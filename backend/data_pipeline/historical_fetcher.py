"""
Historical Data Fetcher — pulls FPL season history + Understat xG data.

Sources:
  - FPL historical data: vaastav/Fantasy-Premier-League GitHub (CSV files)
    Contains all seasons from 2016-17 onward, per-GW per-player stats.
  - Understat: real xG/xA per match (HTML scrape, already in StatsAgent)

This module downloads and compiles a training dataset for the LightGBM xPts model.
The resulting DataFrame has columns matching XPTS_FEATURES + actual_points.

Usage:
    fetcher = HistoricalFetcher()
    df = await fetcher.build_training_dataset(seasons=["2023-24", "2024-25"])
    from models.ml.xpts_model import XPtsModel
    model = XPtsModel()
    metrics = model.train(df)
"""
from __future__ import annotations

import asyncio
import io
from pathlib import Path
from typing import Optional
import pandas as pd
import httpx
from loguru import logger

# vaastav's FPL dataset on GitHub — public, no auth needed
VAASTAV_BASE = "https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/master/data"
CACHE_DIR = Path("models/ml/historical_data")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Available seasons (add new ones as they become available)
AVAILABLE_SEASONS = [
    "2019-20", "2020-21", "2021-22", "2022-23", "2023-24", "2024-25"
]


class HistoricalFetcher:
    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers={"User-Agent": "FPL Intelligence Bot 1.0"},
        )
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.aclose()

    async def _fetch_csv(self, url: str) -> Optional[pd.DataFrame]:
        """Fetch a CSV URL and return a DataFrame, or None on failure."""
        try:
            r = await self._client.get(url)
            if r.status_code == 200:
                return pd.read_csv(io.StringIO(r.text))
            logger.warning(f"historical_fetcher: {url} returned {r.status_code}")
            return None
        except Exception as e:
            logger.warning(f"historical_fetcher fetch failed {url}: {e}")
            return None

    async def fetch_season_gw_data(self, season: str) -> Optional[pd.DataFrame]:
        """
        Fetch merged per-GW per-player data for a season.
        vaastav provides merged_gw.csv with all GWs combined.
        """
        cache_file = CACHE_DIR / f"{season}_merged_gw.csv"
        if cache_file.exists():
            logger.info(f"historical_fetcher: loading cached {season}")
            return pd.read_csv(cache_file)

        url = f"{VAASTAV_BASE}/{season}/gws/merged_gw.csv"
        df = await self._fetch_csv(url)
        if df is not None:
            df["season"] = season
            df.to_csv(cache_file, index=False)
            logger.info(f"historical_fetcher: downloaded {season} → {len(df)} rows")
        return df

    async def fetch_season_players(self, season: str) -> Optional[pd.DataFrame]:
        """Fetch player-level season summary (for price, position, team)."""
        cache_file = CACHE_DIR / f"{season}_players.csv"
        if cache_file.exists():
            return pd.read_csv(cache_file)

        url = f"{VAASTAV_BASE}/{season}/players_raw.csv"
        df = await self._fetch_csv(url)
        if df is not None:
            df["season"] = season
            df.to_csv(cache_file, index=False)
        return df

    def _engineer_features(self, gw_df: pd.DataFrame) -> pd.DataFrame:
        """
        Transform raw vaastav GW data into XPTS_FEATURES-compatible columns.

        vaastav columns of interest:
          total_points, minutes, goals_scored, assists, clean_sheets,
          goals_conceded, yellow_cards, red_cards, saves, bonus, bps,
          ict_index, transfers_in, transfers_out, selected, value (price×10),
          position (GK/DEF/MID/FWD), team, fixture, was_home, round (GW),
          xP (FPL's own expected_points), opponent_team, expected_goals, expected_assists
        """
        df = gw_df.copy()

        # Position dummies
        df["is_gk"]  = (df.get("position", "") == "GK").astype(int)
        df["is_def"] = (df.get("position", "") == "DEF").astype(int)
        df["is_mid"] = (df.get("position", "") == "MID").astype(int)
        df["is_fwd"] = (df.get("position", "") == "FWD").astype(int)

        # Price in millions (vaastav stores value×10)
        df["price_millions"] = df.get("value", 0) / 10

        # xG/xA per 90 (from vaastav's expected_goals/expected_assists if available)
        minutes = df.get("minutes", pd.Series([90] * len(df))).replace(0, 90)
        df["xg_per_90"] = (df.get("expected_goals", df.get("goals_scored", 0)) / minutes * 90).fillna(0)
        df["xa_per_90"] = (df.get("expected_assists", df.get("assists", 0)) / minutes * 90).fillna(0)
        df["npxg_per_90"] = df["xg_per_90"]  # approximation without npxG separately

        # ICT index (available directly)
        df["ict_index"] = pd.to_numeric(df.get("ict_index", 0), errors="coerce").fillna(0)

        # Form — rolling 5-GW average of total_points
        df = df.sort_values(["name", "round"])
        df["form"] = df.groupby("name")["total_points"].transform(
            lambda x: x.shift(1).rolling(5, min_periods=1).mean()
        ).fillna(0)

        # Points per game (cumulative up to prior GW)
        df["points_per_game"] = df.groupby("name")["total_points"].transform(
            lambda x: x.shift(1).expanding().mean()
        ).fillna(0)

        # BPS per 90
        df["bps_per_90"] = (df.get("bps", 0) / minutes * 90).fillna(0)

        # Fixture difficulty — vaastav doesn't include FDR directly; use opponent rank proxy
        df["fdr_next"] = 3.0  # neutral placeholder for historical data

        # Home/away
        df["is_home_next"] = df.get("was_home", False).astype(int)

        # Blank/double GW indicators (all historical are normal GWs)
        df["blank_gw"] = 0
        df["double_gw"] = 0

        # Team strength proxies (simplified)
        df["team_strength_attack"] = 3.0
        df["opponent_strength_defence"] = 3.0
        df["team_win_probability"] = 0.5

        # Set piece taker (not in vaastav — default 0)
        df["is_set_piece_taker"] = 0

        # Ownership
        df["selected_by_percent"] = pd.to_numeric(
            df.get("selected", 0), errors="coerce"
        ).fillna(0) / 1000  # vaastav stores as count, normalize

        # Transfer delta
        df["transfers_in_event_delta"] = (
            pd.to_numeric(df.get("transfers_in", 0), errors="coerce").fillna(0) -
            pd.to_numeric(df.get("transfers_out", 0), errors="coerce").fillna(0)
        )

        # Predicted start/60min probs — not in historical, use minutes as proxy
        df["predicted_start_prob"] = (minutes >= 45).astype(float)
        df["predicted_60min_prob"] = (minutes >= 60).astype(float)

        # Target variable
        df["actual_points"] = pd.to_numeric(df.get("total_points", 0), errors="coerce").fillna(0)

        return df

    async def build_training_dataset(
        self,
        seasons: Optional[list[str]] = None,
    ) -> pd.DataFrame:
        """
        Download and compile training data across multiple seasons.
        Returns a DataFrame with XPTS_FEATURES + actual_points.
        """
        if seasons is None:
            seasons = AVAILABLE_SEASONS[-3:]  # default: last 3 seasons

        all_dfs: list[pd.DataFrame] = []
        for season in seasons:
            df = await self.fetch_season_gw_data(season)
            if df is not None:
                engineered = self._engineer_features(df)
                all_dfs.append(engineered)
                logger.info(f"historical_fetcher: engineered {season} → {len(engineered)} rows")

        if not all_dfs:
            logger.warning("historical_fetcher: no data fetched")
            return pd.DataFrame()

        combined = pd.concat(all_dfs, ignore_index=True)
        logger.info(f"historical_fetcher: combined training set = {len(combined)} rows from {len(seasons)} seasons")
        return combined

    async def retrain_xpts_model(
        self,
        seasons: Optional[list[str]] = None,
    ) -> dict:
        """
        Convenience method: build dataset + retrain xPts model.
        Returns training metrics.
        """
        from models.ml.xpts_model import XPtsModel

        df = await self.build_training_dataset(seasons=seasons)
        if df.empty:
            return {"error": "No training data available"}

        model = XPtsModel()
        metrics = model.train(df)
        logger.info(f"historical_fetcher: model retrained → {metrics}")
        return metrics

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

# The current season is updated by vaastav throughout the season — re-download
# weekly so new GWs are included in retraining. Completed seasons are immutable.
CURRENT_SEASON = AVAILABLE_SEASONS[-1]
CURRENT_SEASON_CACHE_TTL_SECONDS = 7 * 24 * 3600  # 7 days


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

    def _cache_is_valid(self, cache_file: Path, season: str) -> bool:
        """
        Completed seasons: cache is permanent (vaastav data is immutable).
        Current season: re-download after CURRENT_SEASON_CACHE_TTL_SECONDS so new
        GWs are included in monthly retraining.
        """
        if not cache_file.exists():
            return False
        if season != CURRENT_SEASON:
            return True  # Historical seasons never change
        import time
        age = time.time() - cache_file.stat().st_mtime
        return age < CURRENT_SEASON_CACHE_TTL_SECONDS

    async def fetch_season_gw_data(self, season: str) -> Optional[pd.DataFrame]:
        """
        Fetch merged per-GW per-player data for a season.
        vaastav provides merged_gw.csv with all GWs combined.

        Cache policy:
          - Completed seasons: permanent cache (data is immutable).
          - Current season: re-downloaded weekly so new GWs are included in retraining.
        """
        cache_file = CACHE_DIR / f"{season}_merged_gw.csv"
        if self._cache_is_valid(cache_file, season):
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
        if self._cache_is_valid(cache_file, season):
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

        IMPORTANT: All rolling/lagged features use shift(1) to avoid data leakage —
        the target (actual_points for GW N) must not see GW N's own stats.
        """
        import numpy as _np

        df = gw_df.copy()

        # ── Sort for ordered rolling ops ─────────────────────────────────────
        df = df.sort_values(["name", "season", "round"]).reset_index(drop=True)

        # ── Position dummies ─────────────────────────────────────────────────
        pos = df.get("position", pd.Series(["MID"] * len(df)))
        df["is_gk"]  = (pos == "GK").astype(int)
        df["is_def"] = (pos == "DEF").astype(int)
        df["is_mid"] = (pos == "MID").astype(int)
        df["is_fwd"] = (pos == "FWD").astype(int)

        # ── Price in millions ────────────────────────────────────────────────
        df["price_millions"] = pd.to_numeric(df.get("value", 0), errors="coerce").fillna(50) / 10

        # ── Extract raw source columns FIRST (before any rolling ops) ──────────
        total_pts  = pd.to_numeric(df.get("total_points", 0), errors="coerce").fillna(0)
        mins       = pd.to_numeric(df.get("minutes", 0), errors="coerce").fillna(0)
        xg_raw     = pd.to_numeric(df.get("expected_goals", df.get("goals_scored", 0)), errors="coerce").fillna(0)
        xa_raw     = pd.to_numeric(df.get("expected_assists", df.get("assists", 0)), errors="coerce").fillna(0)
        bps_raw    = pd.to_numeric(df.get("bps", 0), errors="coerce").fillna(0)
        ict_raw    = pd.to_numeric(df.get("ict_index", 0), errors="coerce").fillna(0)
        goals_raw  = pd.to_numeric(df.get("goals_scored", 0), errors="coerce").fillna(0)
        cs_raw     = pd.to_numeric(df.get("clean_sheets", 0), errors="coerce").fillna(0)

        # ── Lagged rolling helpers — ALL shifted by 1 to prevent leakage ─────
        # Group by player + season so GW1 of a new season doesn't bleed prior season stats.
        def _roll5(series: "pd.Series") -> "pd.Series":
            """Shift-1 rolling sum over 5 GWs within player×season group."""
            return series.groupby([df["name"], df["season"]]).transform(
                lambda x: x.shift(1).rolling(5, min_periods=1).sum()
            ).fillna(0)

        def _roll5_mean(series: "pd.Series") -> "pd.Series":
            return series.groupby([df["name"], df["season"]]).transform(
                lambda x: x.shift(1).rolling(5, min_periods=1).mean()
            ).fillna(0)

        # Pre-compute rolling sums used by both per-90 and 5-GW feature columns
        xg_roll5   = _roll5(xg_raw)
        xa_roll5   = _roll5(xa_raw)
        bps_roll5  = _roll5(bps_raw)
        mins_roll5 = _roll5(mins)
        # Safe denominator: at least 5 min so we don't divide near-zero
        mins_roll5_safe = mins_roll5.clip(lower=5)

        # ── Per-90 stats — computed from LAGGED rolling window (ZERO leakage) ─
        # Using current-GW minutes/xG to normalise would reveal the match outcome.
        # Instead we compute per-90 rates from the prior 5 GWs, which is exactly
        # the information available at prediction time.
        df["xg_per_90"]   = (xg_roll5 / mins_roll5_safe * 90).clip(0, 5)
        df["xa_per_90"]   = (xa_roll5 / mins_roll5_safe * 90).clip(0, 5)
        df["npxg_per_90"] = df["xg_per_90"]   # vaastav has no separate npxG
        df["bps_per_90"]  = (bps_roll5 / mins_roll5_safe * 90).clip(0, 100)

        # ICT index — rolling mean of last 5 GWs (shift=1, no leakage)
        df["ict_index"] = _roll5_mean(ict_raw)

        # ── Rolling 5-GW form signals (reuse pre-computed sums) ──────────────
        # Form: rolling 5-GW average total_points (shift=1, no leakage)
        df["form"] = _roll5_mean(total_pts)

        # Points per game: expanding mean (shift=1, no leakage)
        df["points_per_game"] = total_pts.groupby([df["name"], df["season"]]).transform(
            lambda x: x.shift(1).expanding().mean()
        ).fillna(0)

        # Rolling 5-GW sums (reuse pre-computed rolls where possible)
        df["xg_last_5_gws"]    = xg_roll5
        df["xa_last_5_gws"]    = xa_roll5
        df["goals_last_5_gws"] = _roll5(goals_raw)
        df["cs_last_5_gws"]    = _roll5(cs_raw)
        df["pts_last_5_gws"]   = _roll5(total_pts)

        # Minutes trend: sum_last5 / sum_prev5 (ratio > 1 = improving minutes)
        mins5      = mins_roll5   # already computed above
        mins_prev5 = mins.groupby([df["name"], df["season"]]).transform(
            lambda x: x.shift(6).rolling(5, min_periods=1).sum()
        ).fillna(0)
        df["minutes_trend"] = (mins5 / (mins_prev5 + 1)).clip(0, 3)

        # ── Predicted start/60min prob — LAGGED minutes (no leakage) ─────────
        # Using same-GW actual minutes would be pure target leakage (reveals if
        # the player actually played, which directly determines points earned).
        mins_lag1 = mins.groupby([df["name"], df["season"]]).transform(
            lambda x: x.shift(1)
        ).fillna(45)  # GW1: assume 45 min as neutral prior
        df["predicted_start_prob"] = (mins_lag1 >= 45).astype(float)
        df["predicted_60min_prob"] = (mins_lag1 >= 60).astype(float)

        # ── Home/away (current GW fixture) ───────────────────────────────────
        df["is_home_next"] = df.get("was_home", pd.Series([False] * len(df))).astype(int)

        # ── FDR proxy from opponent goals conceded ────────────────────────────
        # Build opponent_goals_conceded = goals_scored by player's team vs opponent
        # Proxy: use goals_conceded column as the opponent's defensive weakness signal
        # FDR proxy: map goals conceded by opponent (high = easier fixture)
        # Scaled 1-5 like FDR (higher = harder for defence, easier for attack)
        gc_raw = pd.to_numeric(df.get("goals_conceded", 0), errors="coerce").fillna(0)
        # Team avg goals conceded per 90 in last 5 GWs (as opposition proxy)
        # Use opponent_team column if available
        opp_col = df.get("opponent_team", None)
        if opp_col is not None and opp_col.notna().any():
            # Per-opponent rolling avg goals conceded (proxy for defensive difficulty)
            opp_gc = gc_raw.groupby([df.get("opponent_team", df["name"]), df["season"]]).transform(
                lambda x: x.shift(1).rolling(5, min_periods=1).mean()
            ).fillna(1.0)
            # Map to FDR-like scale: low gc = strong defence (hard fixture = high FDR)
            # opponent gc of 0.5 → FDR 4 (hard), gc of 2.0 → FDR 2 (easy)
            df["fdr_next"] = (5.0 - opp_gc.clip(0, 4)).round(1)
            df["opponent_goals_conceded_per90"] = opp_gc.clip(0, 5)
        else:
            df["fdr_next"] = 3.0  # neutral — no opponent info available
            df["opponent_goals_conceded_per90"] = 1.3

        # ── Features that can't be reliably reconstructed from historical data ─
        # Leave as neutral values — they're excluded from available_features
        # if not in df, so they won't affect training. Set them for completeness.
        df["blank_gw"]               = 0    # no historical blank GWs in vaastav
        df["double_gw"]              = 0    # no DGW history in per-player CSV
        df["team_strength_attack"]   = 3.0  # unavailable historically
        df["opponent_strength_defence"] = 3.0
        df["team_win_probability"]   = 0.5
        df["is_set_piece_taker"]     = 0

        # ── Ownership and transfers ──────────────────────────────────────────
        # FIX: vaastav "selected" is raw player count (e.g. 2,700,000 for 30% ownership
        # in a 9M-manager season). The live FPL API field "selected_by_percent" is already
        # a percentage (0-100). To match the inference scale we must convert the raw count:
        #   selected_by_percent = selected / (sum_per_gw / 15) * 100
        # because each of the 'total_managers' managers picks 15 players, so
        # sum(selected for all players in a GW) ≈ total_managers × 15.
        # Previous code used /1000 which gave values 0-2700+, completely out of range
        # relative to the inference-time values (0-100), causing the model to treat
        # ALL live players as having ~zero ownership.
        _raw_sel = pd.to_numeric(df.get("selected", 0), errors="coerce").fillna(0)
        # Group by season + round to get per-GW totals
        _gw_total = _raw_sel.groupby(
            [df["season"].values, pd.to_numeric(df.get("round", 1), errors="coerce").fillna(1).values]
        ).transform("sum")
        # selected_by_percent = (raw / (gw_total / 15)) * 100
        df["selected_by_percent"] = (
            _raw_sel * 15.0 / _gw_total.clip(lower=1) * 100.0
        ).clip(0, 100)
        # Log-compress ownership % so popular players aren't penalised.
        # log1p(0)=0, log1p(10)=2.40, log1p(50)=3.93, log1p(100)=4.62
        # Keeps quality signal but squashes the raw magnitude that was causing
        # selected_by_percent to dominate feature importance (rank 2 of 27).
        import numpy as _np_sel
        df["selected_by_percent"] = _np_sel.log1p(df["selected_by_percent"])

        # FIX: Normalize transfers_in_event_delta by total GW transfer volume.
        # Raw counts vary from ~100 to 500,000+ across player/season combinations.
        # The model previously learned "high raw delta = regression" because:
        #   - After a haul, 100k+ managers buy the player (high raw delta)
        #   - That single week was already exceptional → regression next GW
        # This overweighted the regression signal, suppressing form=11 players like
        # Bruno Fernandes to 3.4 xPts (less than form=4.8 Casemiro at 6.6 xPts).
        #
        # Fix: divide by total GW transfer volume → normalized "market flow %" in range
        # roughly -10 to +10. Bruno at 10.7% of week's activity = genuinely popular;
        # this is a POSITIVE bounded signal, not a regression anchor.
        _raw_ti = pd.to_numeric(df.get("transfers_in", 0), errors="coerce").fillna(0)
        _raw_to = pd.to_numeric(df.get("transfers_out", 0), errors="coerce").fillna(0)
        _gw_ti_total = _raw_ti.groupby(
            [df["season"].values, pd.to_numeric(df.get("round", 1), errors="coerce").fillna(1).values]
        ).transform("sum").clip(lower=1)
        df["transfers_in_event_delta"] = (
            (_raw_ti - _raw_to) / _gw_ti_total * 100
        ).clip(-10, 10)

        # ── Season stage ─────────────────────────────────────────────────────
        max_round = df["round"].max() or 38
        df["season_stage"] = ((pd.to_numeric(df.get("round", 1), errors="coerce").fillna(1) - 1) / 37.0).clip(0, 1)

        # ── Target variable ──────────────────────────────────────────────────
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

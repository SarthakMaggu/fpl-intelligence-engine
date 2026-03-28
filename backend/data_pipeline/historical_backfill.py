"""
Historical Backfill Pipeline — ingests the vaastav Fantasy-Premier-League open
dataset and runs full model + strategy backtests for past seasons.

https://github.com/vaastav/Fantasy-Premier-League

Entry points
------------
ingest_vaastav_season(season, db, http_client)
    Downloads merged_gw.csv from GitHub raw, parses it, and bulk-upserts rows
    into the `historical_gw_stats` table.

synthesize_features_for_season(season, db)
    Reads `historical_gw_stats` for the given season, computes rolling 5-GW
    features for every (player, gw) pair, and upserts them into
    `player_features_history` (tagged with the season).

run_full_historical_backtest(db, redis, http_client)
    Orchestrates the complete pipeline for all HISTORICAL_SEASONS:
      ingest → synthesize → model backtest → strategy backtest

run_backtest_for_current_season(db, redis)
    Convenience wrapper — only runs the model + strategy backtest on already-
    existing current-season feature data (no CSV download needed).
"""
from __future__ import annotations

import io
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from loguru import logger
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.db.historical_gw_stats import HistoricalGWStats
from models.db.feature_store import PlayerFeaturesHistory
from models.db.backtest import BacktestModelMetrics, BacktestStrategyMetrics

# Seasons available via the vaastav dataset
HISTORICAL_SEASONS: List[str] = ["2022-23", "2023-24", "2024-25"]

# Model version label used for historical backtest rows in BacktestModelMetrics
HIST_MODEL_VERSION = "historical"

# vaastav GitHub raw URL template
_VAASTAV_URL = (
    "https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League"
    "/master/data/{season}/gws/merged_gw.csv"
)

# Position string → element_type integer
_POSITION_MAP = {"GKP": 1, "DEF": 2, "MID": 3, "FWD": 4}


# ---------------------------------------------------------------------------
# 1. Ingest vaastav CSV into historical_gw_stats
# ---------------------------------------------------------------------------


async def ingest_vaastav_season(
    season: str,
    db: AsyncSession,
    http_client: Any,
) -> int:
    """
    Download the merged_gw.csv for `season` and upsert into historical_gw_stats.

    Returns the number of rows upserted.
    """
    url = _VAASTAV_URL.format(season=season)
    logger.info(f"[backfill] Fetching vaastav CSV for {season}: {url}")

    try:
        resp = await http_client.get(url, timeout=60.0)
        resp.raise_for_status()
        csv_bytes = resp.content
    except Exception as e:
        logger.error(f"[backfill] Failed to download vaastav CSV for {season}: {e}")
        raise

    df = pd.read_csv(io.BytesIO(csv_bytes), low_memory=False)
    logger.info(f"[backfill] Loaded {len(df)} rows for season {season}. Columns: {list(df.columns)}")

    # Normalise column names to lower-case with underscores
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

    # Required columns — rename vaastav names to our schema names.
    # Note: vaastav CSVs have BOTH a `GW` column (normalised to `gw`) AND a
    # `round` column.  Renaming `round`→`gw` would create duplicate column names,
    # causing row["gw"] to return a Series instead of a scalar and every row to
    # be silently skipped.  We only rename `round`→`gw` if `gw` doesn't already
    # exist, and deduplicate columns afterwards as a safety net.
    col_map = {
        "element": "player_id",
        "xp": "expected_points",       # vaastav column is `xP` → normalised to `xp`
    }
    if "gw" not in df.columns:
        col_map["round"] = "gw"
    df = df.rename(columns=col_map)

    # Drop any remaining duplicate column names (keep first occurrence)
    df = df.loc[:, ~df.columns.duplicated(keep="first")]
    logger.info(f"[backfill] Normalised columns for {season}: {list(df.columns)}")

    # Ensure required columns exist
    required = ["player_id", "gw", "total_points", "minutes"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"[backfill] Missing required columns in vaastav CSV: {missing}")

    # Position column may be "position" or "element_type"
    if "position" not in df.columns and "element_type" in df.columns:
        df["position"] = df["element_type"].map(
            {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
        )

    def _safe_int(val, default: int = 0) -> int:
        try:
            return int(float(val)) if pd.notna(val) else default
        except (TypeError, ValueError):
            return default

    def _safe_float(val) -> Optional[float]:
        try:
            return float(val) if pd.notna(val) else None
        except (TypeError, ValueError):
            return None

    upserted = 0
    batch: List[Dict] = []

    for _, row in df.iterrows():
        player_id = _safe_int(row.get("player_id"))
        gw = _safe_int(row.get("gw"))
        if player_id == 0 or gw == 0:
            continue

        record = {
            "season": season,
            "player_id": player_id,
            "gw": gw,
            "position": str(row.get("position", "")) or None,
            "total_points": _safe_int(row.get("total_points")),
            "minutes": _safe_int(row.get("minutes")),
            "goals_scored": _safe_int(row.get("goals_scored")),
            "assists": _safe_int(row.get("assists")),
            "clean_sheets": _safe_int(row.get("clean_sheets")),
            "yellow_cards": _safe_int(row.get("yellow_cards")),
            "red_cards": _safe_int(row.get("red_cards")),
            "saves": _safe_int(row.get("saves")),
            "bonus": _safe_int(row.get("bonus")),
            "bps": _safe_int(row.get("bps")),
            "ict_index": _safe_float(row.get("ict_index")),
            "creativity": _safe_float(row.get("creativity")),
            "threat": _safe_float(row.get("threat")),
            "influence": _safe_float(row.get("influence")),
            "value": _safe_int(row.get("value"), 0) or None,
            "selected": _safe_int(row.get("selected"), 0) or None,
            "transfers_in": _safe_int(row.get("transfers_in"), 0) or None,
            "transfers_out": _safe_int(row.get("transfers_out"), 0) or None,
            "was_home": bool(row.get("was_home")) if pd.notna(row.get("was_home")) else None,
            "team_h_score": _safe_int(row.get("team_h_score"), -1) if pd.notna(row.get("team_h_score")) else None,
            "team_a_score": _safe_int(row.get("team_a_score"), -1) if pd.notna(row.get("team_a_score")) else None,
            "opponent_team": _safe_int(row.get("opponent_team"), 0) or None,
            "expected_points": _safe_float(row.get("expected_points")),
            "expected_goals": _safe_float(row.get("expected_goals")),
            "expected_assists": _safe_float(row.get("expected_assists")),
        }
        # Normalise team_h_score / team_a_score — filter out -1 sentinel
        if record["team_h_score"] == -1:
            record["team_h_score"] = None
        if record["team_a_score"] == -1:
            record["team_a_score"] = None

        batch.append(record)

        # Batch upsert every 500 rows
        if len(batch) >= 500:
            await _upsert_batch(batch, db)
            upserted += len(batch)
            batch = []

    if batch:
        await _upsert_batch(batch, db)
        upserted += len(batch)

    await db.commit()
    logger.info(f"[backfill] Upserted {upserted} rows for season {season}")
    return upserted


async def _upsert_batch(batch: List[Dict], db: AsyncSession) -> None:
    """Bulk upsert a batch of HistoricalGWStats rows.

    PostgreSQL ON CONFLICT DO UPDATE fails with CardinalityViolationError if the
    same conflict key appears more than once in a single batch (the CSV can have
    duplicate rows for the same player+gw due to DGW replays or data issues).
    Deduplicate on (season, player_id, gw) before inserting — last row wins.
    """
    # Deduplicate: keep last occurrence of each (season, player_id, gw)
    deduped: dict[tuple, dict] = {}
    for item in batch:
        key = (item.get("season"), item.get("player_id"), item.get("gw"))
        deduped[key] = item
    batch = list(deduped.values())
    if not batch:
        return

    stmt = (
        pg_insert(HistoricalGWStats)
        .values(batch)
        .on_conflict_do_update(
            constraint="uq_hgws_player_gw_season",
            set_={
                k: pg_insert(HistoricalGWStats).excluded[k]
                for k in batch[0]
                if k not in ("season", "player_id", "gw")
            },
        )
    )
    await db.execute(stmt)


# ---------------------------------------------------------------------------
# 2. Synthesize rolling features from raw historical stats
# ---------------------------------------------------------------------------


async def synthesize_features_for_season(season: str, db: AsyncSession) -> int:
    """
    Read `historical_gw_stats` for `season`, compute rolling 5-GW features for
    every (player, gw) combination, and upsert into `player_features_history`.

    Features computed (stored in features_json JSONB):
      form, pts_last_5, goals_last_5, assists_last_5,
      minutes_pct, clean_sheet_rate, bonus_last_5,
      ict_index, creativity, threat, influence,
      value, selected, xP, was_home,
      position (int: 1=GKP, 2=DEF, 3=MID, 4=FWD),
      predicted_xpts_next  ← set to xP (best available proxy)

    Returns number of feature rows written.
    """
    logger.info(f"[backfill] Synthesizing features for season {season}...")

    # Load all rows for this season ordered by player + gw
    result = await db.execute(
        select(HistoricalGWStats)
        .where(HistoricalGWStats.season == season)
        .order_by(HistoricalGWStats.player_id, HistoricalGWStats.gw)
    )
    rows = result.scalars().all()

    if not rows:
        logger.warning(f"[backfill] No historical_gw_stats rows for season {season}")
        return 0

    # Build per-player GW history as a dict: player_id → list of row dicts (sorted by gw)
    player_history: Dict[int, List[Dict]] = {}
    for r in rows:
        player_history.setdefault(r.player_id, []).append({
            "gw": r.gw,
            "total_points": r.total_points or 0,
            "goals_scored": r.goals_scored or 0,
            "assists": r.assists or 0,
            "minutes": r.minutes or 0,
            "clean_sheets": r.clean_sheets or 0,
            "bonus": r.bonus or 0,
            "ict_index": r.ict_index or 0.0,
            "creativity": r.creativity or 0.0,
            "threat": r.threat or 0.0,
            "influence": r.influence or 0.0,
            "value": r.value or 0,
            "selected": r.selected or 0,
            "expected_points": r.expected_points or 0.0,
            "was_home": int(r.was_home) if r.was_home is not None else 0,
            "position": _POSITION_MAP.get(r.position or "", 3),
        })

    # Sort each player's history by GW
    for pid in player_history:
        player_history[pid].sort(key=lambda x: x["gw"])

    written = 0
    batch: List[Dict] = []

    for player_id, gw_list in player_history.items():
        n = len(gw_list)
        for i, gw_data in enumerate(gw_list):
            # Rolling window: last 5 GWs (exclusive of current for lagged features)
            window = gw_list[max(0, i - 5):i]  # up to 5 GWs before current
            w = len(window)

            def _roll_mean(key: str, default: float = 0.0) -> float:
                if w == 0:
                    return default
                return float(np.mean([g[key] for g in window]))

            def _roll_sum(key: str) -> float:
                if w == 0:
                    return 0.0
                return float(sum(g[key] for g in window))

            form = _roll_mean("total_points")
            pts_last_5 = _roll_sum("total_points")
            goals_last_5 = _roll_sum("goals_scored")
            assists_last_5 = _roll_sum("assists")
            minutes_avg = _roll_mean("minutes")
            minutes_pct = min(1.0, minutes_avg / 90.0)
            clean_sheet_rate = _roll_mean("clean_sheets")
            bonus_last_5 = _roll_sum("bonus")
            ict_index = _roll_mean("ict_index")
            creativity = _roll_mean("creativity")
            threat = _roll_mean("threat")
            influence = _roll_mean("influence")

            # Current-GW static features
            value = gw_data["value"]
            selected = gw_data["selected"]
            expected_points = gw_data["expected_points"]
            was_home = gw_data["was_home"]
            position = gw_data["position"]

            # For next-GW context: look forward 1 GW if available
            if i + 1 < n:
                next_xp = gw_list[i + 1].get("expected_points", expected_points)
                next_was_home = gw_list[i + 1].get("was_home", was_home)
            else:
                next_xp = expected_points
                next_was_home = was_home

            features = {
                "form": round(form, 3),
                "pts_last_5": round(pts_last_5, 1),
                "goals_last_5": round(goals_last_5, 1),
                "assists_last_5": round(assists_last_5, 1),
                "minutes_pct": round(minutes_pct, 3),
                "clean_sheet_rate": round(clean_sheet_rate, 3),
                "bonus_last_5": round(bonus_last_5, 1),
                "ict_index": round(ict_index, 3),
                "creativity": round(creativity, 3),
                "threat": round(threat, 3),
                "influence": round(influence, 3),
                "value": value,
                "selected": selected,
                "xP": round(expected_points, 3),
                "was_home": was_home,
                "position": position,
                # predicted_xpts_next = xP from vaastav (best available proxy for
                # "what the model would have predicted before this GW")
                "predicted_xpts_next": round(next_xp, 3),
            }

            batch.append({
                "player_id": player_id,
                "gw_id": gw_data["gw"],
                "season": season,
                "features_json": features,
            })

            if len(batch) >= 500:
                await _upsert_features_batch(batch, db)
                written += len(batch)
                batch = []

    if batch:
        await _upsert_features_batch(batch, db)
        written += len(batch)

    await db.commit()
    logger.info(
        f"[backfill] Feature synthesis for {season} complete: {written} rows"
    )
    return written


async def _upsert_features_batch(batch: List[Dict], db: AsyncSession) -> None:
    """Bulk upsert player_features_history rows."""
    stmt = (
        pg_insert(PlayerFeaturesHistory)
        .values(batch)
        .on_conflict_do_update(
            constraint="uq_pfh_player_gw_season",
            set_={"features_json": pg_insert(PlayerFeaturesHistory).excluded.features_json},
        )
    )
    await db.execute(stmt)


# ---------------------------------------------------------------------------
# 3. Run model backtest for a season (uses historical feature data)
# ---------------------------------------------------------------------------


async def run_model_backtest_for_season(
    season: str,
    db: AsyncSession,
    model_version: str = HIST_MODEL_VERSION,
    model_obj: Any = None,
) -> List[Dict]:
    """
    Evaluate model predictions vs actuals for every GW in `season`.

    Uses features from `player_features_history` (season-filtered) and actual
    points from `historical_gw_stats`.

    Returns list of per-GW metric dicts.
    """
    import numpy as np
    from scipy.stats import spearmanr

    logger.info(f"[backfill] Running model backtest for season {season}...")

    # Discover GWs that have feature history for this season
    gw_res = await db.execute(
        select(PlayerFeaturesHistory.gw_id)
        .where(PlayerFeaturesHistory.season == season)
        .distinct()
        .order_by(PlayerFeaturesHistory.gw_id)
    )
    gw_ids = [row[0] for row in gw_res.all()]

    if not gw_ids:
        logger.warning(f"[backfill] No feature history for season {season} — run synthesize first")
        return []

    # Load actual points for all GWs in this season from historical_gw_stats
    actuals_res = await db.execute(
        select(
            HistoricalGWStats.player_id,
            HistoricalGWStats.gw,
            HistoricalGWStats.total_points,
        )
        .where(HistoricalGWStats.season == season)
    )
    # actuals_map: (player_id, gw) → total_points
    actuals_map = {
        (row[0], row[1]): float(row[2] or 0.0)
        for row in actuals_res.all()
    }

    # Load model if not provided (use the current model for retroactive evaluation)
    if model_obj is None:
        try:
            from ml.model_loader import get_current_model
            model_obj = await get_current_model("xpts_lgbm")
        except Exception as e:
            logger.warning(f"[backfill] Could not load ML model: {e} — using xP proxy")

    results: List[Dict] = []

    for gw_id in gw_ids:
        try:
            metrics = await _eval_historical_gw(
                gw_id=gw_id,
                season=season,
                model_version=model_version,
                model_obj=model_obj,
                actuals_map=actuals_map,
                db=db,
            )
            if metrics:
                results.append(metrics)
                stmt = (
                    pg_insert(BacktestModelMetrics)
                    .values(**metrics)
                    .on_conflict_do_update(
                        constraint="uq_bmm_version_gw_season",
                        set_={
                            k: v for k, v in metrics.items()
                            if k not in ("id", "model_version", "gw_id", "season", "created_at")
                        },
                    )
                )
                await db.execute(stmt)
        except Exception as e:
            logger.error(f"[backfill] Model eval failed for {season} GW{gw_id}: {e}")

    await db.commit()
    logger.info(
        f"[backfill] Model backtest done for {season}: "
        f"{len(results)} GWs evaluated"
    )
    return results


async def _eval_historical_gw(
    gw_id: int,
    season: str,
    model_version: str,
    model_obj: Any,
    actuals_map: Dict,
    db: AsyncSession,
) -> Optional[Dict]:
    """Evaluate model on a single historical GW."""
    import pandas as pd
    from scipy.stats import spearmanr

    # Load stored features for this GW + season
    feat_res = await db.execute(
        select(PlayerFeaturesHistory.player_id, PlayerFeaturesHistory.features_json)
        .where(
            PlayerFeaturesHistory.gw_id == gw_id,
            PlayerFeaturesHistory.season == season,
        )
    )
    feat_rows = feat_res.all()
    if not feat_rows:
        return None

    player_ids = [r[0] for r in feat_rows]
    feat_dicts = [r[1] for r in feat_rows]

    df = pd.DataFrame(feat_dicts)
    df["player_id"] = player_ids

    # Map actuals
    df["actual_points"] = df["player_id"].map(
        lambda pid: actuals_map.get((pid, gw_id), 0.0)
    ).fillna(0.0)

    # Generate predictions
    if model_obj is not None:
        try:
            from models.ml.xpts_model import XPTS_FEATURES
            available = [f for f in XPTS_FEATURES if f in df.columns]
            X = df[available].fillna(0)
            predictions = np.array(model_obj.predict(X), dtype=float)
        except Exception as e:
            logger.debug(f"[backfill] Model predict failed for GW{gw_id}: {e} — using xP")
            predictions = df.get("predicted_xpts_next", df.get("xP", df.get("form", 0.0))).fillna(0.0).values
    else:
        # Use xP as the prediction proxy when no model is available
        predictions = df.get(
            "predicted_xpts_next", df.get("xP", df.get("form", pd.Series([0.0] * len(df))))
        ).fillna(0.0).values

    actuals_arr = df["actual_points"].values
    mask = ~np.isnan(actuals_arr) & ~np.isnan(predictions)
    if mask.sum() < 5:
        return None

    preds_c = predictions[mask]
    acts_c = actuals_arr[mask]

    mae = float(np.mean(np.abs(preds_c - acts_c)))
    rmse = float(np.sqrt(np.mean((preds_c - acts_c) ** 2)))

    try:
        rank_corr = float(spearmanr(preds_c, acts_c).correlation)
    except Exception:
        rank_corr = 0.0

    top10_actual = set(np.argsort(acts_c)[-10:])
    top10_pred = set(np.argsort(preds_c)[-10:])
    top10_hit_rate = len(top10_actual & top10_pred) / 10.0

    return {
        "model_version": model_version,
        "gw_id": gw_id,
        "season": season,
        "mae": mae,
        "rmse": rmse,
        "rank_corr": rank_corr,
        "top_10_hit_rate": top10_hit_rate,
    }


# ---------------------------------------------------------------------------
# 4. Run strategy backtest for a season
# ---------------------------------------------------------------------------


async def run_strategy_backtest_for_season(
    season: str,
    db: AsyncSession,
) -> Dict[str, List[Dict]]:
    """
    Simulate all three strategies across every GW in `season`.

    Returns dict of strategy_name → list of per-GW results.
    """
    from data_pipeline.backtest import AVAILABLE_STRATEGIES

    logger.info(f"[backfill] Running strategy backtest for season {season}...")

    # Discover GWs with feature history for this season
    gw_res = await db.execute(
        select(PlayerFeaturesHistory.gw_id)
        .where(PlayerFeaturesHistory.season == season)
        .distinct()
        .order_by(PlayerFeaturesHistory.gw_id)
    )
    gw_ids = [row[0] for row in gw_res.all()]

    if not gw_ids:
        logger.warning(f"[backfill] No feature history for season {season}")
        return {}

    # Load actuals once
    actuals_res = await db.execute(
        select(HistoricalGWStats.player_id, HistoricalGWStats.gw, HistoricalGWStats.total_points)
        .where(HistoricalGWStats.season == season)
    )
    actuals_map = {
        (row[0], row[1]): float(row[2] or 0.0)
        for row in actuals_res.all()
    }

    all_results: Dict[str, List[Dict]] = {}

    for strategy in AVAILABLE_STRATEGIES:
        cumulative_pts = 0.0
        strategy_rows: List[Dict] = []

        for gw_id in gw_ids:
            try:
                gw_pts = await _simulate_historical_gw(
                    gw_id=gw_id,
                    season=season,
                    strategy=strategy,
                    actuals_map=actuals_map,
                    db=db,
                )
                cumulative_pts += gw_pts

                row = {
                    "strategy_name": strategy,
                    "gw_id": gw_id,
                    "season": season,
                    "gw_points": gw_pts,
                    "cumulative_points": cumulative_pts,
                    "rank_simulated": None,
                }
                strategy_rows.append(row)

                stmt = (
                    pg_insert(BacktestStrategyMetrics)
                    .values(**row)
                    .on_conflict_do_update(
                        constraint="uq_bsm_strategy_season_gw",
                        set_={
                            "gw_points": gw_pts,
                            "cumulative_points": cumulative_pts,
                        },
                    )
                )
                await db.execute(stmt)

            except Exception as e:
                logger.error(f"[backfill] Strategy sim failed {season} GW{gw_id} ({strategy}): {e}")

        all_results[strategy] = strategy_rows
        logger.info(
            f"[backfill] Strategy '{strategy}' for {season}: "
            f"{len(strategy_rows)} GWs, {cumulative_pts:.1f} total pts"
        )

    await db.commit()
    return all_results


async def _simulate_historical_gw(
    gw_id: int,
    season: str,
    strategy: str,
    actuals_map: Dict,
    db: AsyncSession,
) -> float:
    """Simulate one GW for a given strategy using historical feature data."""
    import pandas as pd

    feat_res = await db.execute(
        select(PlayerFeaturesHistory.player_id, PlayerFeaturesHistory.features_json)
        .where(
            PlayerFeaturesHistory.gw_id == gw_id,
            PlayerFeaturesHistory.season == season,
        )
    )
    feat_rows = feat_res.all()
    if not feat_rows:
        return 0.0

    df = pd.DataFrame([r[1] for r in feat_rows])
    df["player_id"] = [r[0] for r in feat_rows]

    df["actual_points"] = df["player_id"].map(
        lambda pid: actuals_map.get((pid, gw_id), 0.0)
    ).fillna(0.0)

    pred_col = (
        "predicted_xpts_next" if "predicted_xpts_next" in df.columns
        else ("xP" if "xP" in df.columns else "form")
    )
    df["predicted"] = df[pred_col].fillna(0.0)

    if df.empty or df["predicted"].sum() == 0:
        return 0.0

    # Pick top-11 by predicted xPts
    xi = df.nlargest(11, "predicted")
    captain_idx = xi["predicted"].idxmax()

    total_pts = 0.0
    for idx, row in xi.iterrows():
        pts = row["actual_points"]
        if idx == captain_idx:
            pts *= 2  # captain doubling
        total_pts += pts

    # bandit_ilp: simulate average hit cost (~0.3 hits/GW)
    if strategy == "bandit_ilp":
        total_pts -= 4.0 * 0.3

    return float(total_pts)


# ---------------------------------------------------------------------------
# 5. Orchestrator — full historical backtest
# ---------------------------------------------------------------------------


_BACKFILL_STATUS_KEY = "backfill:status"       # "computing" | "complete" | missing
_BACKFILL_STARTED_KEY = "backfill:started_at"  # ISO timestamp


async def run_full_historical_backtest(
    db: AsyncSession,
    redis: Any = None,
    http_client: Any = None,
    seasons: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Full orchestration:
      For each season in `seasons` (default: all 3 historical seasons):
        1. Ingest vaastav CSV → historical_gw_stats
        2. Synthesize features → player_features_history
        3. Run model backtest → backtest_model_metrics
        4. Run strategy backtest → backtest_strategy_metrics

    Sets Redis key `backfill:status` = "computing" at start, "complete" at end.
    Returns a summary dict with per-season stats.
    """
    from datetime import datetime, timezone

    if seasons is None:
        seasons = HISTORICAL_SEASONS

    # Mark as computing in Redis (visible to performance-summary endpoint)
    if redis is not None:
        try:
            await redis.set(_BACKFILL_STATUS_KEY, "computing", ex=3600)  # 1h TTL
            await redis.set(
                _BACKFILL_STARTED_KEY,
                datetime.now(timezone.utc).isoformat(),
                ex=3600,
            )
        except Exception:
            pass

    summary: Dict[str, Any] = {}

    for season in seasons:
        logger.info(f"[backfill] ═══ Starting full historical pipeline for {season} ═══")
        season_summary: Dict[str, Any] = {}

        # ── Step 1: Ingest CSV ────────────────────────────────────────────────
        if http_client is not None:
            try:
                ingested = await ingest_vaastav_season(season, db, http_client)
                season_summary["ingested_rows"] = ingested
            except Exception as e:
                logger.error(f"[backfill] Ingest failed for {season}: {e}")
                season_summary["ingest_error"] = str(e)
                summary[season] = season_summary
                continue
        else:
            # Check if we already have data for this season
            count_res = await db.execute(
                select(HistoricalGWStats)
                .where(HistoricalGWStats.season == season)
                .limit(1)
            )
            if count_res.scalar_one_or_none() is None:
                logger.warning(
                    f"[backfill] No http_client provided and no data for {season} — skipping"
                )
                season_summary["skipped"] = "no_http_client_and_no_data"
                summary[season] = season_summary
                continue
            season_summary["ingested_rows"] = "skipped_already_loaded"

        # ── Step 2: Synthesize features ────────────────────────────────────────
        try:
            feat_count = await synthesize_features_for_season(season, db)
            season_summary["features_synthesized"] = feat_count
        except Exception as e:
            logger.error(f"[backfill] Feature synthesis failed for {season}: {e}")
            season_summary["synthesis_error"] = str(e)
            summary[season] = season_summary
            continue

        # ── Step 3: Model backtest ────────────────────────────────────────────
        try:
            model_metrics = await run_model_backtest_for_season(season, db)
            season_summary["model_gws_evaluated"] = len(model_metrics)
            if model_metrics:
                maes = [m["mae"] for m in model_metrics]
                season_summary["avg_mae"] = round(float(np.mean(maes)), 3)
                season_summary["avg_hit_rate"] = round(
                    float(np.mean([m["top_10_hit_rate"] for m in model_metrics])), 3
                )
        except Exception as e:
            logger.error(f"[backfill] Model backtest failed for {season}: {e}")
            season_summary["model_backtest_error"] = str(e)

        # ── Step 4: Strategy backtest ─────────────────────────────────────────
        try:
            strategy_results = await run_strategy_backtest_for_season(season, db)
            season_summary["strategy_gws"] = {
                k: len(v) for k, v in strategy_results.items()
            }
            if "bandit_ilp" in strategy_results and strategy_results["bandit_ilp"]:
                bandit_last = strategy_results["bandit_ilp"][-1]
                baseline_last = (strategy_results.get("baseline_no_transfer") or [{}])[-1]
                season_summary["bandit_cumulative_pts"] = bandit_last.get("cumulative_points")
                season_summary["baseline_cumulative_pts"] = baseline_last.get("cumulative_points")
        except Exception as e:
            logger.error(f"[backfill] Strategy backtest failed for {season}: {e}")
            season_summary["strategy_backtest_error"] = str(e)

        summary[season] = season_summary
        logger.info(f"[backfill] ═══ Season {season} complete: {season_summary} ═══")

    # Mark as complete in Redis
    if redis is not None:
        try:
            await redis.set(_BACKFILL_STATUS_KEY, "complete", ex=86400 * 7)  # 7-day TTL
        except Exception:
            pass

    return summary


# ---------------------------------------------------------------------------
# 6. Current-season backtest (no CSV download)
# ---------------------------------------------------------------------------


async def run_backtest_for_current_season(
    db: AsyncSession,
    redis: Any = None,
    season: str = "2024-25",
) -> Dict[str, Any]:
    """
    Run model + strategy backtest for the current season using existing
    player_features_history rows (written by the live pipeline).

    No vaastav download needed — actuals come from player_gw_history.
    """
    from data_pipeline.backtest import run_model_backtest, run_strategy_backtest, AVAILABLE_STRATEGIES
    from ml.model_loader import get_current_model

    logger.info(f"[backfill] Running current-season backtest for {season}")

    try:
        model_obj = await get_current_model("xpts_lgbm")
        model_version = getattr(model_obj, "version", "current")
    except Exception as e:
        logger.warning(f"[backfill] Could not load model: {e}")
        model_obj = None
        model_version = "current"

    model_results = await run_model_backtest(
        model_version=model_version,
        seasons=[season],
        db=db,
        model_obj=model_obj,
    )

    strategy_results = {}
    for strategy in AVAILABLE_STRATEGIES:
        rows = await run_strategy_backtest(strategy=strategy, seasons=[season], db=db, season=season)
        strategy_results[strategy] = rows

    return {
        "season": season,
        "model_gws": len(model_results),
        "strategy_gws": {k: len(v) for k, v in strategy_results.items()},
    }

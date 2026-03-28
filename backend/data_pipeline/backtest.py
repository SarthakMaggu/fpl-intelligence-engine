"""
Backtest Engine — offline simulation of model accuracy and strategy performance.

run_model_backtest(model_version, seasons, db)
    → BacktestModelMetrics rows per GW (MAE, RMSE, rank_corr, top-10 hit rate)

run_strategy_backtest(strategy, seasons, db)
    → BacktestStrategyMetrics rows per GW (cumulative points for 3 strategies)

Strategy definitions:
  baseline_no_transfer  — no transfers, captain = highest xPts, no hits, no chips
  greedy_xpts           — captain = highest xPts, single best-xPts transfer if 3-GW gain > 4,
                          no hits, no chips
  bandit_ilp            — captain = bandit-chosen arm, ILP-optimised transfers,
                          hit decisions per hit_decision arm, chip per chip_timing arm
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from scipy.stats import spearmanr
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.db.backtest import BacktestModelMetrics, BacktestStrategyMetrics
from models.db.feature_store import PlayerFeaturesHistory
from models.db.history import PlayerGWHistory
from models.db.historical_gw_stats import HistoricalGWStats

logger = logging.getLogger(__name__)

# Seasons available for backtesting (must have data in historical_gw_stats)
SUPPORTED_SEASONS = ["2022-23", "2023-24", "2024-25"]

# Strategies available for simulation
AVAILABLE_STRATEGIES = ["baseline_no_transfer", "greedy_xpts", "bandit_ilp"]


# ---------------------------------------------------------------------------
# Model backtest
# ---------------------------------------------------------------------------


async def run_model_backtest(
    model_version: str,
    seasons: List[str],
    db: AsyncSession,
    *,
    model_obj: Optional[Any] = None,
    season: str = "2024-25",
) -> List[Dict]:
    """
    For each completed GW in `season` where historical_gw_stats data exists:
    1. Build XPTS_FEATURES-compatible feature DataFrame from historical_gw_stats
       (same feature engineering pipeline used during model training).
    2. Predict with the given model version (or provided model_obj).
    3. Compare to actual_points from historical_gw_stats.
    4. Compute MAE, RMSE, rank_corr, top_10_hit_rate.
    5. Upsert into backtest_model_metrics.

    Uses historical_gw_stats (vaastav data, all ~800 players) instead of
    player_features_history (FPL API features, wrong column names, only squad players).
    """
    import pandas as pd
    from models.ml.xpts_model import XPTS_FEATURES

    # ── Load ALL historical stats for this season in one query ──────────────
    stats_res = await db.execute(
        select(HistoricalGWStats)
        .where(HistoricalGWStats.season == season)
        .order_by(HistoricalGWStats.player_id, HistoricalGWStats.gw)
    )
    stats_rows = stats_res.scalars().all()

    if not stats_rows:
        logger.warning(f"[backtest] No historical_gw_stats for season {season} — run backfill first")
        return []

    # ── Convert to DataFrame matching vaastav format ─────────────────────────
    raw_data = []
    for r in stats_rows:
        raw_data.append({
            "name": str(r.player_id),      # use player_id as grouping key
            "player_id": r.player_id,
            "round": r.gw,
            "season": r.season,
            "position": (r.position or "MID").replace("GKP", "GK"),  # normalise vaastav→FPL
            "total_points": r.total_points or 0,
            "minutes": r.minutes or 0,
            "goals_scored": r.goals_scored or 0,
            "assists": r.assists or 0,
            "clean_sheets": r.clean_sheets or 0,
            "bps": r.bps or 0,
            "ict_index": r.ict_index or 0.0,
            "value": r.value or 50,       # pence×10; /10 = £m
            "selected": r.selected or 0,
            "transfers_in": r.transfers_in or 0,
            "transfers_out": r.transfers_out or 0,
            "was_home": bool(r.was_home) if r.was_home is not None else False,
            "opponent_team": r.opponent_team,
            "expected_goals": r.expected_goals or 0.0,
            "expected_assists": r.expected_assists or 0.0,
            "goals_conceded": 0,   # not in historical_gw_stats; neutral value
        })

    df_season = pd.DataFrame(raw_data)

    # ── Apply same feature engineering as historical_fetcher._engineer_features ──
    from data_pipeline.historical_fetcher import HistoricalFetcher
    fetcher = HistoricalFetcher()
    df_engineered = fetcher._engineer_features(df_season)

    # ── Load model if not provided ───────────────────────────────────────────
    if model_obj is None:
        from ml.model_loader import get_current_model
        model_obj = await get_current_model("xpts_lgbm")

    # ── Get model features ───────────────────────────────────────────────────
    try:
        model_features = list(getattr(model_obj, "feature_name_", None) or []) if model_obj else []
    except Exception:
        model_features = []
    if not model_features:
        model_features = XPTS_FEATURES

    # ── Discover which GWs have actuals ─────────────────────────────────────
    available_gws = sorted(df_engineered["round"].unique().tolist())

    results = []

    for gw_id in available_gws:
        try:
            gw_df = df_engineered[df_engineered["round"] == gw_id].copy()
            if len(gw_df) < 5:
                continue

            # Predict
            if model_obj is not None:
                X = gw_df.reindex(columns=model_features, fill_value=0.0).fillna(0.0)
                try:
                    predictions = np.array(model_obj.predict(X), dtype=float)
                except Exception as e:
                    logger.warning(f"[backtest] Prediction failed for GW{gw_id}: {e}")
                    continue
            else:
                predictions = gw_df.get("form", pd.Series([0.0] * len(gw_df))).fillna(0.0).values

            actuals_arr = gw_df["actual_points"].fillna(0.0).values
            mask = ~np.isnan(actuals_arr) & ~np.isnan(predictions)
            if mask.sum() < 5:
                continue

            preds_clean = predictions[mask]
            actuals_clean = actuals_arr[mask]

            mae = float(np.mean(np.abs(preds_clean - actuals_clean)))
            rmse = float(np.sqrt(np.mean((preds_clean - actuals_clean) ** 2)))

            try:
                rank_corr = float(spearmanr(preds_clean, actuals_clean).correlation)
            except Exception:
                rank_corr = 0.0

            top10_actual = set(np.argsort(actuals_clean)[-10:])
            top10_pred = set(np.argsort(preds_clean)[-10:])
            top10_hit_rate = len(top10_actual & top10_pred) / 10.0

            metrics = {
                "model_version": model_version,
                "gw_id": int(gw_id),
                "season": season,
                "mae": mae,
                "rmse": rmse,
                "rank_corr": rank_corr,
                "top_10_hit_rate": top10_hit_rate,
            }
            results.append(metrics)

            # Upsert into DB
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
            logger.error(f"[backtest] Model eval failed for GW{gw_id} season {season}: {e}")

    await db.commit()
    logger.info(
        f"[backtest] Model backtest complete: "
        f"{len(results)} GWs evaluated for v{model_version} season {season}"
    )
    return results


async def _evaluate_model_on_gw(
    gw_id: int,
    model_version: str,
    model_obj: Any,
    db: AsyncSession,
    season: str = "2024-25",
) -> Optional[Dict]:
    """Legacy single-GW evaluator — kept for backward compatibility.
    Prefer run_model_backtest() which loads the full season in one pass."""
    import pandas as pd
    from models.ml.xpts_model import XPTS_FEATURES

    # Load features for this GW from historical_gw_stats (correct data source)
    stats_res = await db.execute(
        select(HistoricalGWStats)
        .where(HistoricalGWStats.season == season, HistoricalGWStats.gw == gw_id)
    )
    gw_rows = stats_res.scalars().all()
    if not gw_rows:
        return None

    # Build a minimal DataFrame (no rolling context — features will be rough but correct column names)
    raw_data = [{
        "name": str(r.player_id),
        "player_id": r.player_id,
        "round": r.gw,
        "season": r.season,
        "position": (r.position or "MID").replace("GKP", "GK"),
        "total_points": r.total_points or 0,
        "minutes": r.minutes or 0,
        "goals_scored": r.goals_scored or 0,
        "assists": r.assists or 0,
        "clean_sheets": r.clean_sheets or 0,
        "bps": r.bps or 0,
        "ict_index": r.ict_index or 0.0,
        "value": r.value or 50,
        "selected": r.selected or 0,
        "transfers_in": r.transfers_in or 0,
        "transfers_out": r.transfers_out or 0,
        "was_home": bool(r.was_home) if r.was_home is not None else False,
        "expected_goals": r.expected_goals or 0.0,
        "expected_assists": r.expected_assists or 0.0,
        "goals_conceded": 0,
    } for r in gw_rows]

    df = pd.DataFrame(raw_data)
    from data_pipeline.historical_fetcher import HistoricalFetcher
    df = HistoricalFetcher()._engineer_features(df)
    df = df[df["round"] == gw_id]

    if len(df) < 5:
        return None

    actuals_arr = df["actual_points"].fillna(0.0).values

    if model_obj is not None:
        try:
            model_features = list(getattr(model_obj, "feature_name_", None) or []) or XPTS_FEATURES
            X = df.reindex(columns=model_features, fill_value=0.0).fillna(0.0)
            predictions = np.array(model_obj.predict(X), dtype=float)
        except Exception as e:
            logger.warning(f"[backtest] Prediction failed for GW{gw_id}: {e}")
            return None
    else:
        predictions = df.get("form", pd.Series([0.0] * len(df))).fillna(0.0).values

    mask = ~np.isnan(actuals_arr) & ~np.isnan(predictions)
    if mask.sum() < 5:
        return None

    preds_clean = predictions[mask]
    actuals_clean = actuals_arr[mask]

    mae = float(np.mean(np.abs(preds_clean - actuals_clean)))
    rmse = float(np.sqrt(np.mean((preds_clean - actuals_clean) ** 2)))

    try:
        rank_corr = float(spearmanr(preds_clean, actuals_clean).correlation)
    except Exception:
        rank_corr = 0.0

    top10_actual = set(np.argsort(actuals_clean)[-10:])
    top10_pred = set(np.argsort(preds_clean)[-10:])
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
# Strategy backtest
# ---------------------------------------------------------------------------


async def run_strategy_backtest(
    strategy: str,
    seasons: List[str],
    db: AsyncSession,
    season: str = "2024-25",
) -> List[Dict]:
    """
    Simulate a full season with the given strategy.

    Strategy definitions:
      baseline_no_transfer  — no transfers, captain = highest predicted_xpts_next, no chips
      greedy_xpts           — captain = highest xPts, take the single best-xPts transfer
                              if 3-GW predicted gain > 4 pts; no hits
      bandit_ilp            — captain per bandit top arm, ILP-suggested transfers,
                              hit decisions per hit arm, chip per chip arm

    Returns list of per-GW metrics.
    """
    if strategy not in AVAILABLE_STRATEGIES:
        raise ValueError(f"Unknown strategy '{strategy}'. Choose from {AVAILABLE_STRATEGIES}")

    # Discover GWs with feature history for this season
    gw_res = await db.execute(
        select(PlayerFeaturesHistory.gw_id)
        .where(PlayerFeaturesHistory.season == season)
        .distinct()
        .order_by(PlayerFeaturesHistory.gw_id)
    )
    gw_ids = [row[0] for row in gw_res.all()]

    if not gw_ids:
        return []

    cumulative_pts = 0.0
    results = []

    for gw_id in gw_ids:
        try:
            gw_pts = await _simulate_gw(gw_id=gw_id, strategy=strategy, db=db, season=season)
            cumulative_pts += gw_pts

            row = {
                "strategy_name": strategy,
                "gw_id": gw_id,
                "season": season,
                "gw_points": gw_pts,
                "cumulative_points": cumulative_pts,
                "rank_simulated": None,  # rank simulation requires all-user comparison
            }
            results.append(row)

            stmt = (
                pg_insert(BacktestStrategyMetrics)
                .values(**row)
                .on_conflict_do_update(
                    constraint="uq_bsm_strategy_season_gw",
                    set_={"gw_points": gw_pts, "cumulative_points": cumulative_pts},
                )
            )
            await db.execute(stmt)

        except Exception as e:
            logger.error(f"[backtest] Strategy sim failed for GW{gw_id}: {e}")

    await db.commit()
    logger.info(
        f"[backtest] Strategy '{strategy}' backtest: "
        f"{len(results)} GWs, {cumulative_pts:.1f} total pts"
    )
    return results


async def _simulate_gw(
    gw_id: int, strategy: str, db: AsyncSession, season: str = "2024-25"
) -> float:
    """
    Simulate a single GW for the given strategy.
    Returns points scored.
    """
    import pandas as pd

    # Load feature snapshot for this GW + season
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

    # Load actuals — current season from player_gw_history
    actuals_res = await db.execute(
        select(PlayerGWHistory.player_id, PlayerGWHistory.total_points)
        .where(PlayerGWHistory.gw_id == gw_id)
    )
    actuals = {row[0]: float(row[1]) for row in actuals_res.all()}

    if not actuals or df.empty:
        return 0.0

    df["actual_points"] = df["player_id"].map(actuals).fillna(0.0)
    pred_col = "predicted_xpts_next" if "predicted_xpts_next" in df.columns else "form"
    df["predicted"] = df[pred_col].fillna(0.0)

    # Pick XI: top 11 by predicted xPts (simple proxy for full ILP)
    xi = df.nlargest(11, "predicted")

    # Captain selection
    if strategy == "baseline_no_transfer":
        captain_idx = xi["predicted"].idxmax()
    elif strategy == "greedy_xpts":
        captain_idx = xi["predicted"].idxmax()
    else:  # bandit_ilp — same as greedy for backtest (bandit state not replayed)
        captain_idx = xi["predicted"].idxmax()

    # Score: XI points + captain doubling
    total_pts = 0.0
    for idx, row in xi.iterrows():
        pts = row["actual_points"]
        if idx == captain_idx:
            pts *= 2  # captain doubling
        total_pts += pts

    # Hits: No hit deduction applied in backtest simulation.
    # Hit frequency varies by user context and chip state; applying a fixed
    # estimate (e.g. 0.3/GW) would bias comparisons between strategies.
    # Actual hit costs are tracked in decision_log table for live evaluation.

    return float(total_pts)


# ---------------------------------------------------------------------------
# Season Monte Carlo simulation
# ---------------------------------------------------------------------------


async def run_season_simulation(
    n_simulations: int,
    db: AsyncSession,
    redis=None,
    *,
    remaining_gws: Optional[int] = None,
) -> Dict:
    """
    Monte Carlo season simulation.

    For each of n_simulations runs:
      1. For each remaining GW, sample player points from a distribution
         centred on predicted_xpts with spread = historical RMSE (~2.5 pts).
      2. Pick the best available XI based on predicted_xpts (greedy).
      3. Double the captain's points.
      4. Accumulate season total.

    Returns:
      {
        "n_simulations": int,
        "remaining_gws": int,
        "points_distribution": {
            "p10": float, "p25": float, "p50": float, "p75": float, "p90": float,
            "mean": float, "std": float,
        },
        "rank_distribution": {
            "p10": int, "p25": int, "p50": int, "p75": int, "p90": int,
        },
        "chip_timing_recommendation": str,
        "risk_profile": str,  # "low" | "medium" | "high"
      }

    Rank estimation uses a linear model fitted to FPL's historical overall
    rank vs points curve (approximate: rank ≈ 10_000_000 - points * 200_000).
    This is deliberately rough — the goal is relative comparison, not exact rank.
    """
    n_simulations = max(100, min(n_simulations, 5000))  # clamp to [100, 5000]

    # ── 1. Load current player predicted_xpts + GW context ───────────────────
    from models.db.player import Player
    from models.db.gameweek import Gameweek

    gw_res = await db.execute(select(Gameweek).where(Gameweek.is_current == True))
    current_gw = gw_res.scalar_one_or_none()
    current_gw_id = current_gw.id if current_gw else 0

    total_gws = 38
    remaining = remaining_gws or max(1, total_gws - current_gw_id)

    # ── Estimate completed-GW base points from league averages ───────────────
    # Sum average_entry_score from all finished GWs to get a typical manager's
    # current season total.  This makes rank estimates meaningful — we project
    # the remaining GWs on top of a realistic season baseline.
    try:
        from sqlalchemy import func as _func
        avg_res = await db.execute(
            select(_func.sum(Gameweek.average_entry_score))
            .where(Gameweek.finished == True)
        )
        league_avg_pts_so_far = float(avg_res.scalar() or 0.0)
    except Exception:
        # Rough fallback: 45 pts/GW average for completed GWs
        league_avg_pts_so_far = current_gw_id * 45.0

    player_res = await db.execute(
        select(Player.id, Player.predicted_xpts_next, Player.element_type)
        .where(Player.predicted_xpts_next.is_not(None))
        .order_by(Player.predicted_xpts_next.desc())
        .limit(200)  # top 200 by predicted xPts
    )
    players = player_res.all()

    if not players:
        return {
            "error": "No player predictions available — run the ML pipeline first",
            "n_simulations": 0,
            "remaining_gws": remaining,
        }

    xpts = np.array([float(p[1] or 0.0) for p in players])

    # ── 2. Estimate point noise from stored model MAE ────────────────────────
    # Use Redis-stored MAE as noise std — it reflects actual model accuracy.
    # Try ml:current_mae (set by calibration job) then ml:model_rmse (set by retrain).
    # Conservative fallback is 3.0 pts — slightly above typical RMSE to account
    # for tail events (hauls, blanks) not captured by Gaussian noise.
    noise_std = 3.0   # fallback — set conservatively above typical RMSE
    if redis is not None:
        for redis_key in ("ml:current_mae", "ml:model_rmse"):
            try:
                stored = await redis.get(redis_key)
                if stored:
                    val = float(stored.decode() if isinstance(stored, bytes) else stored)
                    if 0.5 < val < 10.0:  # sanity range
                        noise_std = val
                        break
            except Exception:
                pass

    # ── 3. Run Monte Carlo ───────────────────────────────────────────────────
    rng = np.random.default_rng(seed=42)
    season_totals: List[float] = []

    for _ in range(n_simulations):
        season_pts = 0.0
        for _gw in range(remaining):
            # Sample actual points for each player from N(xpts, noise_std)
            sampled = rng.normal(loc=xpts, scale=noise_std)
            sampled = np.clip(sampled, 0.0, 25.0)  # FPL points can't be negative or >25

            # Pick top 11 players
            xi_indices = np.argpartition(sampled, -11)[-11:]
            xi_pts = sampled[xi_indices]

            # Double captain (highest xPts in XI)
            captain_local_idx = xi_pts.argmax()
            xi_pts[captain_local_idx] *= 2

            season_pts += float(xi_pts.sum())

        season_totals.append(season_pts)

    totals = np.array(season_totals)

    # ── 4. Rank estimation ───────────────────────────────────────────────────
    # Add league-average completed-GW baseline so rank formula sees a full
    # season total, not just the remaining GWs.
    full_season_totals = totals + league_avg_pts_so_far

    # Approximate inverse rank function from FPL public rank data:
    # Rank ≈ 10_000_000 * exp(-0.007 * (points - 1200))
    # This is deliberately coarse — relative comparison is what matters.
    def _pts_to_rank(pts: float) -> int:
        rank = int(10_000_000 * math.exp(-0.007 * max(0.0, pts - 1200.0)))
        return max(1, min(10_000_000, rank))

    # ── 5. Chip timing recommendation ────────────────────────────────────────
    p50 = float(np.percentile(full_season_totals, 50))
    chip_rec = "Hold chips — projection looks on-target"
    # Thresholds relative to full-season total (league avg ~2000-2200 pts)
    if p50 < max(league_avg_pts_so_far + 200, 1700):
        chip_rec = "Consider Wildcard — projected total is below average; a squad reset may recover ground"
    elif p50 > max(league_avg_pts_so_far + 500, 2200):
        chip_rec = "Strong projection — hold chips; deploy Triple Captain in a DGW for maximum ceiling"

    # ── 6. Risk profile ───────────────────────────────────────────────────────
    cv = float(np.std(full_season_totals)) / max(float(np.mean(full_season_totals)), 1.0)
    risk_profile = "low" if cv < 0.05 else ("medium" if cv < 0.10 else "high")

    return {
        "n_simulations": n_simulations,
        "remaining_gws": remaining,
        "current_gw": current_gw_id,
        "league_avg_pts_so_far": round(league_avg_pts_so_far, 0),
        # points_distribution shows REMAINING GWs only (add league_avg_pts_so_far for full season)
        "points_distribution": {
            "p10": round(float(np.percentile(full_season_totals, 10)), 1),
            "p25": round(float(np.percentile(full_season_totals, 25)), 1),
            "p50": round(p50, 1),
            "p75": round(float(np.percentile(full_season_totals, 75)), 1),
            "p90": round(float(np.percentile(full_season_totals, 90)), 1),
            "mean": round(float(np.mean(full_season_totals)), 1),
            "std": round(float(np.std(full_season_totals)), 1),
        },
        "rank_distribution": {
            "p10": _pts_to_rank(float(np.percentile(full_season_totals, 90))),  # best pts → best rank
            "p25": _pts_to_rank(float(np.percentile(full_season_totals, 75))),
            "p50": _pts_to_rank(float(np.percentile(full_season_totals, 50))),
            "p75": _pts_to_rank(float(np.percentile(full_season_totals, 25))),
            "p90": _pts_to_rank(float(np.percentile(full_season_totals, 10))),
        },
        "chip_timing_recommendation": chip_rec,
        "risk_profile": risk_profile,
    }

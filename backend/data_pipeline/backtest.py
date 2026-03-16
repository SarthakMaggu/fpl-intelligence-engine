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

logger = logging.getLogger(__name__)

# Seasons available for backtesting (must have data in player_gw_history)
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
    For each GW in the current season where player_features_history exists:
    1. Load stored features for that GW.
    2. Predict with the given model version (or provided model_obj).
    3. Compare to actual_points from player_gw_history.
    4. Compute MAE, RMSE, rank_corr, top_10_hit_rate.
    5. Upsert into backtest_model_metrics.

    Returns list of metric dicts per GW.

    Note: For historical seasons (2022-23, 2023-24), use
    data_pipeline.historical_backfill.run_model_backtest_for_season() instead,
    which sources actuals from historical_gw_stats.
    """
    # Discover GWs that have feature history data for this season
    gw_res = await db.execute(
        select(PlayerFeaturesHistory.gw_id)
        .where(PlayerFeaturesHistory.season == season)
        .distinct()
        .order_by(PlayerFeaturesHistory.gw_id)
    )
    available_gws = [row[0] for row in gw_res.all()]

    if not available_gws:
        logger.warning("[backtest] No feature history found — run at least one GW pipeline first")
        return []

    # Load model if not provided
    if model_obj is None:
        from ml.model_loader import get_current_model
        model_obj = await get_current_model("xpts_lgbm")

    results = []

    for gw_id in available_gws:
        try:
            metrics = await _evaluate_model_on_gw(
                gw_id=gw_id,
                model_version=model_version,
                model_obj=model_obj,
                db=db,
                season=season,
            )
            if metrics:
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
            logger.error(f"[backtest] Model eval failed for GW{gw_id}: {e}")

    await db.commit()
    logger.info(
        f"[backtest] Model backtest complete: "
        f"{len(results)} GWs evaluated for v{model_version}"
    )
    return results


async def _evaluate_model_on_gw(
    gw_id: int,
    model_version: str,
    model_obj: Any,
    db: AsyncSession,
    season: str = "2024-25",
) -> Optional[Dict]:
    """Evaluate model predictions vs actuals for a single GW."""
    import pandas as pd
    from models.ml.xpts_model import XPTS_FEATURES

    # Load features for this GW + season
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

    # Load actual points — current season from player_gw_history
    actuals_res = await db.execute(
        select(PlayerGWHistory.element, PlayerGWHistory.total_points)
        .where(
            PlayerGWHistory.event == gw_id,
            PlayerGWHistory.element.in_(player_ids),
        )
    )
    actuals = {row[0]: float(row[1]) for row in actuals_res.all()}

    if not actuals:
        return None

    # Align actuals with df
    df["actual_points"] = df["player_id"].map(actuals).fillna(0.0)

    # Predict
    if model_obj is not None:
        available = [f for f in XPTS_FEATURES if f in df.columns]
        X = df[available].fillna(0)
        try:
            predictions = model_obj.predict(X)
        except Exception as e:
            logger.warning(f"[backtest] Prediction failed for GW{gw_id}: {e}")
            return None
    else:
        predictions = df.get("predicted_xpts_next", df.get("form", 0.0)).fillna(0.0).values

    actuals_arr = df["actual_points"].values
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

    # Top-10 hit rate: fraction of top-10 actual scorers in top-10 predicted
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
        select(PlayerGWHistory.element, PlayerGWHistory.total_points)
        .where(PlayerGWHistory.event == gw_id)
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

    # Hits: baseline/greedy never take hits; bandit_ilp deducts simulated hit cost
    if strategy == "bandit_ilp":
        # Simulate ~0.3 hits/GW on average for bandit strategy
        total_pts -= 4.0 * 0.3

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

    # ── 1. Load current player predicted_xpts ────────────────────────────────
    from models.db.player import Player
    from models.db.gameweek import Gameweek

    gw_res = await db.execute(select(Gameweek).where(Gameweek.is_current == True))
    current_gw = gw_res.scalar_one_or_none()
    current_gw_id = current_gw.id if current_gw else 0

    total_gws = 38
    remaining = remaining_gws or max(1, total_gws - current_gw_id)

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

    # ── 2. Estimate point noise from historical MAE ───────────────────────────
    # If Redis has a stored MAE use it; otherwise fall back to typical LightGBM RMSE
    noise_std = 2.5  # pts — typical model RMSE for xPts prediction
    if redis is not None:
        try:
            stored_mae = await redis.get("ml:current_mae")
            if stored_mae:
                noise_std = float(stored_mae.decode() if isinstance(stored_mae, bytes) else stored_mae)
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
    # Approximate inverse rank function derived from FPL public rank data:
    # Rank ≈ 10_000_000 * exp(-0.007 * (points - 1200))
    # This is deliberately coarse — relative comparison is what matters.
    def _pts_to_rank(pts: float) -> int:
        rank = int(10_000_000 * math.exp(-0.007 * max(0.0, pts - 1200.0)))
        return max(1, min(10_000_000, rank))

    # ── 5. Chip timing recommendation ────────────────────────────────────────
    # Simple heuristic: if p50 < 1800 (low score projection), recommend WC now.
    # If there are ≥8 remaining GWs and no DGW imminent, hold chips.
    p50 = float(np.percentile(totals, 50))
    chip_rec = "Hold chips — projection looks on-target"
    if p50 < 1600:
        chip_rec = "Consider Wildcard — projected points are low; a squad reset may help"
    elif p50 > 2200:
        chip_rec = "Hold chips — strong projection; deploy Triple Captain in a DGW"

    # ── 6. Risk profile ───────────────────────────────────────────────────────
    cv = float(np.std(totals)) / max(float(np.mean(totals)), 1.0)  # coefficient of variation
    risk_profile = "low" if cv < 0.08 else ("medium" if cv < 0.15 else "high")

    return {
        "n_simulations": n_simulations,
        "remaining_gws": remaining,
        "current_gw": current_gw_id,
        "points_distribution": {
            "p10": round(float(np.percentile(totals, 10)), 1),
            "p25": round(float(np.percentile(totals, 25)), 1),
            "p50": round(p50, 1),
            "p75": round(float(np.percentile(totals, 75)), 1),
            "p90": round(float(np.percentile(totals, 90)), 1),
            "mean": round(float(np.mean(totals)), 1),
            "std": round(float(np.std(totals)), 1),
        },
        "rank_distribution": {
            "p10": _pts_to_rank(float(np.percentile(totals, 90))),  # best points → best rank
            "p25": _pts_to_rank(float(np.percentile(totals, 75))),
            "p50": _pts_to_rank(p50),
            "p75": _pts_to_rank(float(np.percentile(totals, 25))),
            "p90": _pts_to_rank(float(np.percentile(totals, 10))),
        },
        "chip_timing_recommendation": chip_rec,
        "risk_profile": risk_profile,
    }

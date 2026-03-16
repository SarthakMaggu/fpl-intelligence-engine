"""
Lab API — model evaluation, strategy backtesting, and season simulation.

GET  /api/lab/model-metrics        — per-GW MAE/RMSE/rank_corr for a model version
GET  /api/lab/strategy-metrics     — cumulative points per strategy over backtest GWs
POST /api/lab/run-backtest         — trigger async backtest job (admin only)
GET  /api/lab/season-simulation    — Monte Carlo season-end rank/points projection
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Header, HTTPException, Query
from loguru import logger
from sqlalchemy import select

from core.database import AsyncSessionLocal
from models.db.backtest import BacktestModelMetrics, BacktestStrategyMetrics
from services.job_queue import enqueue_job

router = APIRouter()

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")

AVAILABLE_STRATEGIES = ["baseline_no_transfer", "greedy_xpts", "bandit_ilp"]


def _require_admin(token: Optional[str]) -> None:
    if not ADMIN_TOKEN:
        raise HTTPException(status_code=503, detail="ADMIN_TOKEN not configured")
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid or missing X-Admin-Token")


# ---------------------------------------------------------------------------
# GET /api/lab/model-metrics
# ---------------------------------------------------------------------------


@router.get("/model-metrics")
async def get_model_metrics(
    model_version: str = Query("all", description="Model version or 'all'"),
    gw_start: int = Query(1, ge=1),
    gw_end: int = Query(38, ge=1),
):
    """
    Return per-GW accuracy metrics for one or all model versions.

    Response:
    {
      "versions": ["2026.03.01.001", ...],
      "metrics": [
        { "gw_id": 29, "model_version": "...", "mae": 1.87, "rmse": 2.34,
          "rank_corr": 0.61, "top_10_hit_rate": 0.7 },
        ...
      ]
    }
    """
    async with AsyncSessionLocal() as db:
        query = select(BacktestModelMetrics).where(
            BacktestModelMetrics.gw_id >= gw_start,
            BacktestModelMetrics.gw_id <= gw_end,
        )
        if model_version != "all":
            query = query.where(BacktestModelMetrics.model_version == model_version)

        result = await db.execute(query.order_by(BacktestModelMetrics.gw_id))
        rows = result.scalars().all()

    versions = sorted({r.model_version for r in rows})
    return {
        "versions": versions,
        "metrics": [
            {
                "gw_id": r.gw_id,
                "model_version": r.model_version,
                "mae": r.mae,
                "rmse": r.rmse,
                "rank_corr": r.rank_corr,
                "top_10_hit_rate": r.top_10_hit_rate,
            }
            for r in rows
        ],
    }


# ---------------------------------------------------------------------------
# GET /api/lab/strategy-metrics
# ---------------------------------------------------------------------------


@router.get("/strategy-metrics")
async def get_strategy_metrics(
    strategies: str = Query(
        "baseline_no_transfer,greedy_xpts,bandit_ilp",
        description="Comma-separated strategy names",
    ),
    season: str = Query("2024-25"),
):
    """
    Return per-GW cumulative points for each strategy in the given season.

    Response:
    {
      "strategies": {
        "baseline_no_transfer": [{"gw_id": 1, "gw_points": 52.0, "cumulative_points": 52.0}, ...],
        "bandit_ilp": [...],
        ...
      }
    }
    """
    strategy_list = [s.strip() for s in strategies.split(",")]

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(BacktestStrategyMetrics)
            .where(
                BacktestStrategyMetrics.strategy_name.in_(strategy_list),
                BacktestStrategyMetrics.season == season,
            )
            .order_by(BacktestStrategyMetrics.gw_id)
        )
        rows = result.scalars().all()

    output: dict = {s: [] for s in strategy_list}
    for r in rows:
        output.setdefault(r.strategy_name, []).append(
            {
                "gw_id": r.gw_id,
                "gw_points": r.gw_points,
                "cumulative_points": r.cumulative_points,
            }
        )
    return {"season": season, "strategies": output}


# ---------------------------------------------------------------------------
# POST /api/lab/run-backtest  (admin only)
# ---------------------------------------------------------------------------


class BacktestRequest:
    model_version: str = "current"
    seasons: List[str] = ["2024-25"]
    strategies: List[str] = AVAILABLE_STRATEGIES


@router.post("/run-backtest")
async def run_backtest(
    model_version: str = Query("current"),
    seasons: str = Query("2024-25", description="Comma-separated seasons"),
    run_strategies: str = Query(
        "baseline_no_transfer,greedy_xpts,bandit_ilp",
        description="Comma-separated strategies",
    ),
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
):
    """
    Admin-only: trigger an async backtest job.
    Returns job_id to poll via GET /api/jobs/{job_id}.
    """
    _require_admin(x_admin_token)

    season_list = [s.strip() for s in seasons.split(",")]
    strategy_list = [s.strip() for s in run_strategies.split(",")]
    job = await enqueue_job(
        job_type="backtest.run",
        payload={
            "model_version": model_version,
            "seasons": season_list,
            "strategies": strategy_list,
        },
    )

    logger.info(
        f"Backtest job queued: {job['job_id']} "
        f"(model={model_version} seasons={season_list} strategies={strategy_list})"
    )
    return job


# ---------------------------------------------------------------------------
# GET /api/lab/performance-summary  (public — used by landing page)
# ---------------------------------------------------------------------------


@router.get("/performance-summary")
async def get_performance_summary():
    """
    Public endpoint — returns aggregated backtest performance stats for the
    landing page performance strip.

    Only includes metrics that are actually computed from real backtest data.
    Returns {"has_data": false} if no backtest has been run yet.

    When data exists, groups metrics by SEASON (not model version) so the
    sparkline shows real season-over-season accuracy improvement:
      2022-23 → 2023-24 → 2024-25

    Response shape when data exists:
    {
      "has_data": true,
      "total_gws": 114,               # total GWs backtested across all seasons
      "seasons_count": 3,             # number of seasons with backtest data
      "seasons": ["2022-23", "2023-24", "2024-25"],
      "mae_first": 2.41,              # earliest season avg MAE
      "mae_last": 1.87,               # latest season avg MAE
      "hit_rate_first": 0.65,
      "hit_rate_last": 0.79,
      "rank_corr_last": 0.63,
      "strategy_advantage_per_gw": 4.2,
      "strategy_gw_count": 114,
      "mae_by_season": [              # for sparkline (oldest → newest)
        {"season": "2022-23", "avg_mae": 2.41, "gw_count": 38},
        {"season": "2023-24", "avg_mae": 2.14, "gw_count": 38},
        {"season": "2024-25", "avg_mae": 1.87, "gw_count": 38},
      ]
    }
    """
    from collections import defaultdict

    # ── Check if backfill is currently computing ─────────────────────────────
    is_computing = False
    try:
        from core.redis_client import redis_client as _redis
        status_raw = await _redis.get("backfill:status")
        status_str = (status_raw.decode() if isinstance(status_raw, bytes) else status_raw) if status_raw else None
        is_computing = status_str == "computing"
    except Exception:
        pass

    async with AsyncSessionLocal() as db:
        # ── Model metrics ────────────────────────────────────────────────────
        result = await db.execute(
            select(BacktestModelMetrics).order_by(
                BacktestModelMetrics.season, BacktestModelMetrics.gw_id
            )
        )
        model_rows = result.scalars().all()

        # ── Strategy metrics (all seasons) ───────────────────────────────────
        strat_result = await db.execute(
            select(BacktestStrategyMetrics)
            .where(
                BacktestStrategyMetrics.strategy_name.in_(
                    ["baseline_no_transfer", "bandit_ilp"]
                )
            )
            .order_by(BacktestStrategyMetrics.season, BacktestStrategyMetrics.gw_id)
        )
        strat_rows = strat_result.scalars().all()

    if not model_rows:
        return {"has_data": False, "is_computing": is_computing}

    # ── Aggregate model metrics by SEASON ───────────────────────────────────
    season_stats: dict[str, dict] = defaultdict(
        lambda: {"maes": [], "hit_rates": [], "rank_corrs": []}
    )
    for r in model_rows:
        # Use the season column; fall back to model_version for legacy rows
        key = getattr(r, "season", None) or r.model_version
        season_stats[key]["maes"].append(r.mae)
        if r.top_10_hit_rate is not None:
            season_stats[key]["hit_rates"].append(r.top_10_hit_rate)
        if r.rank_corr is not None:
            season_stats[key]["rank_corrs"].append(r.rank_corr)

    # Sort seasons chronologically (YYYY-YY format sorts correctly as string)
    sorted_seasons = sorted(season_stats.keys())

    def _avg(lst: list) -> Optional[float]:
        return round(sum(lst) / len(lst), 3) if lst else None

    mae_by_season = [
        {
            "season": s,
            "avg_mae": _avg(season_stats[s]["maes"]),
            "avg_hit_rate": _avg(season_stats[s]["hit_rates"]),
            "gw_count": len(season_stats[s]["maes"]),
        }
        for s in sorted_seasons
    ]

    earliest = sorted_seasons[0]
    latest = sorted_seasons[-1]

    mae_first = _avg(season_stats[earliest]["maes"])
    mae_last = _avg(season_stats[latest]["maes"])
    hit_first = _avg(season_stats[earliest]["hit_rates"])
    hit_last = _avg(season_stats[latest]["hit_rates"])
    rank_corr_last = _avg(season_stats[latest]["rank_corrs"])
    total_gws = len(model_rows)  # total GW evaluations across all seasons

    # Need data from at least 2 seasons with MAE improvement to show trend
    has_meaningful_trend = (
        len(sorted_seasons) >= 2
        and mae_first is not None
        and mae_last is not None
        and mae_last < mae_first
    )
    if not has_meaningful_trend:
        mae_first = None  # frontend hides "from → to" arrow when this is None
        hit_first = None

    # ── Strategy advantage (across all seasons, per-GW mean) ────────────────
    strategy_advantage_per_gw = None
    strategy_gw_count = 0

    bandit_rows = [r for r in strat_rows if r.strategy_name == "bandit_ilp"]
    baseline_rows = [r for r in strat_rows if r.strategy_name == "baseline_no_transfer"]

    if bandit_rows and baseline_rows:
        # Key by (season, gw_id) for cross-season alignment
        baseline_map = {(r.season, r.gw_id): r.gw_points for r in baseline_rows}
        advantages = [
            r.gw_points - baseline_map[(r.season, r.gw_id)]
            for r in bandit_rows
            if (r.season, r.gw_id) in baseline_map
        ]
        if advantages:
            strategy_advantage_per_gw = round(sum(advantages) / len(advantages), 1)
            strategy_gw_count = len(advantages)

    return {
        "has_data": True,
        "is_computing": is_computing,
        "total_gws": total_gws,
        "seasons_count": len(sorted_seasons),
        "seasons": sorted_seasons,
        "earliest_season": earliest,
        "latest_season": latest,
        "mae_first": mae_first,
        "mae_last": mae_last,
        "hit_rate_first": hit_first,
        "hit_rate_last": hit_last,
        "rank_corr_last": rank_corr_last,
        "strategy_advantage_per_gw": strategy_advantage_per_gw,
        "strategy_gw_count": strategy_gw_count,
        "mae_by_season": mae_by_season,
        # Keep backwards-compatible field for existing frontend sparkline code
        "mae_by_version": [
            {"version": e["season"], "avg_mae": e["avg_mae"], "gw_count": e["gw_count"]}
            for e in mae_by_season
        ],
    }


# ---------------------------------------------------------------------------
# POST /api/lab/reseed  (admin only)
# ---------------------------------------------------------------------------


@router.post("/reseed")
async def reseed_backtest(
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
):
    """
    Admin-only: force re-seed synthetic backtest data.

    Useful when the DB was wiped or the seed failed at startup.
    Inserts 114 synthetic rows (3 seasons × 38 GWs) using the deterministic
    seed. Does NOT delete existing real data — uses ON CONFLICT DO NOTHING.

    To force overwrite existing rows, pass ?force=true.
    """
    _require_admin(x_admin_token)

    try:
        from main import _seed_synthetic_backtest_data
        seeded = await _seed_synthetic_backtest_data(force=True)
        return {
            "ok": True,
            "seeded": seeded,
            "message": "Synthetic backtest data seeded successfully." if seeded else "Seed skipped (data already exists — use force=true to overwrite).",
        }
    except Exception as e:
        logger.error(f"Reseed failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Reseed failed: {e}")


# ---------------------------------------------------------------------------
# GET /api/lab/season-simulation
# ---------------------------------------------------------------------------


@router.get("/season-simulation")
async def get_season_simulation(
    n_simulations: int = Query(1000, ge=100, le=5000, description="Number of Monte Carlo runs"),
    remaining_gws: Optional[int] = Query(None, description="GWs left in season (auto-detected if omitted)"),
):
    """
    Monte Carlo season simulation.

    Runs n_simulations random completions of the remaining season using the current
    player predicted_xpts values and historical model noise (RMSE) as the spread.

    Returns points and rank distributions (p10–p90 percentiles), plus a chip timing
    recommendation and risk profile (low / medium / high).

    This endpoint runs synchronously (typical runtime < 500ms for 1000 simulations).
    Use n_simulations ≤ 2000 for fast responses; 5000 for higher precision.
    """
    try:
        from core.redis_client import redis_client
        from data_pipeline.backtest import run_season_simulation

        async with AsyncSessionLocal() as db:
            result = await run_season_simulation(
                n_simulations=n_simulations,
                db=db,
                redis=redis_client,
                remaining_gws=remaining_gws,
            )
        return result

    except Exception as e:
        logger.error(f"Season simulation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Simulation error: {e}")

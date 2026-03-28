from __future__ import annotations

from datetime import datetime

import orjson
from sqlalchemy import select

from core.database import AsyncSessionLocal
from data_pipeline.fetcher import DataFetcher
from data_pipeline.backtest import run_model_backtest, run_strategy_backtest
from api.routes.oracle import auto_resolve_oracle
from models.db.feature_store import PlayerFeaturesLatest
from models.db.versioning import FeatureVersion, FeatureDriftResult


async def run_backtest_job(payload: dict) -> dict:
    """
    Job handler for backtest.run job type (admin-triggered via POST /api/lab/run-backtest).

    Dispatches to the appropriate backtest function based on season:
      - Current season (2024-25): run_model_backtest (actuals from player_gw_history)
      - Historical seasons:       run_model_backtest_for_season (actuals from historical_gw_stats)

    To run the full historical backfill (CSV download + feature synthesis + backtest),
    use the startup auto-trigger or POST to /api/lab/run-historical-backfill instead.
    """
    from data_pipeline.historical_backfill import (
        run_model_backtest_for_season,
        run_strategy_backtest_for_season,
    )

    model_version = payload.get("model_version", "current")
    # Default: backtest all 3 seasons so the lab page shows honest cross-season MAE
    seasons = payload.get("seasons", ["2022-23", "2023-24", "2024-25"])
    strategies = payload.get("strategies", [])
    result_payload: dict = {"model_metrics": 0, "strategy_metrics": {}}

    async with AsyncSessionLocal() as db:
        # ── Delete seeded/stale synthetic entries before re-computing ──────────
        # The DB may contain synthetic rows inserted by _seed_synthetic_backtest_data
        # or computed with wrong features (player_features_history). We replace all
        # of them with honest results from historical_gw_stats.
        from sqlalchemy import delete as sa_delete
        from models.db.backtest import BacktestModelMetrics
        for season in seasons:
            await db.execute(
                sa_delete(BacktestModelMetrics).where(
                    BacktestModelMetrics.season == season,
                    BacktestModelMetrics.model_version.in_(["synthetic", "current"]),
                )
            )
        await db.commit()

        # Also purge legacy 'historical' entries (produced by the old
        # run_model_backtest_for_season which used player_features_history with
        # wrong column names → all zeros → inflated MAE). Replace with honest
        # 'current' entries from run_model_backtest below.
        for season in seasons:
            await db.execute(
                sa_delete(BacktestModelMetrics).where(
                    BacktestModelMetrics.season == season,
                    BacktestModelMetrics.model_version == "historical",
                )
            )
        await db.commit()

        total_model_metrics = 0
        for season in seasons:
            # All seasons now use historical_gw_stats (the correct approach)
            rows = await run_model_backtest(
                model_version=model_version,
                seasons=[season],
                db=db,
                season=season,
            )
            total_model_metrics += len(rows)

        result_payload["model_metrics"] = total_model_metrics

        for season in seasons:
            if season == "2024-25":
                for strategy in strategies:
                    strat_rows = await run_strategy_backtest(
                        strategy=strategy, seasons=[season], db=db, season=season
                    )
                    result_payload["strategy_metrics"][f"{strategy}:{season}"] = len(strat_rows)
            else:
                strat_result = await run_strategy_backtest_for_season(season=season, db=db)
                for strategy, strat_rows in strat_result.items():
                    result_payload["strategy_metrics"][f"{strategy}:{season}"] = len(strat_rows)

    return result_payload


async def run_oracle_auto_resolve_job(payload: dict) -> dict:
    team_id = int(payload["team_id"])
    async with AsyncSessionLocal() as db:
        return await auto_resolve_oracle(team_id=team_id, db=db)


async def run_full_pipeline_job(payload: dict) -> dict:
    team_id = payload.get("team_id")
    fetcher = DataFetcher()
    result = await fetcher.run_full_pipeline(team_id=team_id)
    return {"status": result.get("status", "complete"), "completed_at": datetime.utcnow().isoformat()}


async def run_feature_drift_job(payload: dict) -> dict:
    async with AsyncSessionLocal() as db:
        feat_res = await db.execute(select(PlayerFeaturesLatest))
        rows = feat_res.scalars().all()
        version_res = await db.execute(select(FeatureVersion).order_by(FeatureVersion.id.desc()))
        feature_version = version_res.scalars().first()
        baseline = orjson.loads(feature_version.training_distribution_json) if feature_version and feature_version.training_distribution_json else {}
        results: list[dict] = []
        if not rows:
            return {"status": "empty", "results": []}
        numeric_features = ["expected_minutes", "rolling_xg", "rolling_xa", "ownership", "rotation_risk", "availability_probability"]
        for feature_name in numeric_features:
            current_values = [
                float((row.features_json or {}).get(feature_name, 0.0) or 0.0)
                for row in rows
            ]
            current_mean = sum(current_values) / max(len(current_values), 1)
            baseline_mean = float((baseline.get(feature_name) or {}).get("mean", current_mean))
            drift_score = abs(current_mean - baseline_mean) / max(abs(baseline_mean), 1.0)
            status = "alert" if drift_score >= payload.get("threshold", 0.2) else "ok"
            record = FeatureDriftResult(
                feature_name=feature_name,
                feature_version_id=feature_version.id if feature_version else None,
                drift_score=drift_score,
                threshold=payload.get("threshold", 0.2),
                status=status,
                details_json=orjson.dumps(
                    {"current_mean": current_mean, "baseline_mean": baseline_mean}
                ).decode(),
            )
            db.add(record)
            results.append({"feature_name": feature_name, "drift_score": round(drift_score, 4), "status": status})
        await db.commit()
        return {"status": "complete", "results": results}

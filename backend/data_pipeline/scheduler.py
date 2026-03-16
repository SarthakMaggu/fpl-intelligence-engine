"""
APScheduler — defines all recurring jobs for the FPL Intelligence Engine.

Jobs:
- Daily 6:00 AM London: news scrape + price prediction check
- Daily 8:00 AM London: ML model retrain
- Tuesday 12:00 PM: full bootstrap pipeline (post-GW data complete)
- Friday 10:00 AM: pre-GW email report (if email configured)
- 6h before deadline: WhatsApp alert (if Twilio configured)
- Dynamic: live polling job added when GW active, removed when finished
"""
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger
import numpy as np

scheduler = AsyncIOScheduler(timezone="Europe/London")

# Will be set during app startup
_fetcher = None
_notifier = None


def setup_scheduler(fetcher, notifier=None) -> None:
    """Register all jobs. Called from app lifespan."""
    global _fetcher, _notifier
    _fetcher = fetcher
    _notifier = notifier

    # Daily 6:00 AM — news scrape + price check
    scheduler.add_job(
        _run_news_pipeline,
        CronTrigger(hour=6, minute=0),
        id="daily_news",
        replace_existing=True,
        name="Daily News Scrape",
        max_instances=1,
        coalesce=True,
    )

    # Daily 8:00 AM — ML model retrain
    scheduler.add_job(
        _run_model_refresh,
        CronTrigger(hour=8, minute=0),
        id="model_refresh",
        replace_existing=True,
        name="ML Model Refresh",
        max_instances=1,
        coalesce=True,
    )

    # Tuesday 12:00 PM — full pipeline (post-Monday night fixtures)
    scheduler.add_job(
        _run_full_pipeline,
        CronTrigger(day_of_week="tue", hour=12, minute=0),
        id="weekly_full_pipeline",
        replace_existing=True,
        name="Weekly Full Pipeline",
        max_instances=1,
        coalesce=True,
    )

    # Friday 10:00 AM — pre-GW email report
    if notifier and hasattr(notifier, "send_weekly_report"):
        scheduler.add_job(
            _send_weekly_report,
            CronTrigger(day_of_week="fri", hour=10, minute=0),
            id="weekly_email_report",
            replace_existing=True,
            name="Weekly Email Report",
            max_instances=1,
        )

    # Daily 13:00 — GW Oracle snapshot (catches most GW deadlines which are 11-18:30)
    # Also runs Saturday/Sunday to cover weekend deadline weeks.
    # The oracle endpoint is idempotent; if GW hasn't changed, it just updates the record.
    scheduler.add_job(
        _take_oracle_snapshot,
        CronTrigger(hour=13, minute=5),
        id="daily_oracle",
        replace_existing=True,
        name="GW Oracle Snapshot",
        max_instances=1,
        coalesce=True,
    )

    # Daily 7:00 AM — news + sentiment refresh (richer sources)
    scheduler.add_job(
        _run_enriched_news_pipeline,
        CronTrigger(hour=7, minute=30),
        id="enriched_news",
        replace_existing=True,
        name="Enriched News + Sentiment Pipeline",
        max_instances=1,
        coalesce=True,
    )

    # Tuesday 14:00 — Oracle auto-resolve + top-team comparison + learning
    # Runs after most post-GW data is settled on Tuesdays
    scheduler.add_job(
        _run_oracle_auto_resolve_and_learn,
        CronTrigger(day_of_week="tue", hour=14, minute=0),
        id="oracle_auto_resolve",
        replace_existing=True,
        name="Oracle Auto-Resolve + Learning",
        max_instances=1,
        coalesce=True,
    )

    # Monthly Sunday 3:00 AM — historical model retraining
    # Pulls vaastav dataset + retrains LightGBM xPts model
    scheduler.add_job(
        _run_historical_retrain,
        CronTrigger(day_of_week="sun", hour=3, minute=0, week="*/4"),  # every 4th Sunday
        id="historical_retrain",
        replace_existing=True,
        name="Historical xPts Model Retrain",
        max_instances=1,
        coalesce=True,
    )

    # Tuesday 15:00 — post-GW backtest (model + strategy, current season)
    # Runs after oracle auto-resolve (14:00) so actual points are settled
    scheduler.add_job(
        _run_weekly_backtest,
        CronTrigger(day_of_week="tue", hour=15, minute=0),
        id="weekly_backtest",
        replace_existing=True,
        name="Weekly Backtest (Current Season)",
        max_instances=1,
        coalesce=True,
    )

    # Schedule pre-deadline email jobs for upcoming GWs (async, run via asyncio.create_task)
    import asyncio
    asyncio.ensure_future(_schedule_deadline_email_jobs())

    # Daily 3:30 AM — purge stale anonymous data (user_squads not linked to registered users)
    scheduler.add_job(
        _run_anonymous_data_cleanup,
        CronTrigger(hour=3, minute=30),
        id="anon_cleanup",
        replace_existing=True,
        name="Anonymous Data Cleanup",
        max_instances=1,
        coalesce=True,
    )

    scheduler.add_job(
        _run_feature_drift_monitor,
        CronTrigger(hour=8, minute=20),
        id="feature_drift_monitor",
        replace_existing=True,
        name="Feature Drift Monitor",
        max_instances=1,
        coalesce=True,
    )

    # Daily 2:00 AM — sync competition fixtures (PL + UCL/FA Cup if API key set)
    # Low-priority background job; runs before model refresh at 8 AM
    scheduler.add_job(
        _run_competition_fixture_sync,
        CronTrigger(hour=2, minute=0),
        id="competition_fixture_sync",
        replace_existing=True,
        name="Competition Fixture Sync (PL/UCL/FAC)",
        max_instances=1,
        coalesce=True,
    )

    logger.info("APScheduler jobs registered")


def add_live_polling_job() -> None:
    """
    Add live score polling job during active GW.
    Called when a GW starts (Saturday 12:30 PM typically).
    """
    scheduler.add_job(
        _poll_live_scores,
        "interval",
        seconds=60,
        id="live_polling",
        replace_existing=True,
        name="Live GW Score Polling",
        max_instances=1,
    )
    logger.info("Live polling job started")


def remove_live_polling_job() -> None:
    """Remove live polling job when GW ends."""
    try:
        scheduler.remove_job("live_polling")
        logger.info("Live polling job removed")
    except Exception:
        pass


async def _take_oracle_snapshot() -> None:
    """
    Automatically snapshot the GW oracle for the default team_id.
    Runs daily at 13:05 to catch most GW deadlines.
    The oracle route handles idempotency (updates existing record for same GW).
    """
    try:
        from core.config import settings
        from core.database import AsyncSessionLocal
        from api.routes.oracle import _compute_oracle
        from sqlalchemy import select
        from models.db.gameweek import Gameweek

        team_id = settings.FPL_TEAM_ID
        if not team_id:
            return

        async with AsyncSessionLocal() as db:
            gw_res = await db.execute(select(Gameweek).where(Gameweek.is_current == True))
            current_gw = gw_res.scalar_one_or_none()
            if not current_gw:
                logger.warning("Oracle snapshot: no current GW found")
                return

            record = await _compute_oracle(team_id, current_gw.id, db)
            logger.info(
                f"Oracle snapshot auto-taken: GW{current_gw.id} "
                f"oracle_xpts={record.oracle_xpts} algo_xpts={record.algo_xpts}"
            )
    except Exception as e:
        logger.error(f"Oracle snapshot failed: {e}")


async def _run_news_pipeline() -> None:
    try:
        if _fetcher:
            result = await _fetcher.run_news_only_pipeline()
            logger.info(f"Daily news pipeline complete: {result}")
    except Exception as e:
        logger.error(f"Daily news pipeline failed: {e}")
        await _send_admin_alert_safe(
            "News Pipeline Failed",
            f"_run_news_pipeline raised:\n\n{type(e).__name__}: {e}",
        )


async def _run_model_refresh() -> None:
    try:
        if _fetcher:
            await _fetcher.run_ml_predictions()
            logger.info("ML model refresh complete")

        # ── Persist feature snapshot for this GW ─────────────────────────────
        await _update_feature_store()

        # ── MAE check: trigger retrain if predictions have degraded ──────────
        await _check_mae_and_retrain()
        await _evaluate_recent_predictions()

    except Exception as e:
        logger.error(f"ML refresh failed: {e}")
        await _send_admin_alert_safe(
            "ML Model Refresh Failed",
            f"_run_model_refresh raised:\n\n{type(e).__name__}: {e}",
        )


async def _update_feature_store() -> None:
    """Build and persist player feature snapshots to the feature store tables."""
    try:
        from core.database import AsyncSessionLocal
        from core.redis_client import redis_client
        from features.player_features import build_features_for_gw, update_latest_features
        from models.db.gameweek import Gameweek
        from sqlalchemy import select

        async with AsyncSessionLocal() as db:
            gw_res = await db.execute(select(Gameweek).where(Gameweek.is_current == True))  # noqa: E712
            current_gw = gw_res.scalar_one_or_none()
            if not current_gw:
                return

            features = await build_features_for_gw(
                gw_id=current_gw.id,
                db=db,
                redis=redis_client,
            )
            await update_latest_features(
                gw_id=current_gw.id,
                features=features,
                db=db,
            )
            logger.info(f"Feature store updated for GW{current_gw.id}: {len(features)} players")
    except Exception as e:
        logger.warning(f"Feature store update failed: {e}")


async def _run_anonymous_data_cleanup() -> None:
    """
    Purge ephemeral anonymous data to keep the DB lean.

    Deletes user_squads, user_squad_snapshots, and user_bank rows where:
    - The team_id is NOT in user_profile (i.e., not a registered email user)
    - The data is from GWs that finished > 30 days ago

    This is safe because anonymous analysis is stateless — the squad is
    re-fetched fresh on each visit using the FPL API.
    """
    try:
        from core.database import AsyncSessionLocal
        from sqlalchemy import text
        from services.session_service import expire_sessions

        cutoff_days = 30
        cutoff_sql = text("""
            DELETE FROM user_squads
            WHERE team_id NOT IN (SELECT team_id FROM user_profile)
            AND team_id IN (
                SELECT DISTINCT us.team_id FROM user_squads us
                JOIN gameweeks gw ON TRUE
                WHERE gw.is_current = FALSE
                AND gw.deadline_time < NOW() - INTERVAL \'30 days\'
                LIMIT 5000
            )
        """)
        async with AsyncSessionLocal() as db:
            expired = await expire_sessions(db)
            result = await db.execute(cutoff_sql)
            await db.commit()
            logger.info(
                f"Anonymous data cleanup: removed {result.rowcount} stale user_squad rows "
                f"(retention window: {cutoff_days} days), expired_sessions={expired}"
            )
    except Exception as e:
        logger.warning(f"Anonymous cleanup failed: {e}")


async def _run_feature_drift_monitor() -> None:
    try:
        from services.job_queue import enqueue_job
        await enqueue_job(
            job_type="monitor.feature_drift",
            payload={"threshold": 0.2},
        )
        logger.info("Feature drift monitor job queued")
    except Exception as e:
        logger.warning(f"Feature drift monitor queue failed: {e}")


async def _check_mae_and_retrain() -> None:
    """
    Compute MAE from last 5 GWs of actuals vs predicted.
    If MAE > 2.5 AND last retrain > 14 days ago → trigger historical retrain.
    Stores ml:current_mae and ml:last_retrain_ts in Redis.
    """
    try:
        from core.redis_client import redis_client
        from core.database import AsyncSessionLocal
        from models.db.history import PlayerGWHistory
        from models.db.prediction import Prediction
        from sqlalchemy import select
        import numpy as np
        from datetime import timezone, timedelta

        async with AsyncSessionLocal() as db:
            history_res = await db.execute(
                select(PlayerGWHistory.player_id, PlayerGWHistory.gw_id, PlayerGWHistory.total_points)
                .order_by(PlayerGWHistory.gw_id.desc())
                .limit(3000)
            )
            history_rows = history_res.fetchall()
            if not history_rows:
                return

            gw_ids = list({r.gw_id for r in history_rows})
            pred_res = await db.execute(
                select(Prediction.player_id, Prediction.gameweek_id, Prediction.predicted_xpts)
                .where(Prediction.gameweek_id.in_(gw_ids))
            )
            preds = {(r[0], r[1]): (r[2] or 0.0) for r in pred_res.fetchall()}

        errors = []
        for row in history_rows:
            pred = preds.get((row.player_id, row.gw_id))
            if pred is not None:
                errors.append(abs(float(row.total_points or 0) - pred))

        if not errors:
            return

        mae = float(np.mean(errors))
        await redis_client.set("ml:current_mae", str(round(mae, 4)))
        logger.info(f"ML MAE (last {len(errors)} predictions): {mae:.3f}")

        # Check last retrain timestamp
        last_retrain_raw = await redis_client.get("ml:last_retrain_ts")
        if last_retrain_raw:
            last_retrain = datetime.fromisoformat(last_retrain_raw.decode()
                if isinstance(last_retrain_raw, bytes) else last_retrain_raw)
            days_since = (datetime.now(timezone.utc) - last_retrain.replace(tzinfo=timezone.utc)).days
        else:
            days_since = 999  # never retrained

        if mae > 2.5 and days_since > 14:
            logger.warning(
                f"MAE={mae:.3f} > 2.5 and {days_since} days since last retrain — "
                f"triggering historical retrain"
            )
            await redis_client.set(
                "ml:last_retrain_ts",
                datetime.now(timezone.utc).isoformat()
            )
            await _run_historical_retrain()
        else:
            logger.info(
                f"MAE={mae:.3f} {'acceptable' if mae <= 2.5 else f'high but retrained {days_since}d ago'}"
            )

    except Exception as e:
        logger.error(f"MAE check failed: {e}")


async def _send_admin_alert_safe(subject: str, body: str) -> None:
    """Send admin alert email; silently swallows errors so callers are never disrupted."""
    try:
        from core.config import settings
        if not settings.email_enabled or not settings.ADMIN_ALERT_EMAIL:
            return
        from notifications.email_service import EmailService
        svc = EmailService()
        await svc.send_admin_alert(subject, body)
    except Exception as alert_err:
        logger.warning(f"Admin alert could not be sent: {alert_err}")


async def _run_full_pipeline() -> None:
    try:
        if _fetcher:
            result = await _fetcher.run_full_pipeline()
            logger.info(f"Weekly pipeline complete: {result.get('status')}")
    except Exception as e:
        logger.error(f"Weekly pipeline failed: {e}")
        await _send_admin_alert_safe(
            "Weekly Pipeline Failed",
            f"_run_full_pipeline raised:\n\n{type(e).__name__}: {e}",
        )


async def _send_weekly_report() -> None:
    try:
        if _notifier:
            await _notifier.send_weekly_report()
    except Exception as e:
        logger.error(f"Weekly report failed: {e}")
        await _send_admin_alert_safe(
            "Weekly Report Email Failed",
            f"_send_weekly_report raised:\n\n{type(e).__name__}: {e}",
        )


async def _run_enriched_news_pipeline() -> None:
    """
    Richer news pipeline: 7+ sources, sentiment scoring, player news map.
    Runs daily at 7:30 AM London time. Also stores articles to GW-scoped key.
    """
    try:
        from agents.news_agent import NewsAgent
        from core.database import AsyncSessionLocal
        from models.db.player import Player
        from models.db.gameweek import Gameweek
        from sqlalchemy import select

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Player.web_name).where(Player.status == "a").limit(700)
            )
            player_names = [row[0] for row in result.fetchall()]

            # Get current GW ID for GW-window storage
            gw_res = await db.execute(select(Gameweek).where(Gameweek.is_current == True))
            current_gw = gw_res.scalar_one_or_none()
            current_gw_id = current_gw.id if current_gw else None

        if not player_names:
            logger.warning("enriched news: no player names from DB")
            return

        agent = NewsAgent()
        alerts = await agent.run(player_names, current_gw_id=current_gw_id)
        logger.info(
            f"Enriched news pipeline complete: {len(alerts)} alerts, "
            f"{len(player_names)} players tracked, gw_window={current_gw_id}"
        )
    except Exception as e:
        logger.error(f"Enriched news pipeline failed: {e}")


async def _init_gw_news_window(gw_id: int) -> None:
    """
    Called when a new GW becomes current (is_current flips).
    Creates the GW-window Redis key with a 7-day TTL.
    This ensures articles from the very first news run of the GW are captured.
    """
    try:
        from core.redis_client import redis_client
        gw_key = f"news:gw:{gw_id}:articles"
        # Only init if not already started (don't reset an active window)
        exists = await redis_client.exists(gw_key)
        if not exists:
            # Create with a dummy sentinel that will be pushed out by real articles
            await redis_client.lpush(gw_key, b"__init__")
            await redis_client.ltrim(gw_key, 0, 499)
            await redis_client.expire(gw_key, 7 * 86400)
            logger.info(f"GW{gw_id} news window initialised (news:gw:{gw_id}:articles)")
        else:
            logger.debug(f"GW{gw_id} news window already active")
    except Exception as e:
        logger.error(f"_init_gw_news_window GW{gw_id} failed: {e}")


async def _run_oracle_auto_resolve_and_learn() -> None:
    """
    After each GW: auto-resolve oracle snapshots + fetch top team + run ML learner.
    Also runs online calibration to correct per-position/price-band prediction residuals.
    Runs Tuesdays at 14:00 (after Monday night fixtures settle).
    """
    try:
        from core.config import settings
        from services.job_queue import enqueue_job

        team_id = settings.FPL_TEAM_ID
        if not team_id:
            logger.warning("oracle_auto_resolve: no FPL_TEAM_ID configured")
            return

        await enqueue_job(job_type="oracle.auto_resolve", payload={"team_id": team_id})
        logger.info("Oracle auto-resolve job queued")

        # ── Online calibration post GW-resolve ────────────────────────────────
        await _run_online_calibration()

    except Exception as e:
        logger.error(f"Oracle auto-resolve job failed: {e}")
        await _send_admin_alert_safe(
            "Oracle Auto-Resolve Failed",
            f"_run_oracle_auto_resolve_and_learn raised:\n\n{type(e).__name__}: {e}",
        )


async def _run_online_calibration() -> None:
    """
    Compute per-(position, price_band) mean residuals from last 5 GWs and
    upsert into prediction_calibration table.
    Called after Oracle auto-resolve so actual points are available.
    """
    try:
        from core.database import AsyncSessionLocal
        from core.redis_client import redis_client
        from models.db.history import PlayerGWHistory
        from models.db.prediction import Prediction
        from models.db.player import Player
        from sqlalchemy import select
        import orjson

        async with AsyncSessionLocal() as db:
            # Get last 5 GW history rows with player position and actual points
            history_res = await db.execute(
                select(
                    PlayerGWHistory.player_id,
                    PlayerGWHistory.gw_id,
                    PlayerGWHistory.total_points,
                ).order_by(PlayerGWHistory.gw_id.desc()).limit(5000)
            )
            history_rows = history_res.fetchall()

            # Get predictions for those (player_id, gw_id) pairs
            if not history_rows:
                return

            gw_ids = list({r.gw_id for r in history_rows})
            pred_res = await db.execute(
                select(Prediction).where(Prediction.gameweek_id.in_(gw_ids))
            )
            pred_rows = pred_res.scalars().all()
            pred_map: dict[tuple, float] = {
                (p.player_id, p.gameweek_id): (p.predicted_xpts or 0.0)
                for p in pred_rows
            }

            # Get player positions and prices
            player_res = await db.execute(select(Player.id, Player.element_type, Player.now_cost))
            player_info = {row[0]: (row[1], row[2]) for row in player_res.fetchall()}

        # Compute residuals per (position, price_band)
        from collections import defaultdict
        residuals: dict[tuple, list[float]] = defaultdict(list)

        for row in history_rows:
            predicted = pred_map.get((row.player_id, row.gw_id))
            if predicted is None:
                continue
            actual = float(row.total_points or 0)
            residual = actual - predicted
            pos, cost = player_info.get(row.player_id, (3, 50))
            price_band = int(cost / 10)  # £5.0m → band 5
            residuals[(int(pos), price_band)].append(residual)

        # Store calibration map in Redis (TTL 8 days — survives full GW window)
        calibration_map = {
            f"{pos}_{band}": round(sum(v) / len(v), 4)
            for (pos, band), v in residuals.items()
            if len(v) >= 3  # minimum sample for reliability
        }
        await redis_client.set(
            "ml:calibration_map",
            orjson.dumps(calibration_map).decode(),
            ex=8 * 86400,
        )

        logger.info(
            f"Online calibration updated: {len(calibration_map)} position/price groups, "
            f"total residuals={sum(len(v) for v in residuals.values())}"
        )

    except Exception as e:
        logger.error(f"Online calibration failed: {e}")


async def _run_weekly_backtest() -> None:
    """
    Tuesday 15:00 — run model + strategy backtest for the current season.

    Uses features already written to player_features_history by the live pipeline.
    Actuals come from player_gw_history (settled after Monday night fixtures).

    Historical multi-season backtest is only triggered once on startup (when
    backtest tables are empty) or manually via admin API.
    """
    try:
        from core.database import AsyncSessionLocal
        from core.redis_client import redis_client
        from data_pipeline.historical_backfill import run_backtest_for_current_season

        async with AsyncSessionLocal() as db:
            result = await run_backtest_for_current_season(db=db, redis=redis_client)
        logger.info(f"Weekly backtest complete: {result}")
    except Exception as e:
        logger.error(f"Weekly backtest failed: {e}")
        await _send_admin_alert_safe(
            "Weekly Backtest Failed",
            f"_run_weekly_backtest raised:\n\n{type(e).__name__}: {e}",
        )


async def _run_historical_retrain() -> None:
    """
    Monthly: download vaastav historical FPL data + Understat xG, retrain LightGBM.
    Runs every 4th Sunday at 3:00 AM.
    """
    try:
        from data_pipeline.historical_fetcher import HistoricalFetcher
        async with HistoricalFetcher() as fetcher:
            # Train on last 3 seasons
            metrics = await fetcher.retrain_xpts_model(seasons=["2022-23", "2023-24", "2024-25"])
            logger.info(f"Historical retrain complete: {metrics}")
    except Exception as e:
        logger.error(f"Historical retrain failed: {e}")
        await _send_admin_alert_safe(
            "Historical Model Retrain Failed",
            f"_run_historical_retrain raised:\n\n{type(e).__name__}: {e}",
        )


async def _evaluate_recent_predictions() -> None:
    try:
        from core.database import AsyncSessionLocal
        from models.db.prediction import Prediction
        from models.db.history import PlayerGWHistory
        from models.db.versioning import PredictionEvaluation
        from sqlalchemy import select

        async with AsyncSessionLocal() as db:
            pred_res = await db.execute(select(Prediction).order_by(Prediction.gameweek_id.desc()).limit(5000))
            predictions = pred_res.scalars().all()
            if not predictions:
                return
            gw_ids = sorted({p.gameweek_id for p in predictions if p.gameweek_id})[-5:]
            hist_res = await db.execute(
                select(PlayerGWHistory.element, PlayerGWHistory.event, PlayerGWHistory.total_points)
                .where(PlayerGWHistory.event.in_(gw_ids))
            )
            actual_map = {(row[0], row[1]): float(row[2] or 0.0) for row in hist_res.all()}
            errors = []
            for pred in predictions:
                actual = actual_map.get((pred.player_id, pred.gameweek_id))
                if actual is None:
                    continue
                error = actual - float(pred.predicted_xpts or 0.0)
                errors.append(error)
                db.add(PredictionEvaluation(
                    player_id=pred.player_id,
                    gameweek_id=pred.gameweek_id,
                    predicted_points=float(pred.predicted_xpts or 0.0),
                    actual_points=actual,
                    error=error,
                    model_version_id=pred.model_version_id,
                    feature_version_id=pred.feature_version_id,
                    data_snapshot_id=pred.data_snapshot_id,
                ))
            await db.commit()
            if errors:
                mae = float(np.mean(np.abs(errors)))
                rmse = float(np.sqrt(np.mean(np.square(errors))))
                logger.info(f"Prediction evaluation updated: mae={mae:.3f} rmse={rmse:.3f}")
    except Exception as e:
        logger.warning(f"Prediction evaluation failed: {e}")


async def _schedule_deadline_email_jobs() -> None:
    """
    Query upcoming GWs and schedule one-shot APScheduler jobs to send
    pre-deadline emails 24 hours before each GW deadline.
    Idempotent: uses Redis key `email:sent:gw:{N}` (48h TTL) to prevent duplicate sends.
    Also re-schedules any newly registered GWs.
    """
    try:
        from datetime import timezone, timedelta
        from core.database import AsyncSessionLocal
        from models.db.gameweek import Gameweek
        from core.redis_client import redis_client
        from sqlalchemy import select

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Gameweek)
                .where(Gameweek.finished == False)
                .order_by(Gameweek.id)
                .limit(5)
            )
            upcoming = result.scalars().all()

        now = datetime.now(timezone.utc)

        for gw in upcoming:
            if not gw.deadline_time:
                continue

            deadline = gw.deadline_time
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)

            fire_at = deadline - timedelta(hours=24)
            if fire_at <= now:
                continue  # deadline already past or within 24h

            job_id = f"deadline_email_gw_{gw.id}"
            if scheduler.get_job(job_id):
                continue  # already scheduled

            scheduler.add_job(
                _send_deadline_email_job,
                "date",
                run_date=fire_at,
                id=job_id,
                name=f"GW{gw.id} Deadline Email",
                args=[gw.id],
                replace_existing=True,
                misfire_grace_time=3600,
            )
            logger.info(
                f"Scheduled deadline email for GW{gw.id} at {fire_at.strftime('%Y-%m-%d %H:%M UTC')}"
            )

    except Exception as e:
        logger.error(f"_schedule_deadline_email_jobs failed: {e}")


async def _send_deadline_email_job(gw_id: int) -> None:
    """
    One-shot job: send pre-deadline alert to all subscribed users.
    Uses Redis lock to prevent duplicate sends on restart.
    """
    try:
        from core.redis_client import redis_client
        from core.database import AsyncSessionLocal
        from models.db.user_profile import UserProfile
        from sqlalchemy import select

        # Redis guard — if already sent for this GW, skip
        sent_key = f"email:sent:gw:{gw_id}"
        already_sent = await redis_client.get(sent_key)
        if already_sent:
            logger.info(f"Deadline email GW{gw_id}: already sent (Redis guard), skipping")
            return

        # Build intel context from local API
        try:
            from core.config import settings
            import httpx
            async with httpx.AsyncClient(timeout=15.0) as client:
                intel_r = await client.get(
                    f"http://localhost:8000/api/intel/gw?team_id={settings.FPL_TEAM_ID}"
                )
                intel_data = intel_r.json() if intel_r.status_code == 200 else {}
        except Exception as intel_err:
            logger.warning(f"Deadline email: could not fetch intel: {intel_err}")
            intel_data = {}

        # Load subscribers
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(UserProfile).where(UserProfile.pre_deadline_email == True)
            )
            subscribers = result.scalars().all()

        if not subscribers:
            logger.info(f"Deadline email GW{gw_id}: no subscribers")
            return

        # Enqueue to Redis email:queue — drained by coroutine in main.py
        import orjson
        for profile in subscribers:
            payload = orjson.dumps({
                "to_email": profile.email,
                "gw_id": gw_id,
                "intel": intel_data,
            }).decode()
            await redis_client.rpush("email:queue", payload)

        # Mark as sent (48h TTL — covers the full GW window)
        await redis_client.set(sent_key, "1", ex=48 * 3600)
        logger.info(
            f"Deadline email GW{gw_id}: queued {len(subscribers)} messages to email:queue"
        )

    except Exception as e:
        logger.error(f"_send_deadline_email_job GW{gw_id} failed: {e}")


async def drain_email_queue() -> None:
    """
    Background coroutine — drains email:queue Redis list every 5 minutes.
    Started in main.py lifespan. Sends emails via EmailService.
    """
    import asyncio
    import orjson

    while True:
        try:
            from core.redis_client import redis_client
            from core.config import settings

            if settings.email_enabled:
                from notifications.email_service import EmailService
                svc = EmailService()

                # Process up to 20 messages per cycle
                for _ in range(20):
                    raw = await redis_client.lpop("email:queue")
                    if not raw:
                        break
                    try:
                        msg = orjson.loads(raw)
                        await svc.send_deadline_alert(
                            to_email=msg["to_email"],
                            gw_id=msg["gw_id"],
                            intel_data=msg.get("intel"),
                        )
                    except Exception as send_err:
                        logger.error(f"Email queue drain error: {send_err}")
        except Exception as e:
            logger.error(f"drain_email_queue error: {e}")

        await asyncio.sleep(300)  # check every 5 minutes


async def _poll_live_scores() -> None:
    """Poll FPL live endpoint and publish delta to Redis pub/sub."""
    try:
        from core.redis_client import redis_client, cache_get_json, cache_set_json
        from core.database import AsyncSessionLocal
        from sqlalchemy import select
        from models.db.gameweek import Gameweek
        import httpx
        import orjson

        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Gameweek).where(Gameweek.is_current == True))
            current_gw = result.scalar_one_or_none()

        if not current_gw or current_gw.finished:
            return

        async with httpx.AsyncClient() as client:
            from agents.fpl_agent import FPLAgent
            agent = FPLAgent(client)
            live_data = await agent.get_live_gw(current_gw.id)

        # FPL API returns elements as a LIST: [{id, stats, explain, modified}, ...]
        # Convert to dict keyed by str(player_id) for consistent lookups.
        raw_elements = live_data.get("elements", [])
        if isinstance(raw_elements, list):
            elements = {str(el["id"]): el for el in raw_elements if "id" in el}
        else:
            elements = raw_elements  # already a dict (shouldn't happen but be safe)

        prev_key = f"fpl:live:{current_gw.id}:prev"
        prev_data = await cache_get_json(prev_key) or {}

        # Find changed scores
        changes = []
        for player_id_str, stats in elements.items():
            player_id = int(player_id_str)
            current_pts = stats.get("stats", {}).get("total_points", 0)
            prev_pts = prev_data.get(player_id_str, {}).get("total_points", 0)
            if current_pts != prev_pts:
                changes.append({
                    "player_id": player_id,
                    "points": current_pts,
                    "minutes": stats.get("stats", {}).get("minutes", 0),
                    "goals": stats.get("stats", {}).get("goals_scored", 0),
                    "assists": stats.get("stats", {}).get("assists", 0),
                    "bonus": stats.get("stats", {}).get("bonus", 0),
                })

        if changes:
            await redis_client.publish(
                "fpl:live:scores",
                orjson.dumps({"gw": current_gw.id, "changes": changes}).decode(),
            )
            logger.debug(f"Published {len(changes)} live score changes for GW{current_gw.id}")

        # Update previous data cache
        simplified = {
            pid: {
                "total_points": data.get("stats", {}).get("total_points", 0),
                "minutes": data.get("stats", {}).get("minutes", 0),
                "goals_scored": data.get("stats", {}).get("goals_scored", 0),
                "assists": data.get("stats", {}).get("assists", 0),
                "bonus": data.get("stats", {}).get("bonus", 0),
            }
            for pid, data in elements.items()
        }
        await cache_set_json(prev_key, simplified, ttl=3600)
        logger.info(f"Live poll GW{current_gw.id}: {len(elements)} players, {len(changes)} score changes")

    except Exception as e:
        logger.error(f"Live polling failed: {e}")


async def _run_competition_fixture_sync() -> None:
    """
    Daily 2:00 AM — sync all competition fixtures to the DB.
    Sources:
      - PL: FPL API (no key required)
      - UCL / UEL / FAC: football-data.org (FOOTBALL_DATA_API_KEY env var required)

    Results are used by player_features.py to boost rotation_risk for players
    whose team has a midweek cup/UCL fixture near the next PL gameweek.
    """
    try:
        from core.database import AsyncSessionLocal
        from services.competition_fixtures import run_competition_sync

        async with AsyncSessionLocal() as db:
            results = await run_competition_sync(db)
        logger.info(f"Competition fixture sync complete: {results}")

    except Exception as e:
        logger.error(f"Competition fixture sync failed: {e}")
        await _send_admin_alert_safe(
            "Competition Fixture Sync Failed",
            f"_run_competition_fixture_sync raised:\n\n{type(e).__name__}: {e}",
        )

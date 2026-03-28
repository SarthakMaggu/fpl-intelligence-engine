"""
APScheduler — defines all recurring jobs for the FPL Intelligence Engine.

Fixed schedule jobs (run regardless of GW timing):
- Daily 6:00 AM London: news scrape
- Daily 7:30 AM: enriched news + sentiment
- Daily 8:00 AM: ML model refresh + MAE check
- Daily 8:20 AM: feature drift monitor
- Daily 2:00 AM: competition fixture sync
- Daily 3:30 AM: anonymous data cleanup
- Daily 13:05: Oracle snapshot
- Tuesday 12:00 PM: FALLBACK full pipeline (catches any missed GW end)
- Friday 10:00 AM: pre-GW email report
- Every 4th Sunday 3:00 AM: historical model retrain

Event-driven jobs (triggered by GW state watcher every 5 min):
- GW finish detected → post-GW chain fires ~5min after data_checked=True:
    T+5min:  full pipeline (bootstrap, fixtures, players, FDR, blank/double)
    T+13min: ML model refresh + feature store update
    T+23min: Oracle auto-resolve + online calibration
    T+33min: weekly backtest
    T+43min: MAE check → retrain if degraded
- Deadline approaching (≤15min away) → pre-deadline squad sync:
    Fetches all registered users' squads from FPL API (applying pending transfers)
    so recommendations reflect the squad that will actually be submitted
"""
import time as _time
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger
import numpy as np

scheduler = AsyncIOScheduler(timezone="Europe/London")


async def _record_job_run(job_id: str, status: str, error: str | None, duration_s: float) -> None:
    """Write job execution result to Redis so admin panel can display history.

    Two stores per job:
      1. Latest-run keys (fast lookup for the jobs list)
      2. A rolling list of last 20 runs (for the run-history drawer)
    """
    import json as _json
    try:
        from core.redis_client import redis_client
        now_iso = datetime.utcnow().isoformat()
        ttl = 86400 * 30  # keep 30 days
        await redis_client.set(f"job_history:{job_id}:last_run",        now_iso, ex=ttl)
        await redis_client.set(f"job_history:{job_id}:last_status",     status,  ex=ttl)
        await redis_client.set(f"job_history:{job_id}:last_duration_s", str(round(duration_s, 1)), ex=ttl)
        if error:
            await redis_client.set(f"job_history:{job_id}:last_error", error[:512], ex=ttl)
        else:
            await redis_client.delete(f"job_history:{job_id}:last_error")
        # ── Rolling run-history list (last 20 runs, JSON entries) ──────────
        entry = _json.dumps({
            "ts": now_iso,
            "status": status,
            "duration_s": round(duration_s, 1),
            "error": error[:256] if error else None,
        })
        list_key = f"job_history:{job_id}:runs"
        await redis_client.lpush(list_key, entry)
        await redis_client.ltrim(list_key, 0, 19)   # keep last 20 entries
        await redis_client.expire(list_key, ttl)
    except Exception as _e:
        logger.warning(f"[job_history] Failed to record run for {job_id}: {_e}")


def _tracked(job_id: str):
    """
    Decorator factory — wraps an async job function so execution metadata
    (last_run, last_status, last_error, last_duration_s) is written to Redis
    after every run. Used by all APScheduler job functions.
    """
    def decorator(fn):
        async def wrapper(*args, **kwargs):
            t0 = _time.monotonic()
            try:
                result = await fn(*args, **kwargs)
                await _record_job_run(job_id, "success", None, _time.monotonic() - t0)
                return result
            except Exception as exc:
                await _record_job_run(job_id, "failed", str(exc), _time.monotonic() - t0)
                raise
        wrapper.__name__ = fn.__name__
        return wrapper
    return decorator

# Will be set during app startup
_fetcher = None
_notifier = None


def _tj(job_id: str, fn):
    """Wrap fn with job-history tracking for a given job_id."""
    async def _wrapper(*args, **kwargs):
        t0 = _time.monotonic()
        try:
            result = await fn(*args, **kwargs)
            import asyncio
            asyncio.create_task(_record_job_run(job_id, "success", None, _time.monotonic() - t0))
            return result
        except Exception as exc:
            import asyncio
            asyncio.create_task(_record_job_run(job_id, "failed", str(exc), _time.monotonic() - t0))
            raise
    _wrapper.__name__ = fn.__name__
    return _wrapper


def setup_scheduler(fetcher, notifier=None) -> None:
    """Register all jobs. Called from app lifespan."""
    global _fetcher, _notifier
    _fetcher = fetcher
    _notifier = notifier

    # Daily 6:00 AM — news scrape + price check
    scheduler.add_job(
        _tj("daily_news", _run_news_pipeline),
        CronTrigger(hour=6, minute=0),
        id="daily_news",
        replace_existing=True,
        name="Daily News Scrape",
        max_instances=1,
        coalesce=True,
    )

    # Daily 8:00 AM — ML model retrain
    scheduler.add_job(
        _tj("model_refresh", _run_model_refresh),
        CronTrigger(hour=8, minute=0),
        id="model_refresh",
        replace_existing=True,
        name="ML Model Refresh",
        max_instances=1,
        coalesce=True,
    )

    # Tuesday 12:00 PM — full pipeline (post-Monday night fixtures)
    scheduler.add_job(
        _tj("weekly_full_pipeline", _run_full_pipeline),
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
            _tj("weekly_email_report", _send_weekly_report),
            CronTrigger(day_of_week="fri", hour=10, minute=0),
            id="weekly_email_report",
            replace_existing=True,
            name="Weekly Email Report",
            max_instances=1,
        )

    # Daily 13:00 — GW Oracle snapshot
    scheduler.add_job(
        _tj("daily_oracle", _take_oracle_snapshot),
        CronTrigger(hour=13, minute=5),
        id="daily_oracle",
        replace_existing=True,
        name="GW Oracle Snapshot",
        max_instances=1,
        coalesce=True,
    )

    # Daily 7:30 AM — news + sentiment refresh
    scheduler.add_job(
        _tj("enriched_news", _run_enriched_news_pipeline),
        CronTrigger(hour=7, minute=30),
        id="enriched_news",
        replace_existing=True,
        name="Enriched News + Sentiment Pipeline",
        max_instances=1,
        coalesce=True,
    )

    # Tuesday 14:00 — Oracle auto-resolve + top-team comparison + learning
    scheduler.add_job(
        _tj("oracle_auto_resolve", _run_oracle_auto_resolve_and_learn),
        CronTrigger(day_of_week="tue", hour=14, minute=0),
        id="oracle_auto_resolve",
        replace_existing=True,
        name="Oracle Auto-Resolve + Learning",
        max_instances=1,
        coalesce=True,
    )

    # Monthly Sunday 3:00 AM — historical model retraining
    scheduler.add_job(
        _tj("historical_retrain", _run_historical_retrain),
        CronTrigger(day_of_week="sun", hour=3, minute=0, week="*/4"),
        id="historical_retrain",
        replace_existing=True,
        name="Historical xPts Model Retrain",
        max_instances=1,
        coalesce=True,
    )

    # Tuesday 15:00 — post-GW backtest
    scheduler.add_job(
        _tj("weekly_backtest", _run_weekly_backtest),
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
        _tj("anon_cleanup", _run_anonymous_data_cleanup),
        CronTrigger(hour=3, minute=30),
        id="anon_cleanup",
        replace_existing=True,
        name="Anonymous Data Cleanup",
        max_instances=1,
        coalesce=True,
    )

    scheduler.add_job(
        _tj("feature_drift_monitor", _run_feature_drift_monitor),
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
        _tj("competition_fixture_sync", _run_competition_fixture_sync),
        CronTrigger(hour=2, minute=0),
        id="competition_fixture_sync",
        replace_existing=True,
        name="Competition Fixture Sync (PL/UCL/FAC)",
        max_instances=1,
        coalesce=True,
    )

    # ── Every 5 min: GW state watcher (event-driven pipeline trigger) ──────────
    # Detects GW finish → schedules post-GW chain
    # Detects upcoming deadline (≤15 min) → triggers pre-deadline squad sync
    scheduler.add_job(
        _watch_gw_state,
        "interval",
        minutes=5,
        id="gw_state_watcher",
        replace_existing=True,
        name="GW State Watcher",
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
    Automatically snapshot the GW oracle for ALL registered users.
    Runs daily at 13:05 to catch most GW deadlines.
    The oracle route handles idempotency (updates existing record for same GW).
    Also includes the admin FPL_TEAM_ID if set.
    """
    try:
        from core.config import settings
        from core.database import AsyncSessionLocal
        from api.routes.oracle import _compute_oracle
        from sqlalchemy import select
        from models.db.gameweek import Gameweek
        from models.db.user_profile import UserProfile

        async with AsyncSessionLocal() as db:
            gw_res = await db.execute(select(Gameweek).where(Gameweek.is_current == True))
            current_gw = gw_res.scalar_one_or_none()
            if not current_gw:
                logger.warning("Oracle snapshot: no current GW found")
                return

            # Collect all team IDs: registered users + admin FPL_TEAM_ID
            users_res = await db.execute(select(UserProfile.team_id))
            team_ids: set[int] = {row[0] for row in users_res.fetchall()}
            if settings.FPL_TEAM_ID:
                team_ids.add(settings.FPL_TEAM_ID)

            if not team_ids:
                logger.info("Oracle snapshot: no registered users or FPL_TEAM_ID — skipping")
                return

            logger.info(f"Oracle snapshot: running for {len(team_ids)} teams (GW{current_gw.id})")
            success = 0
            for tid in team_ids:
                try:
                    record = await _compute_oracle(tid, current_gw.id, db)
                    logger.debug(
                        f"Oracle snapshot auto-taken: team={tid} GW{current_gw.id} "
                        f"oracle_xpts={record.oracle_xpts} algo_xpts={record.algo_xpts}"
                    )
                    success += 1
                except Exception as e:
                    logger.warning(f"Oracle snapshot failed for team {tid}: {e}")

            logger.info(f"Oracle snapshot complete: {success}/{len(team_ids)} teams OK")
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

            # Use gw_id+1 so that rolling stats include the completed current GW.
            # build_features_for_gw uses WHERE gw_id < :gw_id, so passing current+1
            # means "include GW{current} results" in the last-5-GW window.
            # This ensures Bruno's GW31 haul is visible when predicting GW32.
            predict_gw = current_gw.id + 1
            features = await build_features_for_gw(
                gw_id=predict_gw,
                db=db,
                redis=redis_client,
            )
            await update_latest_features(
                gw_id=current_gw.id,
                features=features,
                db=db,
            )
            logger.info(f"Feature store updated for GW{current_gw.id} (window up to GW{predict_gw-1}): {len(features)} players")
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
            # Record the GW this pipeline ran for so the startup auto-pipeline
            # check knows not to re-run it on the next restart.
            try:
                from core.redis_client import redis_client as _rc
                from core.database import AsyncSessionLocal as _Sess
                from models.db.gameweek import Gameweek as _GW
                from sqlalchemy import select as _sel
                async with _Sess() as _db:
                    _res = await _db.execute(_sel(_GW).where(_GW.is_current == True))
                    _gw = _res.scalar_one_or_none()
                if _gw:
                    await _rc.set("pipeline:last_gw_run", str(_gw.id))
            except Exception:
                pass
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


async def _watch_gw_state() -> None:
    """
    Runs every 5 minutes.  Detects two events and fires the right jobs:

    1. GW FINISH: current_gw.finished=True AND data_checked=True transitions to a
       new GW id we haven't processed yet.  Schedules the post-GW pipeline chain
       staggered over 45 minutes so FPL API data settles before each step.

    2. DEADLINE APPROACHING: next (or current) GW deadline is ≤15 minutes away.
       Triggers a one-shot pre-deadline squad sync so recommendations are based on
       the squad the user will actually submit (including pending transfers).

    Redis keys used:
      gw_watcher:last_finished_gw  — id of the last GW we triggered post-GW for
      gw_watcher:deadline_sync:{gw_id} — set when pre-deadline sync fires (24h TTL)
    """
    try:
        from core.redis_client import redis_client
        from core.database import AsyncSessionLocal
        from models.db.gameweek import Gameweek
        from sqlalchemy import select
        from datetime import timezone, timedelta

        async with AsyncSessionLocal() as db:
            cur_res = await db.execute(select(Gameweek).where(Gameweek.is_current == True))
            current_gw = cur_res.scalars().first()
            nxt_res = await db.execute(select(Gameweek).where(Gameweek.is_next == True))
            next_gw = nxt_res.scalars().first()

        now = datetime.now(timezone.utc)

        # ── Case 1: GW resolved — fire post-GW pipeline chain ────────────────
        # Primary trigger: finished=True AND data_checked=True (FPL fully settled).
        # Fallback trigger: gw_end_time + 24h elapsed regardless of FPL flags —
        #   FPL sometimes delays data_checked for days; we can't wait forever.
        # Either way we wait a minimum of 12h from gw_end_time so bonus points
        # and player scores settle before recommendations are regenerated.
        if current_gw:
            gw_end = current_gw.gw_end_time
            if gw_end and gw_end.tzinfo is None:
                gw_end = gw_end.replace(tzinfo=timezone.utc)

            twelve_hr_mark  = (gw_end + timedelta(hours=12))  if gw_end else None
            twentyfour_mark = (gw_end + timedelta(hours=24))   if gw_end else None

            # Condition A: FPL fully settled + 12h elapsed
            fpl_ready = current_gw.finished and current_gw.data_checked and twelve_hr_mark and now >= twelve_hr_mark
            # Condition B: 24h elapsed regardless of FPL flags (safety net)
            timeout_ready = twentyfour_mark and now >= twentyfour_mark

            if fpl_ready or timeout_ready:
                # Idempotency: check whether the pipeline ACTUALLY RAN for this GW.
                # We intentionally do NOT use a separate "last_finished_gw" lock because
                # if the container restarts after the lock is set but before APScheduler
                # jobs execute, the in-memory jobs are lost and the pipeline never runs.
                # Instead we check the pipeline's own completion marker in Redis.
                pipeline_ran_raw = await redis_client.get("pipeline:last_gw_run")
                pipeline_ran_id  = int(pipeline_ran_raw) if pipeline_ran_raw else None

                if pipeline_ran_id != current_gw.id:
                    trigger = "FPL data_checked + 12h" if fpl_ready else "24h timeout (data_checked pending)"
                    logger.info(
                        f"[GW Watcher] GW{current_gw.id} — {trigger} — "
                        f"pipeline not yet run for this GW — scheduling post-GW chain"
                    )
                    base = now + timedelta(minutes=1)   # start immediately
                    _schedule_post_gw_chain(current_gw.id, base)
                else:
                    logger.debug(
                        f"[GW Watcher] GW{current_gw.id} — post-GW pipeline already "
                        f"ran (pipeline:last_gw_run={pipeline_ran_id}) — skipping"
                    )
            elif twelve_hr_mark and now < twelve_hr_mark:
                mins_left = (twelve_hr_mark - now).total_seconds() / 60
                logger.debug(
                    f"[GW Watcher] GW{current_gw.id} 12h window not elapsed "
                    f"({mins_left:.0f}min remaining)"
                )

        # ── Case 2: 1 hour before first kick-off ────────────────────────────
        # In FPL the deadline is ~1hr before the first game, so this fires
        # right around deadline time — squad is locked, all pending transfers
        # are applied by FPL. We sync every user's squad and run cross-check.
        target_gw = next_gw or current_gw
        if target_gw and target_gw.gw_start_time:
            kick_off = target_gw.gw_start_time
            if kick_off.tzinfo is None:
                kick_off = kick_off.replace(tzinfo=timezone.utc)

            mins_to_kickoff = (kick_off - now).total_seconds() / 60.0

            if 0 < mins_to_kickoff <= 65:  # window: 0–65 min before first game
                lock_key = f"gw_watcher:pre_kickoff_sync:{target_gw.id}"
                already_done = await redis_client.get(lock_key)
                if not already_done:
                    await redis_client.set(lock_key, "1", ex=86400)
                    logger.info(
                        f"[GW Watcher] GW{target_gw.id} kick-off in "
                        f"{mins_to_kickoff:.0f}min — firing pre-kick-off squad sync + cross-check"
                    )
                    await _run_pre_deadline_squad_sync(target_gw.id)

    except Exception as e:
        logger.error(f"[GW Watcher] failed: {e}")


def _schedule_post_gw_chain(gw_id: int, base_time: "datetime") -> None:
    """
    Register staggered one-shot APScheduler jobs for the post-GW pipeline.
    Each step fires with a grace period so the previous one can finish and FPL
    API data can settle.

    Chain:
      base + 0min  → full pipeline   (bootstrap, fixtures, players, FDR, blank/double)
      base + 8min  → ML model refresh + feature store
      base + 18min → Oracle auto-resolve + online calibration
      base + 28min → weekly backtest (season accuracy)
      base + 38min → MAE check → retrain if degraded
    """
    from datetime import timedelta

    # ML predictions are already run inside _run_full_pipeline (step 8),
    # so there is no separate "ML refresh" step here.
    #
    # Chain timeline (from base_time):
    #   +0  min : full pipeline — fresh player data, fixtures, FDR, ML predictions
    #   +15 min : squad sync (all users) — FH-aware, sets correct GW+1 planning squad
    #   +20 min : Oracle resolve + calibration (mean residuals + isotonic calibrators)
    #   +30 min : weekly backtest — season accuracy metrics
    #   +35 min : MAE check → historical retrain if severely degraded (MAE > 2.5)
    #   +45 min : incremental retrain from local DB + SHAP importance + calibrator refresh
    # Total worst-case: ~55 min (60 min = safe buffer)
    _ssid = f"post_gw_{gw_id}_squad_sync"
    _retrain_id = f"post_gw_{gw_id}_retrain"
    steps = [
        (0,  f"post_gw_{gw_id}_pipeline",    f"GW{gw_id} Post-GW: Full Pipeline",                    _tj(f"post_gw_{gw_id}_pipeline",   _run_full_pipeline)),
        (15, _ssid,                           f"GW{gw_id} Post-GW: Squad Sync (all users)",           _tj(_ssid,                         lambda: _run_post_gw_squad_sync(gw_id))),
        (20, f"post_gw_{gw_id}_oracle",      f"GW{gw_id} Post-GW: Oracle Resolve + Calibration",     _tj(f"post_gw_{gw_id}_oracle",     _run_oracle_auto_resolve_and_learn)),
        (30, f"post_gw_{gw_id}_backtest",    f"GW{gw_id} Post-GW: Backtest",                         _tj(f"post_gw_{gw_id}_backtest",   _run_weekly_backtest)),
        (35, f"post_gw_{gw_id}_mae",         f"GW{gw_id} Post-GW: MAE/Retrain Check",                _tj(f"post_gw_{gw_id}_mae",        _check_mae_and_retrain)),
        (45, _retrain_id,                    f"GW{gw_id} Post-GW: Incremental Retrain + SHAP",        _tj(_retrain_id,                   lambda: _run_post_gw_retrain(gw_id))),
    ]

    for offset_min, job_id, name, fn in steps:
        fire_at = base_time + timedelta(minutes=offset_min)
        scheduler.add_job(
            fn,
            "date",
            run_date=fire_at,
            id=job_id,
            name=name,
            replace_existing=True,
            misfire_grace_time=3600,
        )
        logger.info(
            f"[GW Watcher] Scheduled '{name}' at "
            f"{fire_at.strftime('%Y-%m-%d %H:%M UTC')}"
        )


async def _run_pre_deadline_squad_sync(gw_id: int) -> None:
    """
    Fires 5–15 minutes before each GW deadline.

    For every registered user, re-fetches their squad from FPL API including
    any pending transfers made since the last GW ended.  This ensures the
    strategy page recommendations are based on the squad they'll actually submit,
    not last GW's squad.

    Flow:
      1. Fetch all registered user team_ids
      2. For each: call fetcher.sync_squad_with_pending_transfers(team_id, gw_id)
         which applies pending transfers from entry/{id}/transfers/ endpoint
      3. Re-run ML predictions with fresh squad data so xPts reflect actual picks
    """
    try:
        from core.database import AsyncSessionLocal
        from models.db.user_profile import UserProfile
        from sqlalchemy import select

        async with AsyncSessionLocal() as db:
            users_res = await db.execute(select(UserProfile.team_id))
            team_ids = [row[0] for row in users_res.fetchall()]

        if not team_ids:
            logger.info(f"[Pre-deadline sync] GW{gw_id}: no registered users, skipping")
            return

        logger.info(
            f"[Pre-deadline sync] GW{gw_id}: syncing {len(team_ids)} registered users"
        )

        if _fetcher:
            for tid in team_ids:
                try:
                    await _fetcher.sync_squad_with_pending_transfers(tid, gw_id)
                except Exception as e:
                    logger.warning(
                        f"[Pre-deadline sync] squad sync failed for team {tid}: {e}"
                    )

            # Refresh ML predictions after squad data is updated
            try:
                await _fetcher.run_ml_predictions()
                logger.info(
                    f"[Pre-deadline sync] GW{gw_id}: ML predictions refreshed "
                    f"after squad sync"
                )
            except Exception as e:
                logger.warning(f"[Pre-deadline sync] ML refresh failed: {e}")

    except Exception as e:
        logger.error(f"[Pre-deadline sync] GW{gw_id} failed: {e}")
        await _send_admin_alert_safe(
            f"Pre-Deadline Squad Sync Failed (GW{gw_id})",
            f"_run_pre_deadline_squad_sync raised:\n\n{type(e).__name__}: {e}",
        )


async def _run_post_gw_squad_sync(gw_id: int) -> None:
    """
    Post-GW squad sync — fires after the full pipeline completes.

    For every registered user, re-fetches their squad from FPL API using
    sync_squad_with_pending_transfers which already contains Free Hit detection:
    if the just-finished GW was a Free Hit, it fetches the pre-FH squad instead
    so GW+1 recommendations are based on their real planning squad.

    Runs BEFORE Oracle resolve so decision audit has the correct squad context.
    """
    next_gw_id = gw_id + 1
    try:
        from core.database import AsyncSessionLocal
        from models.db.user_profile import UserProfile
        from sqlalchemy import select

        async with AsyncSessionLocal() as db:
            users_res = await db.execute(select(UserProfile.team_id))
            team_ids = [row[0] for row in users_res.fetchall()]

        if not team_ids:
            logger.info(f"[Post-GW squad sync] GW{gw_id}: no registered users")
            return

        logger.info(
            f"[Post-GW squad sync] GW{gw_id}: syncing {len(team_ids)} users for GW{next_gw_id}"
        )

        if _fetcher:
            for tid in team_ids:
                try:
                    await _fetcher.sync_squad_with_pending_transfers(tid, next_gw_id)
                except Exception as e:
                    logger.warning(
                        f"[Post-GW squad sync] team {tid} failed (non-fatal): {e}"
                    )

    except Exception as e:
        logger.error(f"[Post-GW squad sync] GW{gw_id} failed: {e}")
        await _send_admin_alert_safe(
            f"Post-GW Squad Sync Failed (GW{gw_id})",
            f"_run_post_gw_squad_sync raised:\n\n{type(e).__name__}: {e}",
        )


async def _resolve_all_user_decisions() -> None:
    """
    After each GW settles: run resolve_gw_decisions for ALL registered users.

    This ensures every user's decision_log rows get rewards computed and bandit
    Q-values updated — not just the admin's FPL_TEAM_ID.

    Queries the last finished GW (finished=True, data_checked=True) and iterates
    all rows in user_profile.
    """
    try:
        from core.database import AsyncSessionLocal
        from models.db.gameweek import Gameweek
        from models.db.user_profile import UserProfile
        from rl.resolve_decisions import resolve_gw_decisions
        from sqlalchemy import select

        async with AsyncSessionLocal() as db:
            # Find last settled GW
            gw_res = await db.execute(
                select(Gameweek)
                .where(Gameweek.finished == True, Gameweek.data_checked == True)
                .order_by(Gameweek.id.desc())
            )
            last_gw = gw_res.scalars().first()
            if not last_gw:
                logger.info("[resolve_all_users] No settled GW found — skipping")
                return

            # All registered users
            users_res = await db.execute(select(UserProfile.team_id))
            team_ids = [row[0] for row in users_res.fetchall()]

        if not team_ids:
            logger.info("[resolve_all_users] No registered users — skipping")
            return

        logger.info(
            f"[resolve_all_users] Resolving GW{last_gw.id} decisions "
            f"for {len(team_ids)} registered users"
        )
        failed = 0
        for tid in team_ids:
            try:
                async with AsyncSessionLocal() as db:
                    await resolve_gw_decisions(
                        team_id=tid,
                        gw_id=last_gw.id,
                        db=db,
                    )
            except Exception as e:
                logger.warning(f"[resolve_all_users] team {tid} failed: {e}")
                failed += 1

        logger.info(
            f"[resolve_all_users] Done. "
            f"{len(team_ids) - failed}/{len(team_ids)} users resolved."
        )
    except Exception as e:
        logger.error(f"[resolve_all_users] Unexpected error: {e}")
        await _send_admin_alert_safe(
            "Decision Resolve (All Users) Failed",
            f"_resolve_all_user_decisions raised:\n\n{type(e).__name__}: {e}",
        )


async def _run_oracle_auto_resolve_and_learn() -> None:
    """
    After each GW: auto-resolve oracle snapshots + fetch top team + run ML learner.
    Also runs online calibration to correct per-position/price-band prediction residuals.
    Runs Tuesdays at 14:00 (after Monday night fixtures settle).
    Resolves oracle for ALL registered users (not just FPL_TEAM_ID).
    """
    try:
        from core.config import settings
        from core.database import AsyncSessionLocal
        from models.db.user_profile import UserProfile
        from services.job_queue import enqueue_job
        from sqlalchemy import select

        # Collect all team IDs: registered users + admin FPL_TEAM_ID
        async with AsyncSessionLocal() as db:
            users_res = await db.execute(select(UserProfile.team_id))
            team_ids: set[int] = {row[0] for row in users_res.fetchall()}
        if settings.FPL_TEAM_ID:
            team_ids.add(settings.FPL_TEAM_ID)

        if not team_ids:
            logger.warning("oracle_auto_resolve: no registered users or FPL_TEAM_ID — skipping")
        else:
            logger.info(f"Oracle auto-resolve: enqueueing for {len(team_ids)} teams")
            for tid in team_ids:
                try:
                    await enqueue_job(job_type="oracle.auto_resolve", payload={"team_id": tid})
                except Exception as e:
                    logger.warning(f"oracle_auto_resolve: enqueue failed for team {tid}: {e}")

        # ── Resolve decisions + bandit for ALL registered users ───────────────
        await _resolve_all_user_decisions()

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
    Compute per-(position, price_band) mean residuals from last 10 GWs and
    write to Redis ml:calibration_map + prediction_calibration table.

    Data source: player_features_history × player_gw_history.
    The features table stores predicted_xpts_next at gw_id=N (prediction for N+1).
    The history table stores total_points at gw_id=N+1 (actual score for N+1).
    Residual = actual(N+1) - predicted_next(from N).

    This bypasses the predictions table which has a gw_id=0 data bug.
    """
    try:
        from core.database import AsyncSessionLocal
        from core.redis_client import redis_client
        from models.db.feature_store import PlayerFeaturesHistory
        from models.db.history import PlayerGWHistory
        from sqlalchemy import select
        import orjson
        import json as _json
        from collections import defaultdict

        async with AsyncSessionLocal() as db:
            # ── Determine max GW with actual points data ──────────────────────
            from sqlalchemy import func as _func
            max_actual_res = await db.execute(select(_func.max(PlayerGWHistory.gw_id)))
            max_actual_gw = max_actual_res.scalar() or 0
            if max_actual_gw < 2:
                logger.info("Online calibration: insufficient GW history data")
                return

            # ── Load feature history for GWs where actuals exist (gw N predicts N+1) ──
            # Features at gw_id=N predict xPts for GW N+1, so we need gw_id <= max_actual_gw-1
            feat_res = await db.execute(
                select(
                    PlayerFeaturesHistory.player_id,
                    PlayerFeaturesHistory.gw_id,
                    PlayerFeaturesHistory.features_json,
                ).where(
                    PlayerFeaturesHistory.gw_id <= max_actual_gw - 1
                ).order_by(PlayerFeaturesHistory.gw_id.desc()).limit(15000)
            )
            feat_rows = feat_res.fetchall()
            if not feat_rows:
                logger.info("Online calibration: no feature history available yet")
                return

            # Build lookup: (player_id, gw_id) → (predicted_xpts_next, position, value)
            pred_at_gw: dict[tuple, dict] = {}
            for row in feat_rows:
                fj = row.features_json
                if isinstance(fj, str):
                    try:
                        fj = _json.loads(fj)
                    except Exception:
                        continue
                pred_xpts = fj.get("predicted_xpts_next")
                if pred_xpts is None or pred_xpts <= 0:
                    continue
                pred_at_gw[(row.player_id, row.gw_id)] = {
                    "predicted": float(pred_xpts),
                    "position": int(fj.get("position", 3)),
                    "value": int(fj.get("value", 50)),  # pence × 10
                }

            # ── Load actual points (gw N+1) ──────────────────────────────────
            if not pred_at_gw:
                logger.info("Online calibration: no valid predictions in feature history")
                return
            min_gw = min(gw for (_, gw) in pred_at_gw)
            max_gw = max(gw for (_, gw) in pred_at_gw)

            hist_res = await db.execute(
                select(
                    PlayerGWHistory.player_id,
                    PlayerGWHistory.gw_id,
                    PlayerGWHistory.total_points,
                ).where(
                    PlayerGWHistory.gw_id.between(min_gw + 1, max_gw + 1)
                )
            )
            actuals: dict[tuple, float] = {
                (row.player_id, row.gw_id): float(row.total_points or 0)
                for row in hist_res.fetchall()
            }

            # ── Compute residuals per (position, price_band) ─────────────────
            residuals: dict[tuple, list[float]] = defaultdict(list)
            # Raw (pred, actual) pairs per group — needed for isotonic fitting
            raw_pairs: dict[tuple, tuple[list, list]] = defaultdict(lambda: ([], []))
            n_matched = 0

            for (player_id, gw_n), info in pred_at_gw.items():
                actual = actuals.get((player_id, gw_n + 1))
                if actual is None:
                    continue
                residual = actual - info["predicted"]
                # Band = £ value rounded to nearest £1m  (value in pence × 10, so /10)
                price_band = round(info["value"] / 10)
                key = (info["position"], price_band)
                residuals[key].append(residual)
                raw_pairs[key][0].append(info["predicted"])
                raw_pairs[key][1].append(actual)
                n_matched += 1

            if n_matched == 0:
                logger.warning("Online calibration: 0 (prediction, actual) pairs matched — check data pipeline")
                return

            # ── Build calibration map with friendly keys ──────────────────────
            # Format: "GK_4" → position_priceband (int band = £Xm)
            # Admin endpoint parses: key.split("_",1) → [position_name, price_band]
            pos_names = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
            calibration_map = {
                f"{pos_names.get(pos, str(pos))}_{band}": round(sum(v) / len(v), 4)
                for (pos, band), v in residuals.items()
                if len(v) >= 2  # minimum 2 samples
            }

            # ── Write to Redis (admin endpoint falls back to this if DB empty) ─
            await redis_client.set(
                "ml:calibration_map",
                orjson.dumps(calibration_map).decode(),
                ex=8 * 86400,
            )

            logger.info(
                f"Online calibration updated: {len(calibration_map)} position/price groups, "
                f"n_matched={n_matched}"
            )

            # ── Fit isotonic calibrators from raw (pred, actual) pairs ────────
            # These are out-of-sample predictions (stored before each GW was
            # played), so fitting isotonic regression on them is bias-free.
            try:
                if _fetcher is not None and hasattr(_fetcher, "xpts_model"):
                    all_preds, all_actuals, all_pos, all_bands = [], [], [], []
                    for (pos, band), (preds_list, actuals_list) in raw_pairs.items():
                        for p, a in zip(preds_list, actuals_list):
                            all_preds.append(p)
                            all_actuals.append(a)
                            all_pos.append(pos)
                            all_bands.append(band)

                    if all_preds:
                        summary = _fetcher.xpts_model.train_calibrators(
                            y_pred    = np.array(all_preds,   dtype=float),
                            y_actual  = np.array(all_actuals, dtype=float),
                            positions = np.array(all_pos,     dtype=int),
                            price_bands = np.array(all_bands, dtype=int),
                        )
                        n_groups_fitted = len(summary)
                        logger.info(
                            f"Isotonic calibrators fitted: {n_groups_fitted} groups "
                            f"({n_matched} (pred, actual) pairs)"
                        )
                        # Persist calibrator summary to Redis for admin panel
                        await redis_client.set(
                            "ml:isotonic_calibration_summary",
                            orjson.dumps(summary).decode(),
                            ex=8 * 86400,
                        )
            except Exception as _iso_err:
                logger.warning(f"Isotonic calibrator fitting failed (non-fatal): {_iso_err}")

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
        import orjson as _orjson
        from datetime import timezone as _tz
        from core.redis_client import redis_client as _redis_retrain
        from data_pipeline.historical_fetcher import HistoricalFetcher
        async with HistoricalFetcher() as fetcher:
            # Train on last 3 seasons
            metrics = await fetcher.retrain_xpts_model(seasons=["2022-23", "2023-24", "2024-25"])
            logger.info(f"Historical retrain complete: {metrics}")
            # ── Write feature importance to Redis for admin ML panel ─────────
            fi = metrics.get("feature_importance", {})
            if fi:
                fi_list = sorted(
                    [{"feature": k, "importance": int(v)} for k, v in fi.items()],
                    key=lambda x: x["importance"], reverse=True
                )
                await _redis_retrain.set(
                    "ml:feature_importance",
                    _orjson.dumps(fi_list).decode(),
                    ex=86400 * 30,
                )
            # ── Write SHAP importance to Redis ────────────────────────────────
            # SHAP distributes credit fairly among correlated features
            # (xa_last_5_gws, xg_last_5_gws etc.) unlike gain importance.
            shap_fi = metrics.get("shap_importance", {})
            if shap_fi:
                shap_list = sorted(
                    [{"feature": k, "importance": round(float(v), 4)} for k, v in shap_fi.items()],
                    key=lambda x: x["importance"], reverse=True
                )
                await _redis_retrain.set(
                    "ml:shap_importance",
                    _orjson.dumps(shap_list).decode(),
                    ex=86400 * 30,
                )
                logger.info(
                    f"SHAP importance stored: top feature = "
                    f"{shap_list[0]['feature']} ({shap_list[0]['importance']:.4f})"
                    if shap_list else "SHAP list empty"
                )
            # ── Write model RMSE for Monte Carlo and calibration use ─────────
            cv_rmse = metrics.get("cv_rmse")
            if cv_rmse and isinstance(cv_rmse, float):
                await _redis_retrain.set(
                    "ml:model_rmse",
                    str(round(cv_rmse, 4)),
                    ex=86400 * 30,
                )
            # ── Write retrain timestamp ──────────────────────────────────────
            await _redis_retrain.set(
                "ml:last_retrain_ts",
                datetime.now(_tz.utc).isoformat(),
                ex=86400 * 30,
            )
            # ── Reload in-memory model so next prediction uses new artifact ──
            if _fetcher is not None and hasattr(_fetcher, "xpts_model"):
                _fetcher.xpts_model._load()
                _fetcher.xpts_model._load_calibrators()
                logger.info("In-memory xPts model + calibrators reloaded after historical retrain")
    except Exception as e:
        logger.error(f"Historical retrain failed: {e}")
        await _send_admin_alert_safe(
            "Historical Model Retrain Failed",
            f"_run_historical_retrain raised:\n\n{type(e).__name__}: {e}",
        )


async def _run_post_gw_retrain(gw_id: int | None = None) -> None:
    """
    Post-GW incremental retrain — fires ~45 min after the last game of each GW.

    Why this exists vs the monthly historical retrain:
    - The monthly retrain fires on the 4th Sunday regardless of GW timing.
    - Every GW adds ~700 new (player, actual_points) training rows.  Waiting a
      month means the model misses 4–5 GWs of fresh signal before correcting.
    - This job runs from LOCAL DB data (no vaastav download) so it finishes in
      under 60 seconds even on a cold container.

    Pipeline:
      1. Load feature history + actuals from DB (all ingested seasons).
      2. Train a candidate model → compute SHAP + gain importance.
      3. Compare candidate MAE vs current production MAE (last 5 GWs).
      4. Promote candidate only if MAE improved (or no production model yet).
      5. Write ml:shap_importance, ml:feature_importance to Redis.
      6. Reload in-memory model + calibrators.
      7. Re-run online calibration to fit isotonic calibrators for new model.

    Idempotent: Redis key ml:post_gw_retrain:last_gw prevents double-running
    for the same GW (e.g. container restart mid-chain).
    """
    try:
        import orjson as _orjson
        import numpy as _np
        from datetime import timezone as _tz, timedelta as _td
        from core.redis_client import redis_client as _rc
        from core.database import AsyncSessionLocal
        from models.db.feature_store import PlayerFeaturesHistory
        from models.db.history import PlayerGWHistory
        from sqlalchemy import select
        import json as _json

        # ── Idempotency guard ─────────────────────────────────────────────────
        if gw_id is not None:
            last_retrain_gw_raw = await _rc.get("ml:post_gw_retrain:last_gw")
            last_retrain_gw = int(last_retrain_gw_raw) if last_retrain_gw_raw else None
            if last_retrain_gw == gw_id:
                logger.info(
                    f"[post_gw_retrain] Already ran for GW{gw_id} — skipping"
                )
                return

        logger.info(
            f"[post_gw_retrain] Starting incremental retrain"
            + (f" (GW{gw_id})" if gw_id else "")
        )

        # ── Step 1: Load training data from local DB ──────────────────────────
        # Features stored in player_features_history contain the model's
        # pre-GW predictions (predicted_xpts_next) and all feature values.
        # Actuals are in player_gw_history.total_points for gw_id+1.
        import pandas as _pd

        async with AsyncSessionLocal() as db:
            feat_res = await db.execute(
                select(
                    PlayerFeaturesHistory.player_id,
                    PlayerFeaturesHistory.gw_id,
                    PlayerFeaturesHistory.features_json,
                ).order_by(PlayerFeaturesHistory.gw_id)
            )
            feat_rows = feat_res.fetchall()

            hist_res = await db.execute(
                select(
                    PlayerGWHistory.player_id,
                    PlayerGWHistory.gw_id,
                    PlayerGWHistory.total_points,
                )
            )
            hist_rows = hist_res.fetchall()

        if not feat_rows or not hist_rows:
            logger.warning("[post_gw_retrain] Insufficient DB data — skipping")
            return

        actuals_map: dict[tuple, float] = {
            (int(r.player_id), int(r.gw_id)): float(r.total_points or 0)
            for r in hist_rows
        }

        # Build rows: features at gw_id=N predict actual at gw_id=N+1
        from models.ml.xpts_model import XPTS_FEATURES
        records = []
        for row in feat_rows:
            fj = row.features_json
            if isinstance(fj, str):
                try:
                    fj = _json.loads(fj)
                except Exception:
                    continue
            if not isinstance(fj, dict):
                continue
            actual = actuals_map.get((int(row.player_id), int(row.gw_id) + 1))
            if actual is None:
                continue
            record = {f: fj.get(f, 0.0) for f in XPTS_FEATURES}
            record["actual_points"] = actual
            records.append(record)

        if len(records) < 200:
            logger.warning(
                f"[post_gw_retrain] Only {len(records)} matched rows — "
                f"need ≥200 for meaningful retrain"
            )
            return

        train_df = _pd.DataFrame(records).fillna(0)
        logger.info(
            f"[post_gw_retrain] Training dataset: {len(train_df)} rows, "
            f"{len(XPTS_FEATURES)} features"
        )

        # ── Step 2: Train candidate model ─────────────────────────────────────
        from models.ml.xpts_model import XPtsModel, MODEL_PATH
        import joblib as _jl
        import shutil as _sh
        from pathlib import Path as _P

        candidate = XPtsModel.__new__(XPtsModel)
        candidate.model = None
        candidate.calibrators = {}

        metrics = candidate.train(train_df)
        if "error" in metrics:
            logger.error(f"[post_gw_retrain] Training failed: {metrics['error']}")
            return

        candidate_rmse = metrics.get("cv_rmse", 999.0)
        logger.info(f"[post_gw_retrain] Candidate RMSE: {candidate_rmse:.4f}")

        # ── Step 3: Compare candidate vs production MAE ───────────────────────
        # Use cross-val RMSE as the comparison metric (computed inside train()).
        prod_rmse_raw = await _rc.get("ml:cv_rmse")
        prod_rmse = float(prod_rmse_raw) if prod_rmse_raw else None

        should_promote = (
            prod_rmse is None                      # no production model yet
            or candidate_rmse < prod_rmse + 0.02   # candidate at most 0.02 worse
            #  ^ allow tiny regressions to still promote so we don't get stuck
        )

        if not should_promote:
            logger.info(
                f"[post_gw_retrain] Candidate RMSE={candidate_rmse:.4f} worse than "
                f"production RMSE={prod_rmse:.4f} by >{0.02} — NOT promoting"
            )
            return

        # ── Step 4: Promote candidate ─────────────────────────────────────────
        # candidate.train() already saved the model to MODEL_PATH (XPtsModel
        # always writes to the shared artifact path). Record the production RMSE.
        await _rc.set("ml:cv_rmse", str(round(candidate_rmse, 4)), ex=86400 * 30)
        logger.info(
            f"[post_gw_retrain] Promoted candidate: RMSE={candidate_rmse:.4f}"
            + (f" (was {prod_rmse:.4f})" if prod_rmse else " (first model)")
        )

        # ── Step 5: Write importance metrics to Redis ─────────────────────────
        now_iso = datetime.now(_tz.utc).isoformat()

        fi = metrics.get("feature_importance", {})
        if fi:
            fi_list = sorted(
                [{"feature": k, "importance": int(v)} for k, v in fi.items()],
                key=lambda x: x["importance"], reverse=True,
            )
            await _rc.set(
                "ml:feature_importance",
                _orjson.dumps(fi_list).decode(),
                ex=86400 * 30,
            )

        shap_fi = metrics.get("shap_importance", {})
        if shap_fi:
            shap_list = sorted(
                [{"feature": k, "importance": round(float(v), 4)} for k, v in shap_fi.items()],
                key=lambda x: x["importance"], reverse=True,
            )
            await _rc.set(
                "ml:shap_importance",
                _orjson.dumps(shap_list).decode(),
                ex=86400 * 30,
            )
            logger.info(
                f"[post_gw_retrain] SHAP stored — "
                f"top: {shap_list[0]['feature']} ({shap_list[0]['importance']:.4f})"
                if shap_list else "[post_gw_retrain] SHAP list empty"
            )

        await _rc.set("ml:last_retrain_ts", now_iso, ex=86400 * 30)
        if gw_id is not None:
            await _rc.set("ml:post_gw_retrain:last_gw", str(gw_id), ex=86400 * 7)

        # ── Step 6: Reload in-memory model + calibrators ──────────────────────
        if _fetcher is not None and hasattr(_fetcher, "xpts_model"):
            _fetcher.xpts_model._load()
            _fetcher.xpts_model._load_calibrators()
            logger.info(
                "[post_gw_retrain] In-memory xPts model + calibrators reloaded"
            )

        # ── Step 7: Refit isotonic calibrators for the new model ──────────────
        # After a retrain the old calibrators map OLD model predictions → actuals.
        # Re-running online calibration will collect fresh residuals using the
        # updated model's prediction column from player_features_history and
        # refit isotonic calibrators against actuals.
        await _run_online_calibration()
        logger.info("[post_gw_retrain] Isotonic calibrators refreshed for new model")

    except Exception as e:
        logger.error(f"[post_gw_retrain] Failed: {e}")
        await _send_admin_alert_safe(
            "Post-GW Retrain Failed",
            f"_run_post_gw_retrain raised:\n\n{type(e).__name__}: {e}",
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
                    f"{settings.PUBLIC_APP_URL}/api/intel/gw?team_id={settings.FPL_TEAM_ID}"
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

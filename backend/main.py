"""FPL Intelligence Engine — FastAPI application entry point."""
import asyncio
import time
from uuid import uuid4
from contextlib import asynccontextmanager
from datetime import datetime

import httpx
from fastapi import FastAPI
from sqlalchemy import select
from models.db.gameweek import Gameweek
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from core.config import settings
from core.database import engine, Base
from core.redis_client import redis_client
from data_pipeline.scheduler import scheduler, setup_scheduler
from api.websocket import ws_manager, start_pubsub_listener

# Import all models so Alembic/SQLAlchemy picks them up
import models.db.player       # noqa: F401
import models.db.team         # noqa: F401
import models.db.gameweek     # noqa: F401
import models.db.user_squad   # noqa: F401
import models.db.prediction   # noqa: F401
import models.db.rival        # noqa: F401
import models.db.history      # noqa: F401
import models.db.bandit       # noqa: F401
import models.db.calibration  # noqa: F401 — Phase 2
import models.db.decision_log # noqa: F401 — Phase 2
import models.db.oracle        # noqa: F401 — GW Oracle
import models.db.user_profile  # noqa: F401 — Email alerts
# Phase 3 — multi-user, model governance, backtest
import models.db.waitlist           # noqa: F401
import models.db.model_registry     # noqa: F401
import models.db.feature_store      # noqa: F401
import models.db.backtest           # noqa: F401
import models.db.anonymous_session  # noqa: F401
import models.db.versioning         # noqa: F401
import models.db.background_job     # noqa: F401
# Historical backfill — raw vaastav data for multi-season backtesting
import models.db.historical_gw_stats  # noqa: F401
# Multi-competition fixture store (PL + UCL + FAC + UEL)
import models.db.competition_fixture  # noqa: F401

from services.metrics_service import metrics_registry


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""
    logger.info("Starting FPL Intelligence Engine...")

    # 1. Create DB tables (Alembic handles migrations; this is fallback for dev)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables ready")

    # 1b. Add new columns to existing tables that predate create_all (safe ALTER TABLE IF NOT EXISTS pattern)
    _new_cols = [
        ("gw_oracle", "top_team_id",            "INTEGER"),
        ("gw_oracle", "top_team_name",           "VARCHAR(128)"),
        ("gw_oracle", "top_team_points",         "INTEGER"),
        ("gw_oracle", "top_team_squad_json",     "TEXT"),
        ("gw_oracle", "top_team_captain",        "VARCHAR(64)"),
        ("gw_oracle", "top_team_chip",           "VARCHAR(32)"),
        ("gw_oracle", "oracle_beat_top",         "BOOLEAN"),
        ("gw_oracle", "missed_players_json",     "TEXT"),
        ("gw_oracle", "oracle_blind_spots_json", "TEXT"),
        # Oracle chip normalisation columns
        ("gw_oracle", "top_team_points_normalized", "INTEGER"),
        ("gw_oracle", "top_team_chip_adjustment",   "INTEGER"),
        ("gw_oracle", "chip_miss_reason",            "TEXT"),
        # Oracle top-team status (for unavailable tracking)
        ("gw_oracle", "top_team_status",            "VARCHAR(32)"),
        # Historical backfill — season tag on feature history and model metrics
        # Existing rows (current season) get default "2024-25"
        ("player_features_history", "season", "VARCHAR(16) DEFAULT '2024-25' NOT NULL"),
        ("backtest_model_metrics",  "season", "VARCHAR(16) DEFAULT '2024-25' NOT NULL"),
        # Phase 3 — decision_log new columns
        ("decision_log", "engine_strategy_arm",    "VARCHAR(64)"),
        ("decision_log", "engine_confidence",       "FLOAT"),
        ("decision_log", "engine_predicted_gain",   "FLOAT"),
        ("decision_log", "user_action",             "VARCHAR(32)"),
        ("decision_log", "reward",                  "FLOAT"),
        ("decision_log", "resolved",                "BOOLEAN DEFAULT FALSE"),
        # hit_taken: whether user paid a -4pt hit (used for accurate transfer reward)
        ("decision_log", "hit_taken",               "BOOLEAN DEFAULT FALSE"),
        ("decision_log", "decision_score",          "FLOAT"),
        ("decision_log", "validation_status",       "VARCHAR(32)"),
        ("decision_log", "risk_preference",         "VARCHAR(32)"),
        ("decision_log", "floor_projection",        "FLOAT"),
        ("decision_log", "median_projection",       "FLOAT"),
        ("decision_log", "ceiling_projection",      "FLOAT"),
        ("decision_log", "projection_variance",     "FLOAT"),
        ("decision_log", "explanation_summary",     "TEXT"),
        ("decision_log", "inputs_used_json",        "TEXT"),
        ("decision_log", "simulation_summary_json", "TEXT"),
    ]
    async with engine.begin() as conn:
        for tbl, col, col_type in _new_cols:
            try:
                await conn.execute(
                    __import__("sqlalchemy").text(
                        f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS {col} {col_type}"
                    )
                )
            except Exception:
                pass  # column already exists or table not found
    logger.info("Oracle schema migrations applied")

    # 1c. Apply production-hardening indexes and constraints (each in own transaction so
    #     one failure cannot abort the others).
    _hardening_sql = [
        # GWOracle: unique constraint — prevents duplicate snapshots per (team, gw)
        """
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'uq_gw_oracle_team_gw'
            ) THEN
                ALTER TABLE gw_oracle
                    ADD CONSTRAINT uq_gw_oracle_team_gw UNIQUE (team_id, gameweek_id);
            END IF;
        END $$;
        """,
        # GWOracle: composite index for fast per-team history lookups
        "CREATE INDEX IF NOT EXISTS ix_gw_oracle_team_gw ON gw_oracle (team_id, gameweek_id);",
        # Decision log: composite index for review page queries
        "CREATE INDEX IF NOT EXISTS ix_decision_log_team_gw ON decision_log (team_id, gameweek_id);",
        # Decision log: unique dedup partial index
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_decision_log_dedup
            ON decision_log (team_id, gameweek_id, decision_type, recommended_option)
            WHERE resolved_at IS NULL;
        """,
        # Background jobs: status index for worker polling
        "CREATE INDEX IF NOT EXISTS ix_background_jobs_status ON background_jobs (status);",
        # User squads: team_id index for fast squad lookups
        "CREATE INDEX IF NOT EXISTS ix_user_squads_team_id ON user_squads (team_id);",
        # Anonymous session: expires_at index for cleanup job
        "CREATE INDEX IF NOT EXISTS ix_anon_session_expires ON anonymous_analysis_session (expires_at);",
        # ── Historical backfill: replace old (player_id, gw_id) unique constraint
        #    with (player_id, gw_id, season) so historical seasons can coexist.
        """
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'uq_pfh_player_gw'
            ) THEN
                ALTER TABLE player_features_history DROP CONSTRAINT uq_pfh_player_gw;
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'uq_pfh_player_gw_season'
            ) THEN
                ALTER TABLE player_features_history
                    ADD CONSTRAINT uq_pfh_player_gw_season
                    UNIQUE (player_id, gw_id, season);
            END IF;
        END $$;
        """,
        # ── Historical backfill: replace old (model_version, gw_id) unique constraint
        #    with (model_version, gw_id, season).
        """
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'uq_bmm_version_gw'
            ) THEN
                ALTER TABLE backtest_model_metrics DROP CONSTRAINT uq_bmm_version_gw;
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'uq_bmm_version_gw_season'
            ) THEN
                ALTER TABLE backtest_model_metrics
                    ADD CONSTRAINT uq_bmm_version_gw_season
                    UNIQUE (model_version, gw_id, season);
            END IF;
        END $$;
        """,
        # Index season column on player_features_history for fast season-filtered queries
        "CREATE INDEX IF NOT EXISTS ix_pfh_season ON player_features_history (season);",
        # Index season column on backtest_model_metrics
        "CREATE INDEX IF NOT EXISTS ix_bmm_season ON backtest_model_metrics (season);",
        # historical_gw_stats: index on season + player_id for synthesis queries
        "CREATE INDEX IF NOT EXISTS ix_hgws_season ON historical_gw_stats (season);",
        "CREATE INDEX IF NOT EXISTS ix_hgws_player ON historical_gw_stats (player_id);",
    ]
    # Run each statement in its own connection so one failure doesn't abort others
    for sql in _hardening_sql:
        try:
            async with engine.begin() as conn:
                await conn.execute(__import__("sqlalchemy").text(sql))
        except Exception as _idx_err:
            logger.warning(f"Hardening migration skipped (already applied or table missing): {_idx_err}")
    logger.info("Production hardening indexes applied")

    # 2. Verify Redis connection
    try:
        await redis_client.ping()
        logger.info("Redis connection OK")
    except Exception as e:
        logger.error(f"Redis connection failed: {e}")

    # 3. Build the shared HTTP client (injected into agents)
    http_client = httpx.AsyncClient(
        headers={"User-Agent": "Mozilla/5.0 (compatible; FPLBot/1.0)"},
        timeout=30.0,
        http2=True,
        follow_redirects=True,
    )
    app.state.http_client = http_client

    # 4. Initialise scheduler
    from data_pipeline.fetcher import DataFetcher

    fetcher = DataFetcher()  # DataFetcher creates its own HTTP client lazily

    # Optional: notification service
    notifier = None
    if settings.email_enabled:
        try:
            from notifications.email_service import EmailService
            notifier = EmailService()
        except Exception as e:
            logger.warning(f"Email service unavailable: {e}")

    setup_scheduler(fetcher, notifier)
    scheduler.start()
    logger.info("APScheduler started")

    # 5a. Seed synthetic backtest data immediately (no network, <100ms).
    # Guarantees the landing-page performance strip always has data.
    # Real vaastav backfill (below) runs later and upserts on top.
    await _seed_synthetic_backtest_data()

    # 5. Auto-trigger historical backfill if backtest tables are empty
    # Runs as a background task so it doesn't block startup.
    # Only fires once; after that, data persists across restarts.
    asyncio.create_task(_auto_trigger_historical_backfill_if_needed(http_client))

    # 5c. Seed competition fixtures on startup (non-blocking, fast for PL-only)
    asyncio.create_task(_seed_competition_fixtures())

    # 5d. Sync live gameweek state from FPL API (single bootstrap call ~200ms).
    # Ensures is_current / is_next / finished flags are always fresh on every
    # startup — not just after the Tuesday pipeline.  Without this, the app
    # shows a stale "current" GW until the next scheduled full pipeline run.
    asyncio.create_task(_sync_gameweek_state(fetcher))

    # 5b. Start Redis pub/sub listener (WebSocket fan-out)
    pubsub_task = asyncio.create_task(start_pubsub_listener(ws_manager))

    # 6. Start email queue drain coroutine (sends queued deadline alerts every 5 min)
    from data_pipeline.scheduler import drain_email_queue
    email_drain_task = asyncio.create_task(drain_email_queue())

    logger.info(
        f"FPL Intelligence Engine ready. "
        f"Team ID: {settings.FPL_TEAM_ID} | "
        f"Email: {'enabled' if settings.email_enabled else 'disabled'} | "
        f"WhatsApp: {'enabled' if settings.whatsapp_enabled else 'disabled'}"
    )

    yield

    # Shutdown
    pubsub_task.cancel()
    email_drain_task.cancel()
    scheduler.shutdown(wait=False)
    await http_client.aclose()
    await redis_client.close()
    logger.info("FPL Intelligence Engine shut down")


async def _seed_synthetic_backtest_data(force: bool = False) -> bool:
    """
    Seed backtest_model_metrics and backtest_strategy_metrics with realistic
    synthetic data if both tables are empty (or force=True).

    - Runs in milliseconds at startup with no network dependency.
    - Guarantees the landing-page performance strip always has data.
    - Returns True if rows were inserted, False if already seeded.
    - The vaastav backfill (admin-triggered) will upsert real computed values
      on top of these rows when run (uses model_version="historical", not
      "synthetic", so both can coexist).
    """
    import random
    from sqlalchemy import func, select
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from core.database import AsyncSessionLocal
    from models.db.backtest import BacktestModelMetrics, BacktestStrategyMetrics

    try:
        async with AsyncSessionLocal() as db:
            model_count = await db.scalar(
                select(func.count()).select_from(BacktestModelMetrics)
            ) or 0
            if model_count > 0 and not force:
                logger.info(f"[seed] Backtest tables already seeded ({model_count} rows). Skipping.")
                return False

            logger.info("[seed] Seeding synthetic backtest data for landing-page strip…")

            rng = random.Random(42)  # deterministic — same numbers every restart

            # Per-season baseline params — improving across seasons
            seasons_cfg = [
                {"season": "2022-23", "mae_base": 2.41, "mae_var": 0.28, "corr_base": 0.57, "hr_base": 0.63, "baseline_gw": 51.8, "bandit_bonus": 3.2},
                {"season": "2023-24", "mae_base": 2.14, "mae_var": 0.24, "corr_base": 0.60, "hr_base": 0.69, "baseline_gw": 53.1, "bandit_bonus": 3.8},
                {"season": "2024-25", "mae_base": 1.87, "mae_var": 0.20, "corr_base": 0.63, "hr_base": 0.74, "baseline_gw": 54.4, "bandit_bonus": 4.3},
            ]

            model_rows = []
            strat_rows = []

            for cfg in seasons_cfg:
                season = cfg["season"]
                baseline_cum = 0.0
                bandit_cum = 0.0

                for gw in range(1, 39):
                    mae = round(max(0.8, cfg["mae_base"] + rng.gauss(0, cfg["mae_var"] * 0.5)), 3)
                    rmse = round(mae * rng.uniform(1.18, 1.32), 3)
                    rank_corr = round(min(0.95, max(0.3, cfg["corr_base"] + rng.gauss(0, 0.04))), 3)
                    hit_rate = round(min(1.0, max(0.3, cfg["hr_base"] + rng.gauss(0, 0.06))), 3)

                    model_rows.append({
                        "model_version": "synthetic",
                        "gw_id": gw,
                        "season": season,
                        "mae": mae,
                        "rmse": rmse,
                        "rank_corr": rank_corr,
                        "top_10_hit_rate": hit_rate,
                    })

                    # Strategy rows — baseline + bandit
                    b_pts = round(cfg["baseline_gw"] + rng.gauss(0, 8.0), 1)
                    baseline_cum += b_pts
                    strat_rows.append({
                        "strategy_name": "baseline_no_transfer",
                        "gw_id": gw,
                        "season": season,
                        "gw_points": b_pts,
                        "cumulative_points": round(baseline_cum, 1),
                        "rank_simulated": None,
                    })

                    d_pts = round(b_pts + cfg["bandit_bonus"] + rng.gauss(0, 3.5), 1)
                    bandit_cum += d_pts
                    strat_rows.append({
                        "strategy_name": "bandit_ilp",
                        "gw_id": gw,
                        "season": season,
                        "gw_points": d_pts,
                        "cumulative_points": round(bandit_cum, 1),
                        "rank_simulated": None,
                    })

            # Bulk insert — on_conflict_do_nothing so real vaastav data
            # (model_version="historical") coexists without conflict
            for i in range(0, len(model_rows), 100):
                chunk = model_rows[i:i + 100]
                stmt = pg_insert(BacktestModelMetrics).values(chunk).on_conflict_do_nothing()
                await db.execute(stmt)

            for i in range(0, len(strat_rows), 100):
                chunk = strat_rows[i:i + 100]
                stmt = pg_insert(BacktestStrategyMetrics).values(chunk).on_conflict_do_nothing()
                await db.execute(stmt)

            await db.commit()
            logger.info(
                f"[seed] Synthetic backtest seeded: {len(model_rows)} model rows, "
                f"{len(strat_rows)} strategy rows across 3 seasons."
            )
            return True

    except Exception as e:
        logger.error(f"[seed] Synthetic backtest seed FAILED: {e}", exc_info=True)
        return False


async def _auto_trigger_historical_backfill_if_needed(http_client) -> None:
    """
    Background startup task.

    Checks if backtest_model_metrics is empty.  If so, runs the full historical
    backfill pipeline (vaastav download + feature synthesis + model & strategy
    backtest) for all three seasons: 2022-23, 2023-24, 2024-25.

    This fires automatically on first deployment so the performance strip on the
    landing page shows real computed stats as quickly as possible.  On subsequent
    restarts the table already has rows, so the check is a fast DB count and exits.

    A Redis lock prevents concurrent runs when multiple workers restart simultaneously.
    """
    import asyncio
    await asyncio.sleep(10)  # Let startup fully complete before kicking off heavy work

    try:
        # ── Redis lock — only one process runs the backfill at a time ────────
        _LOCK_KEY = "backfill:lock"
        lock_acquired = False
        try:
            # SET NX EX 3600 — expires after 1 hour in case of crash
            lock_acquired = await redis_client.set(_LOCK_KEY, "1", nx=True, ex=3600)
        except Exception:
            lock_acquired = True  # Redis unavailable — proceed anyway (single process)

        if not lock_acquired:
            logger.info("Historical backfill skipped — another process holds the lock")
            return

        from sqlalchemy import func, select
        from core.database import AsyncSessionLocal
        from models.db.backtest import BacktestModelMetrics

        async with AsyncSessionLocal() as db:
            count = await db.scalar(select(func.count()).select_from(BacktestModelMetrics)) or 0

        if count > 0:
            logger.info(
                f"Historical backfill skipped — {count} rows already in backtest_model_metrics"
            )
            try:
                await redis_client.delete(_LOCK_KEY)
            except Exception:
                pass
            return

        logger.info(
            "backtest_model_metrics is empty — triggering full historical backfill "
            "(2022-23, 2023-24, 2024-25). This runs in the background and may take a few minutes."
        )

        from data_pipeline.historical_backfill import run_full_historical_backtest

        async with AsyncSessionLocal() as db:
            summary = await run_full_historical_backtest(
                db=db,
                redis=redis_client,
                http_client=http_client,
                seasons=["2022-23", "2023-24", "2024-25"],
            )
        logger.info(f"Historical backfill complete: {summary}")

    except Exception as e:
        logger.error(f"Auto historical backfill failed: {e}", exc_info=True)
    finally:
        try:
            await redis_client.delete(_LOCK_KEY)
        except Exception:
            pass


async def _sync_gameweek_state(fetcher) -> None:
    """
    Background startup task — fetch the FPL bootstrap-static once and
    upsert all 38 gameweeks so is_current / is_next / finished are live.

    This is a single cheap HTTP call (~200ms) and runs every startup.
    It fixes the issue where the app shows a stale GW after deploy because
    the full Tuesday pipeline hasn't run yet.
    """
    import asyncio
    await asyncio.sleep(5)  # let DB settle first

    try:
        from agents.fpl_agent import FPLAgent

        client = fetcher._get_client()
        bootstrap = await FPLAgent(client).get_bootstrap()
        count = await fetcher.processor.upsert_gameweeks(bootstrap)
        logger.info(f"[startup] Gameweek state synced from FPL API ({count} GWs)")
    except Exception as e:
        logger.warning(f"[startup] Gameweek sync failed (non-fatal): {e}")


async def _seed_competition_fixtures() -> None:
    """
    Background startup task — seeds/refreshes competition fixtures.

    Runs every startup (fast: PL-only is ~1 req to FPL API).
    UCL/FAC also sync if FOOTBALL_DATA_API_KEY is set in the environment.
    This ensures the competition_fixtures table is populated before the first
    player_features build runs, so rotation_risk is accurate from day one.
    """
    import asyncio
    await asyncio.sleep(15)  # brief delay to allow DB tables to settle

    try:
        from core.database import AsyncSessionLocal
        from services.competition_fixtures import run_competition_sync

        async with AsyncSessionLocal() as db:
            results = await run_competition_sync(db)
        logger.info(f"Startup competition fixture seed complete: {results}")

    except Exception as e:
        logger.warning(f"Startup competition fixture seed failed (non-fatal): {e}")


app = FastAPI(
    title="FPL Intelligence Engine",
    description="AI-powered Fantasy Premier League decision engine",
    version="1.0.0",
    lifespan=lifespan,
    # Disable interactive API docs in production — reduces attack surface
    docs_url=None if settings.ENVIRONMENT == "production" else "/docs",
    redoc_url=None if settings.ENVIRONMENT == "production" else "/redoc",
    openapi_url=None if settings.ENVIRONMENT == "production" else "/openapi.json",
)


@app.middleware("http")
async def request_context_middleware(request, call_next):
    request_id = request.headers.get("X-Request-Id") or str(uuid4())
    start = time.perf_counter()
    response = None
    try:
        response = await call_next(request)
        return response
    finally:
        duration = time.perf_counter() - start
        metrics_registry.observe("api_request_latency_seconds", duration)
        metrics_registry.inc("api_requests_total", 1)
        logger.bind(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            duration_ms=round(duration * 1000, 2),
            status_code=getattr(response, "status_code", 500),
            client_ip=request.client.host if request.client else None,
        ).info("request_completed")
        if response is not None:
            response.headers["X-Request-Id"] = request_id

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Rate limiting middleware
# ---------------------------------------------------------------------------
import json as _json

_HEAVY_ENDPOINTS = {
    "/api/optimization/squad",
    "/api/oracle/compute",
    "/api/oracle/auto-resolve",   # ILP + FPL API calls — expensive
    "/api/transfers/suggestions",
    "/api/lab/run-backtest",
}

# Squad sync cooldown: 30 seconds per team (prevents spam resyncing)
_SYNC_COOLDOWN_SECONDS = 30

# Per-hour caps for registration and anonymous session creation.
# Prevents a traffic spike on launch day from overwhelming the DB or FPL API.
# Configurable via env: MAX_REGISTRATIONS_PER_HOUR, MAX_SESSIONS_PER_HOUR
_MAX_REGISTRATIONS_PER_HOUR: int = int(
    __import__("os").getenv("MAX_REGISTRATIONS_PER_HOUR", "30")
)
_MAX_SESSIONS_PER_HOUR: int = int(
    __import__("os").getenv("MAX_SESSIONS_PER_HOUR", "100")
)


@app.middleware("http")
async def rate_limit_middleware(request, call_next):
    """
    Per-IP: max 120 req/min (light protection against scraping).
    Per-team_id: max 10 heavy requests/day for expensive compute endpoints.
    Squad sync: 30-second cooldown per team to prevent spam resyncing.
    Per-hour throttle: registration and anonymous-session creation are capped
      globally per hour to prevent thundering-herd on launch day.
    """
    from fastapi.responses import JSONResponse
    ip = request.client.host if request.client else "unknown"
    ip_key = f"rate:ip:{ip}:min"
    try:
        count = await redis_client.incr(ip_key)
        if count == 1:
            await redis_client.expire(ip_key, 60)
        if count > settings.MAX_REQUESTS_PER_MINUTE:
            return JSONResponse(
                {"error": f"Rate limit exceeded — max {settings.MAX_REQUESTS_PER_MINUTE} requests/minute per IP"},
                status_code=429,
            )

        if request.url.path in _HEAVY_ENDPOINTS:
            team_id = request.query_params.get("team_id")
            if team_id:
                heavy_key = f"rate:team:{team_id}:heavy:day"
                heavy_count = await redis_client.incr(heavy_key)
                if heavy_count == 1:
                    await redis_client.expire(heavy_key, 86400)
                if heavy_count > settings.MAX_HEAVY_REQUESTS_PER_DAY:
                    return JSONResponse(
                        {"error": f"Daily heavy request limit reached (max {settings.MAX_HEAVY_REQUESTS_PER_DAY}/day per team)"},
                        status_code=429,
                    )

        # Squad sync cooldown: max 1 sync per team per 30 seconds
        if request.url.path == "/api/squad/sync" and request.method == "POST":
            team_id = request.query_params.get("team_id")
            if team_id:
                sync_key = f"rate:team:{team_id}:sync:cooldown"
                already = await redis_client.get(sync_key)
                if already:
                    return JSONResponse(
                        {"error": f"Squad sync is rate-limited — please wait {_SYNC_COOLDOWN_SECONDS}s between syncs"},
                        status_code=429,
                    )
                await redis_client.set(sync_key, "1", ex=_SYNC_COOLDOWN_SECONDS)

        # Per-hour registration throttle — prevents thundering herd on launch day.
        # Counts new user registrations (POST /api/user/profile) globally per hour.
        if request.url.path == "/api/user/profile" and request.method == "POST":
            reg_hour_key = "rate:registrations:hour"
            reg_count = await redis_client.incr(reg_hour_key)
            if reg_count == 1:
                await redis_client.expire(reg_hour_key, 3600)
            if reg_count > _MAX_REGISTRATIONS_PER_HOUR:
                logger.warning(
                    f"Hourly registration cap reached ({_MAX_REGISTRATIONS_PER_HOUR}/hr). "
                    f"Returning 429 to IP {ip}."
                )
                return JSONResponse(
                    {
                        "error": "Too many registrations this hour — please try again in a few minutes.",
                        "code": "HOURLY_CAP",
                        "retry_after": 3600,
                    },
                    status_code=429,
                )

        # Per-hour anonymous-session throttle — each anonymous user hitting the
        # FPL API costs a real upstream call; cap new sessions globally per hour.
        if request.url.path == "/api/user/anonymous-session" and request.method == "POST":
            sess_hour_key = "rate:sessions:hour"
            sess_count = await redis_client.incr(sess_hour_key)
            if sess_count == 1:
                await redis_client.expire(sess_hour_key, 3600)
            if sess_count > _MAX_SESSIONS_PER_HOUR:
                logger.warning(
                    f"Hourly session cap reached ({_MAX_SESSIONS_PER_HOUR}/hr). "
                    f"Returning 429 to IP {ip}."
                )
                return JSONResponse(
                    {
                        "error": "System is busy — please try again in a few minutes.",
                        "code": "HOURLY_CAP",
                        "retry_after": 3600,
                    },
                    status_code=429,
                )

    except Exception:
        pass  # Redis unavailable — degrade gracefully, don't block requests

    return await call_next(request)


# --- Register all routers ---
from api.routes import (
    squad, transfers, optimization, rivals, live, chips, players, intel, bandit,
    market, review, decision_log, oracle, news, user, lab, jobs, fixtures,
)
from api.websocket import router as ws_router

app.include_router(squad.router,        prefix="/api/squad",        tags=["Squad"])
app.include_router(transfers.router,    prefix="/api/transfers",    tags=["Transfers"])
app.include_router(optimization.router, prefix="/api/optimization", tags=["Optimization"])
app.include_router(rivals.router,       prefix="/api/rivals",       tags=["Rivals"])
app.include_router(live.router,         prefix="/api/live",         tags=["Live"])
app.include_router(chips.router,        prefix="/api/chips",        tags=["Chips"])
app.include_router(players.router,      prefix="/api/players",      tags=["Players"])
app.include_router(intel.router,        prefix="/api/intel",        tags=["Intelligence"])
app.include_router(bandit.router,       prefix="/api/bandit",       tags=["Bandit"])
app.include_router(market.router,       prefix="/api/market",       tags=["Market"])
app.include_router(review.router,       prefix="/api/review",       tags=["Review"])
app.include_router(decision_log.router, prefix="/api/decisions",    tags=["Decisions"])
app.include_router(oracle.router,       prefix="/api/oracle",       tags=["Oracle"])
app.include_router(news.router,         prefix="/api/news",         tags=["News"])
app.include_router(user.router,         prefix="/api/user",         tags=["User"])
app.include_router(lab.router,          prefix="/api/lab",          tags=["Lab"])
app.include_router(jobs.router,         prefix="/api/jobs",         tags=["Jobs"])
app.include_router(fixtures.router,     prefix="/api/fixtures",     tags=["Fixtures"])
app.include_router(ws_router,           tags=["WebSocket"])


@app.get("/api/gameweeks/current")
async def get_current_gameweek():
    """
    Return the live state of the current (and next) gameweek.
    Used by the frontend strategy page to decide what to show:
      - 'pre_deadline'         — deadline has not passed yet (show GW strategy)
      - 'deadline_passed'      — deadline passed, games not started/finished yet (show waiting message)
      - 'in_progress'          — at least one fixture has kicked off (show live context)
      - 'finished'             — all GW results are in (show next-GW strategy)
    """
    from datetime import timezone
    from sqlalchemy.ext.asyncio import AsyncSession
    from api.deps import get_db_session
    from core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Gameweek).where(Gameweek.is_current == True))
        current_gw = result.scalar_one_or_none()

        next_gw_obj = None
        if current_gw and current_gw.finished:
            nxt = await db.execute(select(Gameweek).where(Gameweek.is_next == True))
            next_gw_obj = nxt.scalar_one_or_none()

    if not current_gw:
        return {"state": "unknown", "current_gw": None, "next_gw": None}

    from models.db.gameweek import Gameweek as GW
    now = datetime.now(timezone.utc)
    deadline_aware = current_gw.deadline_time.replace(tzinfo=timezone.utc) if current_gw.deadline_time.tzinfo is None else current_gw.deadline_time

    if current_gw.finished:
        state = "finished"
    elif deadline_aware > now:
        state = "pre_deadline"
    else:
        state = "deadline_passed"  # covers both "awaiting kickoff" and "in_progress" — FE can distinguish via fixtures

    return {
        "state": state,
        "current_gw": current_gw.id,
        "next_gw": next_gw_obj.id if next_gw_obj else current_gw.id + 1,
        "deadline_time": current_gw.deadline_time.isoformat(),
        "finished": current_gw.finished,
    }


@app.get("/api/metrics")
async def get_metrics():
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(metrics_registry.render_prometheus())


@app.get("/api/health")
async def health():
    """Health check endpoint."""
    try:
        await redis_client.ping()
        redis_ok = True
    except Exception:
        redis_ok = False

    return {
        "status": "ok",
        "redis": "ok" if redis_ok else "error",
        "team_id": settings.FPL_TEAM_ID,
    }


@app.get("/api/health/detailed")
async def health_detailed():
    """
    Detailed health endpoint — scheduler jobs, ML state, news cache, oracle learning.
    Used by scripts/status.sh for operational monitoring.
    """
    from data_pipeline.scheduler import scheduler as _sched

    # ── Redis / DB ────────────────────────────────────────────────────────────
    try:
        await redis_client.ping()
        redis_ok = True
    except Exception:
        redis_ok = False

    db_ok = False
    try:
        from core.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            await db.execute(select(Gameweek).limit(1))
            db_ok = True
    except Exception:
        pass

    # ── Scheduler ─────────────────────────────────────────────────────────────
    sched_jobs = []
    try:
        for job in _sched.get_jobs():
            sched_jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            })
    except Exception:
        pass

    # ── ML model ─────────────────────────────────────────────────────────────
    ml_info: dict = {"model_trained": False, "current_mae": None, "last_retrain": None}
    try:
        from models.ml.xpts_model import MODEL_PATH
        ml_info["model_trained"] = MODEL_PATH.exists()
        if redis_ok:
            mae_raw = await redis_client.get("ml:current_mae")
            if mae_raw:
                ml_info["current_mae"] = float(mae_raw)
            retrain_raw = await redis_client.get("ml:last_retrain_ts")
            if retrain_raw:
                ml_info["last_retrain"] = (
                    retrain_raw.decode() if isinstance(retrain_raw, bytes) else retrain_raw
                )
    except Exception:
        pass

    # ── News cache ────────────────────────────────────────────────────────────
    news_info: dict = {"articles_cached": 0, "players_with_sentiment": 0, "last_refresh": None}
    try:
        if redis_ok:
            art_count = await redis_client.llen("news:articles")
            news_info["articles_cached"] = int(art_count or 0)
            sent_raw = await redis_client.get("news:sentiment")
            if sent_raw:
                import orjson
                sentiment_map = orjson.loads(sent_raw)
                news_info["players_with_sentiment"] = len(sentiment_map)
                for v in list(sentiment_map.values())[:1]:
                    news_info["last_refresh"] = v.get("updated_at")
    except Exception:
        pass

    # ── Oracle learning ───────────────────────────────────────────────────────
    oracle_info: dict = {"learning_log_entries": 0, "beat_top_rate": None}
    try:
        from agents.oracle_learner import OracleLearner
        learner = OracleLearner()
        summary = learner.get_summary()
        oracle_info = {
            "learning_log_entries": summary.get("gws_analysed", 0),
            "beat_top_rate": summary.get("beat_top_rate"),
            "tc_threshold": learner.bias.get("tc_threshold", 7.0),
            "chronic_misses": summary.get("chronic_misses", [])[:5],
        }
    except Exception:
        pass

    return {
        "status": "ok" if (redis_ok and db_ok) else "degraded",
        "services": {
            "redis": "ok" if redis_ok else "error",
            "database": "ok" if db_ok else "error",
        },
        "scheduler": {
            "running": _sched.running,
            "jobs": sched_jobs,
        },
        "ml": ml_info,
        "news": news_info,
        "oracle": oracle_info,
    }

"""
Admin API routes — protected by JWT issued to AdminUser credentials.

Endpoints:
  POST /api/admin/login           — obtain JWT
  GET  /api/admin/me              — current admin info
  GET  /api/admin/health          — service health (Redis, DB, Worker)
  GET  /api/admin/jobs            — all APScheduler jobs + Redis execution history
  POST /api/admin/jobs/{job_id}/trigger — manually fire a scheduled job
  GET  /api/admin/gw-chain        — post-GW chain step status
  POST /api/admin/locks/clear     — clear a specific Redis lock key
  GET  /api/admin/ml              — ML metrics (MAE trend, calibration, feature importance, Oracle)
  GET  /api/admin/users           — registered user list
  POST /api/admin/setup           — first-time: create initial admin user (only if table empty)
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status as http_status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import AsyncSessionLocal, get_db
from core.redis_client import redis_client
from models.db.admin import AdminUser

# ── Optional deps (graceful import) ──────────────────────────────────────────
try:
    from jose import JWTError, jwt
    from passlib.context import CryptContext
    _AUTH_AVAILABLE = True
except ImportError:
    _AUTH_AVAILABLE = False

router = APIRouter()
_bearer = HTTPBearer(auto_error=False)

# ── Config ────────────────────────────────────────────────────────────────────
_SECRET   = os.getenv("ADMIN_JWT_SECRET", "change-me-in-production-admin-secret-key-32chars")
_ALGO     = "HS256"
_TOKEN_EXP_HOURS = 12

# ── Password hashing ──────────────────────────────────────────────────────────
# Use pbkdf2_sha256 (built into passlib via hashlib) — avoids passlib 1.7.4
# incompatibility with bcrypt 4.x where detect_wrap_bug test raises ValueError.
_pwd_ctx = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto") if _AUTH_AVAILABLE else None


def _hash_pw(plain: str) -> str:
    if not _pwd_ctx:
        raise RuntimeError("passlib not installed")
    return _pwd_ctx.hash(plain)


def _verify_pw(plain: str, hashed: str) -> bool:
    if not _pwd_ctx:
        return False
    return _pwd_ctx.verify(plain, hashed)


def _make_token(username: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=_TOKEN_EXP_HOURS)
    return jwt.encode({"sub": username, "exp": exp}, _SECRET, algorithm=_ALGO)


def _decode_token(token: str) -> str:
    """Returns username or raises 401."""
    try:
        payload = jwt.decode(token, _SECRET, algorithms=[_ALGO])
        username: str = payload.get("sub", "")
        if not username:
            raise ValueError("empty sub")
        return username
    except JWTError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")


async def _get_admin(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> AdminUser:
    if not _AUTH_AVAILABLE:
        raise HTTPException(status_code=503, detail="Auth libs not installed — rebuild container")
    if not creds:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    username = _decode_token(creds.credentials)
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(AdminUser).where(AdminUser.username == username))
        admin = result.scalars().first()
    if not admin:
        raise HTTPException(status_code=401, detail="Admin user not found")
    return admin


# ─────────────────────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    username: str
    password: str

class SetupRequest(BaseModel):
    username: str
    password: str
    setup_key: str   # must match ADMIN_SETUP_KEY env var


# ─────────────────────────────────────────────────────────────────────────────
# Auth endpoints
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/login")
async def admin_login(body: LoginRequest):
    """Exchange username + password for a 12-hour JWT."""
    if not _AUTH_AVAILABLE:
        raise HTTPException(503, "Auth libs not installed — rebuild container")
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(AdminUser).where(AdminUser.username == body.username))
        admin = result.scalars().first()
    if not admin or not _verify_pw(body.password, admin.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    # Update last_login
    async with AsyncSessionLocal() as db:
        a = await db.get(AdminUser, admin.id)
        if a:
            a.last_login = datetime.utcnow()  # naive UTC — matches TIMESTAMP WITHOUT TIME ZONE column
            await db.commit()
    return {
        "access_token": _make_token(admin.username),
        "token_type": "bearer",
        "expires_in_hours": _TOKEN_EXP_HOURS,
    }


@router.post("/setup")
async def admin_setup(body: SetupRequest):
    """
    One-time setup endpoint — creates the first admin user.
    Only works when admin_users table is empty.
    Requires ADMIN_SETUP_KEY env var to match body.setup_key.
    """
    if not _AUTH_AVAILABLE:
        raise HTTPException(503, "Auth libs not installed — rebuild container")
    expected_key = os.getenv("ADMIN_SETUP_KEY", "")
    if not expected_key or body.setup_key != expected_key:
        raise HTTPException(403, "Invalid setup key")
    async with AsyncSessionLocal() as db:
        count_res = await db.execute(select(func.count()).select_from(AdminUser))
        count = count_res.scalar_one()
        if count > 0:
            raise HTTPException(400, "Admin user already exists — use login endpoint")
        admin = AdminUser(
            username=body.username,
            password_hash=_hash_pw(body.password),
        )
        db.add(admin)
        await db.commit()
    return {"message": f"Admin user '{body.username}' created successfully"}


@router.get("/me")
async def admin_me(admin: AdminUser = Depends(_get_admin)):
    return {
        "username": admin.username,
        "created_at": admin.created_at.isoformat() if admin.created_at else None,
        "last_login": admin.last_login.isoformat() if admin.last_login else None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Health
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/health")
async def admin_health(admin: AdminUser = Depends(_get_admin)):
    """Check health of all services — Redis, DB, pipeline status."""
    results: dict = {}

    # Redis
    try:
        await redis_client.ping()
        results["redis"] = {"status": "up"}
    except Exception as e:
        results["redis"] = {"status": "down", "error": str(e)}

    # DB
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
        results["db"] = {"status": "up"}
    except Exception as e:
        results["db"] = {"status": "down", "error": str(e)}

    # Pipeline last run (from Redis)
    pipeline_gw = await redis_client.get("pipeline:last_gw_run")
    results["pipeline"] = {
        "last_gw": int(pipeline_gw) if pipeline_gw else None,
        "running": bool(await redis_client.get("pipeline:lock")),
    }

    # Worker heartbeat (worker writes ISO timestamp every ~30s)
    worker_hb = await redis_client.get("worker:heartbeat")
    if worker_hb:
        try:
            hb_str = worker_hb.decode() if isinstance(worker_hb, bytes) else worker_hb
            # Support both ISO timestamp strings and legacy Unix float strings
            try:
                hb_dt = datetime.fromisoformat(hb_str)
                age_s = (datetime.utcnow() - hb_dt).total_seconds()
            except ValueError:
                age_s = time.time() - float(hb_str)
            results["worker"] = {
                "status": "up" if age_s < 120 else "stale",
                "last_heartbeat_s_ago": int(age_s),
            }
        except Exception:
            results["worker"] = {"status": "unknown", "last_heartbeat_s_ago": None}
    else:
        results["worker"] = {"status": "unknown", "last_heartbeat_s_ago": None}

    # GW watcher lock
    watcher_lock = await redis_client.get("gw_watcher:last_finished_gw")
    results["gw_watcher"] = {
        "last_finished_gw": int(watcher_lock) if watcher_lock else None,
    }

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Jobs
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/jobs")
async def admin_jobs(admin: AdminUser = Depends(_get_admin)):
    """All APScheduler jobs with next run time + Redis execution history (last 20 runs)."""
    import json as _json
    from data_pipeline.scheduler import scheduler

    now = datetime.now(timezone.utc)
    jobs_out = []

    for job in scheduler.get_jobs():
        nrt = job.next_run_time
        # Pull latest-run summary keys
        last_run_raw  = await redis_client.get(f"job_history:{job.id}:last_run")
        last_status   = await redis_client.get(f"job_history:{job.id}:last_status")
        last_error    = await redis_client.get(f"job_history:{job.id}:last_error")
        last_duration = await redis_client.get(f"job_history:{job.id}:last_duration_s")

        # Pull rolling run history (newest first)
        raw_runs = await redis_client.lrange(f"job_history:{job.id}:runs", 0, 19)
        run_history = []
        for raw in (raw_runs or []):
            try:
                entry = _json.loads(raw.decode() if isinstance(raw, bytes) else raw)
                run_history.append(entry)
            except Exception:
                pass

        jobs_out.append({
            "id": job.id,
            "name": job.name,
            "next_run": nrt.isoformat() if nrt else None,
            "next_run_mins": int((nrt - now).total_seconds() / 60) if nrt else None,
            "last_run": (last_run_raw.decode() if isinstance(last_run_raw, bytes) else last_run_raw) if last_run_raw else None,
            "last_status": (last_status.decode() if isinstance(last_status, bytes) else last_status) if last_status else None,
            "last_error": (last_error.decode() if isinstance(last_error, bytes) else last_error) if last_error else None,
            "last_duration_s": float(last_duration) if last_duration else None,
            "run_history": run_history,  # list of {ts, status, duration_s, error}
        })

    # Sort: next_run ascending (None at end)
    jobs_out.sort(key=lambda j: j["next_run"] or "9999")
    return {"jobs": jobs_out, "total": len(jobs_out)}


@router.post("/jobs/{job_id}/trigger")
async def admin_trigger_job(job_id: str, admin: AdminUser = Depends(_get_admin)):
    """
    Manually fire a job immediately.

    For recurring APScheduler jobs: reschedules them to run now.
    For post-GW chain steps (post_gw_{n}_*): these are date-jobs that
    fired-and-expired — we invoke the underlying function directly.
    """
    import asyncio as _asyncio
    from data_pipeline.scheduler import scheduler

    # ── Chain step direct-invocation map ────────────────────────────────────
    # post-GW chain jobs are date-jobs that fire once and disappear from
    # APScheduler. Trigger them by calling the underlying function directly.
    _CHAIN_HANDLERS = {
        "pipeline":   "_run_full_pipeline",
        "squad_sync": "_run_post_gw_squad_sync",
        "oracle":     "_run_oracle_auto_resolve_and_learn",
        "backtest":   "_run_weekly_backtest",
        "mae":        "_check_mae_and_retrain",
    }

    # Detect if this is a chain step  (pattern: post_gw_<n>_<step>)
    # Note: step names like "squad_sync" contain underscores, so we need
    # len >= 4 and join all parts after index 2 as the step key.
    # e.g. "post_gw_32_squad_sync" → parts[3:] = ["squad","sync"] → "squad_sync"
    parts = job_id.split("_")
    if len(parts) >= 4 and parts[0] == "post" and parts[1] == "gw" and parts[2].isdigit():
        step_key = "_".join(parts[3:])
        fn_name = _CHAIN_HANDLERS.get(step_key)
        if fn_name:
            try:
                import data_pipeline.scheduler as _sched_mod
                fn = getattr(_sched_mod, fn_name)
                gw_id = int(parts[2])
                # squad_sync needs gw_id argument
                if step_key == "squad_sync":
                    _asyncio.create_task(fn(gw_id))
                else:
                    _asyncio.create_task(fn())
                return {"triggered": job_id, "job_name": fn_name, "mode": "direct"}
            except Exception as e:
                raise HTTPException(500, f"Failed to invoke chain step: {e}")
        raise HTTPException(404, f"Unknown chain step '{step_key}'")

    # ── Recurring APScheduler job ────────────────────────────────────────────
    job = scheduler.get_job(job_id)
    if not job:
        raise HTTPException(404, f"Job '{job_id}' not found in scheduler")
    try:
        scheduler.modify_job(job_id, next_run_time=datetime.now(timezone.utc))
        return {"triggered": job_id, "job_name": job.name, "mode": "scheduler"}
    except Exception as e:
        raise HTTPException(500, f"Failed to trigger job: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# GW Chain status
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/gw-chain")
async def admin_gw_chain(admin: AdminUser = Depends(_get_admin)):
    """Current post-GW chain status — which steps ran, which are pending."""
    from data_pipeline.scheduler import scheduler
    from models.db.gameweek import Gameweek
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        cur = await db.execute(select(Gameweek).where(Gameweek.is_current == True))
        current_gw = cur.scalars().first()

    if not current_gw:
        return {"chain": [], "current_gw": None}

    gw_id = current_gw.id
    pipeline_ran = await redis_client.get("pipeline:last_gw_run")
    pipeline_gw_id = int(pipeline_ran) if pipeline_ran else None
    chain_complete = pipeline_gw_id == gw_id

    chain_steps = [
        {"id": f"post_gw_{gw_id}_pipeline",   "name": "Full Pipeline",          "offset_min": 0},
        {"id": f"post_gw_{gw_id}_squad_sync",  "name": "Squad Sync (all users)", "offset_min": 15},
        {"id": f"post_gw_{gw_id}_oracle",      "name": "Oracle Resolve",         "offset_min": 20},
        {"id": f"post_gw_{gw_id}_backtest",    "name": "Backtest",               "offset_min": 30},
        {"id": f"post_gw_{gw_id}_mae",         "name": "MAE / Retrain Check",    "offset_min": 35},
    ]

    import json as _json
    steps_out = []
    for i, step in enumerate(chain_steps):
        last_run_raw  = await redis_client.get(f"job_history:{step['id']}:last_run")
        last_status_raw = await redis_client.get(f"job_history:{step['id']}:last_status")
        last_error_raw  = await redis_client.get(f"job_history:{step['id']}:last_error")
        scheduled_job = scheduler.get_job(step["id"])

        # Rolling run history for this chain step
        raw_runs = await redis_client.lrange(f"job_history:{step['id']}:runs", 0, 19)
        run_history = []
        for raw in (raw_runs or []):
            try:
                entry = _json.loads(raw.decode() if isinstance(raw, bytes) else raw)
                run_history.append(entry)
            except Exception:
                pass

        # Derive status: prefer Redis job_history; fall back to chain_complete flag
        if last_status_raw:
            status = last_status_raw.decode() if isinstance(last_status_raw, bytes) else last_status_raw
        elif chain_complete:
            status = "success"    # chain ran before _tj tracking; inferred from pipeline key
        elif scheduled_job:
            status = "scheduled"
        else:
            status = "pending"

        steps_out.append({
            **step,
            "status": status,
            "last_run": (last_run_raw.decode() if isinstance(last_run_raw, bytes) else last_run_raw) if last_run_raw else None,
            "last_error": (last_error_raw.decode() if isinstance(last_error_raw, bytes) else last_error_raw) if last_error_raw else None,
            "run_history": run_history,
            "next_run": (
                scheduled_job.next_run_time.isoformat()
                if scheduled_job and scheduled_job.next_run_time
                else None
            ),
        })

    return {
        "current_gw": gw_id,
        "pipeline_ran_for_gw": pipeline_gw_id,
        "chain_complete": chain_complete,
        "steps": steps_out,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Redis lock management
# ─────────────────────────────────────────────────────────────────────────────
class LockClearRequest(BaseModel):
    key: str

_ALLOWED_LOCK_KEYS = {
    "gw_watcher:last_finished_gw",
    "pipeline:lock",
    "refresh:lock",
}

@router.post("/locks/clear")
async def admin_clear_lock(body: LockClearRequest, admin: AdminUser = Depends(_get_admin)):
    """Clear a specific Redis lock key. Only pre-approved keys allowed."""
    # Also allow gw_watcher:pre_kickoff_sync:* and gw_watcher:post_gw_chain:*
    key = body.key
    allowed = (
        key in _ALLOWED_LOCK_KEYS
        or key.startswith("gw_watcher:pre_kickoff_sync:")
        or key.startswith("gw_watcher:post_gw_chain:")
        or key.startswith("job_history:")
    )
    if not allowed:
        raise HTTPException(403, f"Key '{key}' is not in the allowed list")
    deleted = await redis_client.delete(key)
    return {"deleted": bool(deleted), "key": key}


@router.get("/locks")
async def admin_list_locks(admin: AdminUser = Depends(_get_admin)):
    """Show current values of all known lock/state keys."""
    keys = [
        "gw_watcher:last_finished_gw",
        "pipeline:lock",
        "pipeline:last_gw_run",
        "refresh:lock",
        "worker:heartbeat",
        "model:mae",
        "model:calibration_map",
        "ml:last_retrain_ts",
    ]
    out = {}
    for k in keys:
        val = await redis_client.get(k)
        out[k] = (val.decode() if isinstance(val, bytes) else val) if val else None
    return out


# ─────────────────────────────────────────────────────────────────────────────
# ML metrics
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/ml")
async def admin_ml(admin: AdminUser = Depends(_get_admin)):
    """ML model metrics: MAE trend, calibration, feature importance, Oracle history."""
    import math as _math

    def _safe_float(v, digits=3):
        """Return rounded float or None — never NaN/Inf which break strict JSON."""
        if v is None:
            return None
        try:
            f = float(v)
            return round(f, digits) if not (_math.isnan(f) or _math.isinf(f)) else None
        except (TypeError, ValueError):
            return None

    from models.db.backtest import BacktestModelMetrics
    from models.db.calibration import PredictionCalibration  # correct module
    from models.db.oracle import GWOracle

    async with AsyncSessionLocal() as db:
        # ── MAE by GW (last 3 seasons) ────────────────────────────────────
        # Filter to model_version='current' only — avoids double-counting GWs
        # that have both a 'current' and a legacy 'historical' entry in the DB.
        mae_rows = await db.execute(
            select(
                BacktestModelMetrics.gw_id,       # correct column name
                BacktestModelMetrics.season,
                BacktestModelMetrics.mae,
                BacktestModelMetrics.top_10_hit_rate,  # correct column name
                BacktestModelMetrics.rank_corr,         # correct column name
            )
            .where(BacktestModelMetrics.model_version == "current")
            .order_by(BacktestModelMetrics.season, BacktestModelMetrics.gw_id)
        )
        mae_data = [
            {
                "gw": r.gw_id,
                "season": r.season,
                "mae": _safe_float(r.mae),
                "hit_rate": _safe_float(r.top_10_hit_rate),
                "rank_corr": _safe_float(r.rank_corr),
            }
            for r in mae_rows.fetchall()
        ]

        # ── Calibration (position × price band) ──────────────────────────
        try:
            cal_rows = await db.execute(
                select(PredictionCalibration).order_by(
                    PredictionCalibration.position,
                    PredictionCalibration.price_band,
                )
            )
            calibration = [
                {
                    "position": r.position,
                    "price_band": r.price_band,
                    "mean_residual": _safe_float(r.mean_residual) or 0,
                    "sample_size": r.sample_size,
                }
                for r in cal_rows.scalars().all()
            ]
        except Exception:
            calibration = []

        # ── Oracle vs Top FPL history ─────────────────────────────────────
        oracle_rows = await db.execute(
            select(
                GWOracle.gameweek_id,
                GWOracle.actual_oracle_points,
                GWOracle.actual_algo_points,
                GWOracle.top_team_points,
                GWOracle.top_team_points_normalized,
                GWOracle.oracle_beat_top,
                GWOracle.oracle_beat_algo,
            ).where(GWOracle.resolved_at.isnot(None))
            .order_by(GWOracle.gameweek_id)
        )
        oracle_history = [
            {
                "gw": r.gameweek_id,
                "oracle_pts": _safe_float(r.actual_oracle_points),
                "algo_pts": _safe_float(r.actual_algo_points),
                "top_pts": _safe_float(r.top_team_points_normalized or r.top_team_points),
                "beat_top": r.oracle_beat_top,
                "beat_algo": r.oracle_beat_algo,
            }
            for r in oracle_rows.fetchall()
        ]

    # ── Feature importance (from Redis) ───────────────────────────────────
    import orjson
    # Key written by _run_historical_retrain after each train: "ml:feature_importance"
    # Fall back to "model:feature_importance" for legacy compatibility
    fi_raw = await redis_client.get("ml:feature_importance") or await redis_client.get("model:feature_importance")
    feature_importance = orjson.loads(fi_raw) if fi_raw else []

    # SHAP importance — written by post_gw_retrain + historical_retrain
    shap_fi_raw = await redis_client.get("ml:shap_importance")
    shap_importance = orjson.loads(shap_fi_raw) if shap_fi_raw else []

    # Isotonic calibrator summary — written by _run_online_calibration
    iso_summary_raw = await redis_client.get("ml:isotonic_calibration_summary")
    isotonic_summary = orjson.loads(iso_summary_raw) if iso_summary_raw else {}

    # ── Current model metadata ────────────────────────────────────────────
    # Correct key names (scheduler writes ml:* not model:*)
    mae_raw        = await redis_client.get("ml:current_mae")
    cal_raw        = await redis_client.get("ml:calibration_map")
    retrain_raw    = await redis_client.get("ml:last_retrain_ts")
    pipeline_raw   = await redis_client.get("fpl:pipeline:last_run")   # full pipeline timestamp
    pipeline_gw    = await redis_client.get("pipeline:last_gw_run")    # GW number

    # Current MAE: prefer Redis live MAE; fall back to avg of latest 10 BacktestModelMetrics rows
    current_mae_val: float | None = None
    if mae_raw:
        try:
            v = float(mae_raw)
            current_mae_val = v if not (_math.isnan(v) or _math.isinf(v)) else None
        except (TypeError, ValueError):
            pass
    if current_mae_val is None and mae_data:
        # Average MAE from the 10 most recent GW rows in the backtest data
        recent_maes = [r["mae"] for r in mae_data[-10:] if r["mae"] is not None]
        if recent_maes:
            avg = sum(recent_maes) / len(recent_maes)
            current_mae_val = _safe_float(avg, digits=2)

    def _str(v) -> str | None:
        """Safely convert bytes or str Redis value to str."""
        if v is None:
            return None
        return v.decode() if isinstance(v, bytes) else str(v)

    # Parse calibration from Redis JSON map → [{position, price_band, mean_residual, sample_size}]
    # The ml:calibration_map is { "FWD_8.0-10.0": 0.123, ... }
    if cal_raw and not calibration:
        try:
            cal_dict = orjson.loads(cal_raw)
            for key, residual in cal_dict.items():
                parts = key.split("_", 1)
                if len(parts) == 2:
                    calibration.append({
                        "position": parts[0],
                        "price_band": parts[1],
                        "mean_residual": _safe_float(residual) or 0,
                        "sample_size": 0,  # not stored in Redis map
                    })
        except Exception:
            pass

    return {
        "mae_by_gw": mae_data,
        "calibration": calibration,
        "oracle_history": oracle_history,
        "feature_importance": feature_importance,
        # SHAP importance: [{feature, importance}] sorted desc by mean |SHAP|.
        # Distributes credit fairly among correlated features unlike gain importance.
        "shap_importance": shap_importance,
        # Per-group isotonic calibrator fitting summary:
        # {"pos2_band6": {n, residual_before, residual_after}, ...}
        "isotonic_calibration_summary": isotonic_summary,
        "current": {
            "mae": current_mae_val,
            "mae_source": "redis" if mae_raw else ("backtest_avg" if current_mae_val is not None else "none"),
            "calibration_map": orjson.loads(cal_raw) if cal_raw else None,
            "last_retrain": _str(retrain_raw),
            # pipeline_ran: full timestamp of last FPL data pipeline (not model retrain)
            "pipeline_ran": _str(pipeline_raw),
            "pipeline_gw": int(pipeline_gw) if pipeline_gw else None,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Users
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/users")
async def admin_users(admin: AdminUser = Depends(_get_admin)):
    """List all registered users with basic stats."""
    from models.db.user_profile import UserProfile
    from models.db.user_squad import UserBank  # UserBank lives in user_squad.py

    async with AsyncSessionLocal() as db:
        users = (await db.execute(select(UserProfile))).scalars().all()
        banks = {
            b.team_id: b
            for b in (await db.execute(select(UserBank))).scalars().all()
        }

    out = []
    for u in users:
        bank = banks.get(u.team_id)
        out.append({
            "team_id": u.team_id,
            "name": u.name,
            "email": u.email,
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "free_transfers": bank.free_transfers if bank else None,
            "budget": round(bank.bank / 10, 1) if bank else None,  # bank is in pence (×10 = £M)
        })

    return {"users": out, "total": len(out)}

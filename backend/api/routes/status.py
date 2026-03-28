"""
System Status endpoint — GET /api/status

Returns everything a user (or the status page) needs to understand what
state the engine is in, what's happening now, and what comes next.

No auth required — this is a public informational endpoint.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from core.database import get_db
from models.db.gameweek import Gameweek

router = APIRouter()


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _mins_from_now(dt: datetime | None, now: datetime) -> float | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (dt - now).total_seconds() / 60.0


@router.get("")
async def get_system_status(db: AsyncSession = Depends(get_db)):
    """
    Returns the current GW state, timing, model health, and upcoming events.

    GW states:
      planning   — between last GW ending and next GW kick-off (make transfers)
      live       — GW is underway (gw_start_time ≤ now ≤ gw_end_time)
      settling   — last game finished, FPL processing results (finished=True, data_checked=False)
    """
    now = datetime.now(timezone.utc)

    # ── GW data ──────────────────────────────────────────────────────────────
    cur_res = await db.execute(select(Gameweek).where(Gameweek.is_current == True))
    current_gw = cur_res.scalars().first()

    nxt_res = await db.execute(select(Gameweek).where(Gameweek.is_next == True))
    next_gw = nxt_res.scalars().first()

    prev_res = await db.execute(select(Gameweek).where(Gameweek.is_previous == True))
    prev_gw = prev_res.scalars().first()

    # ── Determine state ───────────────────────────────────────────────────────
    state = "planning"
    state_label = "Planning"
    state_detail = "Make your transfers before the deadline."

    if current_gw:
        gw_start = current_gw.gw_start_time
        gw_end   = current_gw.gw_end_time

        if gw_start:
            if gw_start.tzinfo is None:
                gw_start = gw_start.replace(tzinfo=timezone.utc)
        if gw_end:
            if gw_end.tzinfo is None:
                gw_end = gw_end.replace(tzinfo=timezone.utc)

        next_id = (next_gw.id if next_gw else current_gw.id + 1) if current_gw else 0

        if gw_start and gw_end and gw_start <= now <= gw_end:
            state = "live"
            state_label = "GW Live"
            state_detail = "Games are in progress. Squad and predictions are frozen."
        elif gw_end and now > gw_end and not current_gw.finished:
            # Past gw_end_time but FPL hasn't flipped finished=True yet (normal — takes time)
            remaining_h = max(0, (gw_end + timedelta(hours=12) - now).total_seconds() / 3600)
            state = "settling"
            state_label = "Settling"
            state_detail = f"GW{current_gw.id} complete. FPL finalising results — GW{next_id} recommendations in ~{remaining_h:.0f}h."
        elif gw_end and current_gw.finished and now < gw_end + timedelta(hours=12):
            # 12h settling window — GW ended but recommendations not ready yet.
            # Even if data_checked=True, we hold until gw_end + 12h.
            remaining_h = (gw_end + timedelta(hours=12) - now).total_seconds() / 3600
            state = "settling"
            state_label = "Settling"
            state_detail = f"GW{current_gw.id} complete. GW{next_id} recommendations ready in ~{remaining_h:.0f}h — data settling overnight."
        elif current_gw.finished and not current_gw.data_checked:
            state = "settling"
            state_label = "Settling"
            state_detail = "Last game finished. FPL is processing results — new recommendations soon."
        elif current_gw.finished and current_gw.data_checked:
            state = "planning"
            state_label = "Planning"
            state_detail = "GW complete. Recommendations updated — plan your next GW."
        elif gw_start and now < gw_start:
            mins = (gw_start - now).total_seconds() / 60
            if mins <= 65:
                state = "pre_kickoff"
                state_label = "Pre Kick-off"
                state_detail = f"First game in {int(mins)} min. Squad locked, final predictions loaded."
            else:
                state = "planning"
                state_label = "Planning"
                state_detail = "Make your transfers before the deadline."
        elif not gw_start and not current_gw.finished:
            # gw_start_time not yet computed (columns added but pipeline hasn't run) —
            # fall back to deadline: if deadline has passed and GW not finished → live
            deadline_dt = current_gw.deadline_time
            if deadline_dt:
                if deadline_dt.tzinfo is None:
                    deadline_dt = deadline_dt.replace(tzinfo=timezone.utc)
                if now >= deadline_dt:
                    state = "live"
                    state_label = "GW Live"
                    state_detail = "Games are in progress. Squad and predictions are frozen."

    # ── Build GW blocks ───────────────────────────────────────────────────────
    def _gw_block(gw: Gameweek | None) -> dict | None:
        if not gw:
            return None
        gw_start = gw.gw_start_time
        gw_end   = gw.gw_end_time
        deadline = gw.deadline_time
        if gw_start and gw_start.tzinfo is None:
            gw_start = gw_start.replace(tzinfo=timezone.utc)
        if gw_end and gw_end.tzinfo is None:
            gw_end = gw_end.replace(tzinfo=timezone.utc)
        if deadline and deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        return {
            "id":             gw.id,
            "name":           gw.name,
            "deadline":       _iso(deadline),
            "gw_start_time":  _iso(gw_start),
            "gw_end_time":    _iso(gw_end),
            "finished":       gw.finished,
            "data_checked":   gw.data_checked,
            "is_blank":       gw.is_blank,
            "is_double":      gw.is_double,
            "mins_to_kickoff": _mins_from_now(gw_start, now),
            "mins_to_end":    _mins_from_now(gw_end, now),
            "mins_to_deadline": _mins_from_now(deadline, now),
        }

    # ── Model health from Redis ───────────────────────────────────────────────
    model_info: dict = {}
    pipeline_last_run: str | None = None
    pipeline_last_gw_id: int | None = None  # raw int — used for timeline done checks
    pipeline_running: bool = False
    try:
        from core.redis_client import redis_client
        import orjson
        import math as _math

        mae_raw      = await redis_client.get("ml:current_mae")
        retrain_raw  = await redis_client.get("ml:last_retrain_ts")
        pipeline_raw = await redis_client.get("pipeline:last_gw_run")
        cal_raw      = await redis_client.get("ml:calibration_map")
        lock_exists  = await redis_client.exists("fpl:pipeline:lock")
        pipeline_running = bool(lock_exists)

        # Parse MAE from Redis (may be None if daily job hasn't run yet)
        current_mae: float | None = None
        if mae_raw:
            try:
                v = float(mae_raw)
                current_mae = v if not (_math.isnan(v) or _math.isinf(v)) else None
            except (ValueError, TypeError):
                pass

        # DB fallback: compute average MAE from the most recent GW rows in BacktestModelMetrics
        if current_mae is None:
            try:
                from models.db.backtest import BacktestModelMetrics
                from sqlalchemy import select as _sel, desc as _desc
                _res = await db.execute(
                    _sel(BacktestModelMetrics.mae)
                    .order_by(_desc(BacktestModelMetrics.gw_id))
                    .limit(10)
                )
                _rows = [r for (r,) in _res.fetchall() if r is not None and not _math.isnan(r) and not _math.isinf(r)]
                if _rows:
                    current_mae = round(sum(_rows) / len(_rows), 3)
            except Exception:
                pass

        # Parse calibration groups from Redis
        cal_groups: int = 0
        if cal_raw:
            try:
                cal_groups = len(orjson.loads(cal_raw))
            except Exception:
                pass

        # DB fallback for calibration groups
        if cal_groups == 0:
            try:
                from models.db.calibration import PredictionCalibration
                from sqlalchemy import func as _func, select as _sel
                _cres = await db.execute(_sel(_func.count()).select_from(PredictionCalibration))
                _cnt = _cres.scalar()
                if _cnt:
                    cal_groups = int(_cnt)
            except Exception:
                pass

        def _s(v) -> str | None:
            if v is None: return None
            return v.decode() if isinstance(v, bytes) else str(v)

        model_info = {
            "current_mae":     current_mae,
            "last_retrain_at": _s(retrain_raw),
            "calibration_groups": cal_groups,
        }
        if pipeline_raw:
            raw_str = _s(pipeline_raw)
            pipeline_last_run = f"GW{raw_str}"
            try:
                pipeline_last_gw_id = int(raw_str)
            except (ValueError, TypeError):
                pass
    except Exception:
        pass

    # ── Model trained check ───────────────────────────────────────────────────
    try:
        from models.ml.xpts_model import XPtsModel
        xpts = XPtsModel()
        model_trained = xpts.is_trained()
    except Exception:
        model_trained = False

    # ── Upcoming events ───────────────────────────────────────────────────────
    upcoming_events: list[dict] = []

    if state == "planning" and current_gw:
        next_id = next_gw.id if next_gw else current_gw.id + 1
        # Always show the 12h recommendations sync anchor — derived from gw_end_time.
        # Shows as future ("in Xh") if the 12h window hasn't elapsed yet,
        # or past ("✓ Xh ago") once the pipeline has run.
        gw_end_p = current_gw.gw_end_time
        if gw_end_p:
            if gw_end_p.tzinfo is None:
                gw_end_p = gw_end_p.replace(tzinfo=timezone.utc)
            # +12h = pipeline starts internally; +45min = full chain completes (pipeline ~15min + Oracle ~10min + backtest + MAE ~10min)
            # Show the completion time so ✓ and the displayed time are both "everything is ready"
            recs_sync_at = gw_end_p + timedelta(hours=12, minutes=45)
            # ✓ only when pipeline actually ran for this GW — not just because time passed
            sync_done = pipeline_last_gw_id is not None and pipeline_last_gw_id == current_gw.id
            upcoming_events.append({
                "event": "recommendations_sync",
                "label": f"GW{next_id} recommendations sync",
                "at": _iso(recs_sync_at),
                "mins_from_now": _mins_from_now(recs_sync_at, now),
                "done": sync_done,
            })

    if state == "planning" and next_gw:
        gw_start = next_gw.gw_start_time
        deadline = next_gw.deadline_time
        if gw_start:
            if gw_start.tzinfo is None:
                gw_start = gw_start.replace(tzinfo=timezone.utc)
            sync_at = gw_start - timedelta(hours=1)
            upcoming_events.append({
                "event": "auto_squad_sync",
                "label": "Auto squad sync + cross-check",
                "at": _iso(sync_at),
                "mins_from_now": _mins_from_now(sync_at, now),
            })
            upcoming_events.append({
                "event": "gw_start",
                "label": f"GW{next_gw.id} kick-off",
                "at": _iso(gw_start),
                "mins_from_now": _mins_from_now(gw_start, now),
            })
        if deadline:
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)
            upcoming_events.append({
                "event": "deadline",
                "label": f"GW{next_gw.id} deadline",
                "at": _iso(deadline),
                "mins_from_now": _mins_from_now(deadline, now),
            })

    elif state in ("live", "settling") and current_gw:
        next_id = next_gw.id if next_gw else current_gw.id + 1
        gw_end = current_gw.gw_end_time
        if gw_end:
            if gw_end.tzinfo is None:
                gw_end = gw_end.replace(tzinfo=timezone.utc)
            if state == "live":
                upcoming_events.append({
                    "event": "gw_end",
                    "label": f"GW{current_gw.id} last game ends (approx)",
                    "at": _iso(gw_end),
                    "mins_from_now": _mins_from_now(gw_end, now),
                })
            # +12h = pipeline starts internally; +45min = full chain completes
            recs_at = gw_end + timedelta(hours=12, minutes=45)
            sync_done = pipeline_last_gw_id is not None and pipeline_last_gw_id == current_gw.id
            upcoming_events.append({
                "event": "recommendations_sync",
                "label": f"GW{next_id} recommendations sync",
                "at": _iso(recs_at),
                "mins_from_now": _mins_from_now(recs_at, now),
                "done": sync_done,
            })
        # Also show next GW events
        if next_gw:
            next_deadline = next_gw.deadline_time
            next_start    = next_gw.gw_start_time
            if next_deadline:
                if next_deadline.tzinfo is None:
                    next_deadline = next_deadline.replace(tzinfo=timezone.utc)
                upcoming_events.append({
                    "event": "deadline",
                    "label": f"GW{next_gw.id} deadline",
                    "at": _iso(next_deadline),
                    "mins_from_now": _mins_from_now(next_deadline, now),
                })
            if next_start:
                if next_start.tzinfo is None:
                    next_start = next_start.replace(tzinfo=timezone.utc)
                squad_sync_at = next_start - timedelta(hours=1)
                upcoming_events.append({
                    "event": "auto_squad_sync",
                    "label": "Auto squad sync + cross-check",
                    "at": _iso(squad_sync_at),
                    "mins_from_now": _mins_from_now(squad_sync_at, now),
                })
                upcoming_events.append({
                    "event": "gw_start",
                    "label": f"GW{next_gw.id} kick-off",
                    "at": _iso(next_start),
                    "mins_from_now": _mins_from_now(next_start, now),
                })

    # ── What the system is doing right now ───────────────────────────────────
    system_actions: list[str] = []
    if state == "live":
        system_actions.append("Squad and predictions frozen — mid-GW freeze active")
        system_actions.append("Live scores updating every 60s")
    elif state == "settling":
        system_actions.append("Waiting for FPL to mark data_checked=True")
        system_actions.append("Recommendations sync fires 12 hours after last game — data settles overnight")
    elif state == "planning":
        system_actions.append("ML predictions fresh — updated after last GW")
        system_actions.append("Transfer recommendations based on your current squad")
        system_actions.append("Auto squad sync fires 1hr before first kick-off")
    elif state == "pre_kickoff":
        system_actions.append("Squad synced and locked")
        system_actions.append("Cross-check ran — followed/ignored decisions recorded")
        system_actions.append("Predictions finalised for this GW")

    return {
        "state":          state,
        "state_label":    state_label,
        "state_detail":   state_detail,
        "server_time":    now.isoformat(),
        "current_gw":     _gw_block(current_gw),
        "next_gw":        _gw_block(next_gw),
        "previous_gw":    _gw_block(prev_gw),
        "model": {
            **model_info,
            "trained": model_trained,
            "mode":    "lightgbm" if model_trained else "cold_start_heuristic",
        },
        "pipeline_last_run": pipeline_last_run,
        "pipeline_running":  pipeline_running,
        "upcoming_events":   upcoming_events,
        "system_actions":    system_actions,
    }

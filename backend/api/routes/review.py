"""
Gameweek Review Engine — post-GW analysis of AI recommendation adherence.

GET  /api/review/gameweek?team_id=&gw_id=
  Returns: recommendations that were made, whether user followed them,
           net points vs AI advice, rank delta.

GET  /api/review/season?team_id=
  Returns: season-long adherence stats.

GET  /api/review/transfers?team_id=
  Fetches real FPL transfer history from the API and compares with DecisionLog.

POST /api/review/resolve
  Called after a GW completes — updates DecisionLog with actual_points + rank_delta.
"""
from __future__ import annotations

import httpx
from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, and_
from loguru import logger

from core.database import get_db
from core.config import settings
from agents.fpl_agent import FPLAgent
from models.db.decision_log import DecisionLog
from models.db.history import UserGWHistory
from models.db.gameweek import Gameweek
from models.db.player import Player
from models.db.team import Team
from api.deps import get_team_context
from services.cache_service import ANALYSIS_TTL, get_cached_payload, set_cached_payload

router = APIRouter()


# ── Request/Response schemas ──────────────────────────────────────────────────

class ResolveRequest(BaseModel):
    team_id: int
    gameweek_id: int
    actual_team_points: float
    rank_before: Optional[int] = None
    rank_after: Optional[int] = None


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/gameweek")
async def get_gw_review(
    team_context: dict = Depends(get_team_context),
    gw_id: Optional[int] = Query(None, description="Gameweek ID. Defaults to latest resolved GW."),
    db: AsyncSession = Depends(get_db),
):
    """
    Return a full post-GW review for the given team.

    If gw_id is omitted, uses the most recent completed GW.
    """
    team_id = team_context["team_id"]
    session = team_context.get("session")
    if gw_id is not None:
        cached = await get_cached_payload("review_gw", team_id, gw_id, session.session_token if session else "registered")
        if cached:
            cached["analysis_mode"] = "cached"
            return cached
    # Determine GW — always use the GW that has the most recent decision
    # for this team. This correctly handles the transition between GWs:
    # When GW31 is finished but GW32 oracle has already run and logged
    # decisions, we want to show GW32 (the planning GW), not GW31 (done).
    if gw_id is None:
        # Find the GW whose most recent decision timestamp is latest
        latest_dec_res = await db.execute(
            select(DecisionLog.gameweek_id)
            .where(DecisionLog.team_id == team_id)
            .order_by(DecisionLog.created_at.desc())
            .limit(1)
        )
        latest_gw_with_decision = latest_dec_res.scalar()

        if latest_gw_with_decision is not None:
            gw_id = latest_gw_with_decision
        else:
            # Fallback: no decisions at all → most recent finished GW
            current_gw_res = await db.execute(
                select(Gameweek).where(Gameweek.is_current == True)
            )
            current_gw = current_gw_res.scalars().first()

            finished_gws_res = await db.execute(
                select(Gameweek).where(Gameweek.finished == True).order_by(Gameweek.id.desc())
            )
            finished_gws = finished_gws_res.scalars().all()

            if finished_gws:
                gw_id = finished_gws[0].id
            elif current_gw:
                gw_id = current_gw.id
            else:
                return {"error": "No gameweek data found"}

    # Fetch decision log entries
    log_res = await db.execute(
        select(DecisionLog).where(
            and_(DecisionLog.team_id == team_id, DecisionLog.gameweek_id == gw_id)
        ).order_by(DecisionLog.created_at)
    )
    logs: list[DecisionLog] = log_res.scalars().all()

    # Fetch user GW history for actual performance
    hist_res = await db.execute(
        select(UserGWHistory).where(
            and_(UserGWHistory.team_id == team_id, UserGWHistory.gw_id == gw_id)
        )
    )
    hist = hist_res.scalars().first()

    # Fetch GW average score (all managers) for comparison
    gw_meta_res = await db.execute(select(Gameweek).where(Gameweek.id == gw_id))
    gw_meta = gw_meta_res.scalars().first()
    avg_gw_pts = gw_meta.average_entry_score if gw_meta and gw_meta.average_entry_score else None

    # Auto-mark pending decisions as ignored only when the GW is fully finished.
    # A GW with deadline passed but finished=False is still live (games in play) —
    # don't prematurely mark decisions as ignored during an active GW.
    from datetime import datetime as _dt
    now_utc = _dt.utcnow()
    gw_is_over = (
        gw_meta
        and gw_meta.deadline_time
        and gw_meta.deadline_time < now_utc
        and gw_meta.finished
    )
    if gw_is_over:
        auto_ignored = False
        for l in logs:
            if l.decision_followed is None:
                l.decision_followed = False
                auto_ignored = True
        if auto_ignored:
            await db.commit()
            # Re-fetch after commit
            log_res2 = await db.execute(
                select(DecisionLog).where(
                    and_(DecisionLog.team_id == team_id, DecisionLog.gameweek_id == gw_id)
                ).order_by(DecisionLog.created_at)
            )
            logs = log_res2.scalars().all()

    # Dedup: keep only the latest entry per decision.
    # Rules:
    #   captain_pick / formation  — singleton: only the most recent recommendation
    #     matters (new run supersedes old).  Keyed by decision_type only.
    #   transfer_strategy / chip  — each unique (type, option) pair is a distinct
    #     decision so we keep the latest of each.
    # After dedup, limit to the 7 most recent decisions (matches the Oracle
    # output size so the audit shows exactly what the model recommended).
    SINGLETON_TYPES = {"captain_pick", "captain", "formation_change", "formation"}
    seen: set[tuple] = set()
    deduplicated: list[DecisionLog] = []
    for l in sorted(logs, key=lambda x: x.created_at or "", reverse=True):
        dtype = (l.decision_type or "").lower().replace(" ", "_")
        if any(s in dtype for s in SINGLETON_TYPES):
            key: tuple = (dtype,)           # captain: only ONE per GW
        else:
            key = (dtype, l.recommended_option)
        if key not in seen:
            seen.add(key)
            deduplicated.append(l)
    # Keep at most 7 decisions — matches the Oracle action list length
    logs = deduplicated[:7]

    # ── Backfill missing player_id_primary/secondary for transfers ──────────────
    # Intel.py now stores player IDs when logging, but older records may lack them.
    # Parse "OUT: X / IN: Y" from recommended_option and look up IDs from DB.
    import re as _re2
    for _l in logs:
        if "transfer" not in (_l.decision_type or "").lower():
            continue
        if _l.player_id_primary is not None:
            continue
        _ro = _l.recommended_option or ""
        _in_m2  = _re2.search(r"IN:\s*(.+?)$",     _ro, _re2.IGNORECASE)
        _out_m2 = _re2.search(r"OUT:\s*(.+?)\s*/", _ro, _re2.IGNORECASE)
        _changed = False
        if _in_m2:
            _r2 = await db.execute(select(Player).where(Player.web_name.ilike(_in_m2.group(1).strip())))
            _p2 = _r2.scalars().first()
            if _p2:
                _l.player_id_primary = _p2.id
                _changed = True
        if _out_m2:
            _r3 = await db.execute(select(Player).where(Player.web_name.ilike(_out_m2.group(1).strip())))
            _p3 = _r3.scalars().first()
            if _p3:
                _l.player_id_secondary = _p3.id
                _changed = True
        if _changed:
            await db.commit()

    # ── Auto-compute actual_gain from FPL live data for finished GWs ─────────
    # Runs when: GW finished AND any followed decision has a player ID but no gain yet.
    gw_finished = gw_meta and gw_meta.finished
    needs_gain_compute = gw_finished and any(
        l.player_id_primary and l.actual_gain is None and l.decision_followed is True
        for l in logs
    )
    if needs_gain_compute:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"https://fantasy.premierleague.com/api/event/{gw_id}/live/"
                )
            if resp.status_code == 200:
                live_data = resp.json()
                # Build {element_id: total_points} map
                live_pts: dict[int, int] = {}
                for el in live_data.get("elements", []):
                    eid = el.get("id")
                    pts = el.get("stats", {}).get("total_points", 0)
                    if eid:
                        live_pts[eid] = pts

                any_updated = False
                for l in logs:
                    if not l.player_id_primary or l.actual_gain is not None:
                        continue
                    dt = (l.decision_type or "").lower()
                    primary_pts = live_pts.get(l.player_id_primary)
                    if primary_pts is None:
                        continue

                    if "captain" in dt:
                        # Gain = captain's points (the extra ×1 vs not captaining them)
                        l.actual_gain = float(primary_pts)
                    elif "transfer" in dt:
                        # Gain = player_in pts − player_out pts
                        secondary_pts = live_pts.get(l.player_id_secondary or 0)
                        if secondary_pts is not None:
                            l.actual_gain = float(primary_pts - secondary_pts)
                    any_updated = True

                if any_updated:
                    await db.commit()
                    # Re-fetch to get updated actual_gain values
                    log_res3 = await db.execute(
                        select(DecisionLog).where(
                            and_(DecisionLog.team_id == team_id, DecisionLog.gameweek_id == gw_id)
                        ).order_by(DecisionLog.created_at)
                    )
                    logs = log_res3.scalars().all()
                    # Re-dedup
                    seen2: set[tuple] = set()
                    deduped2: list[DecisionLog] = []
                    for l in sorted(logs, key=lambda x: x.created_at or "", reverse=True):
                        key = (l.decision_type, l.recommended_option)
                        if key not in seen2:
                            seen2.add(key)
                            deduped2.append(l)
                    logs = deduped2
        except Exception as _gain_exc:
            logger.warning(f"actual_gain compute failed for GW{gw_id}: {_gain_exc}")

    # Compute stats
    followed = [l for l in logs if l.decision_followed is True]
    ignored = [l for l in logs if l.decision_followed is False]
    pending = [l for l in logs if l.decision_followed is None]
    decided = followed + ignored  # decisions where outcome is known

    expected_if_followed = sum(l.expected_points for l in followed if l.expected_points)

    # Build player_id → team_code map for badge rendering in the frontend
    _pids_gw = {
        pid for l in logs
        for pid in (l.player_id_primary, l.player_id_secondary)
        if pid is not None
    }
    _player_team_code_map: dict[int, int] = {}
    if _pids_gw:
        _p_res = await db.execute(
            select(Player.id, Player.team_id).where(Player.id.in_(_pids_gw))
        )
        _pid_to_team = {row[0]: row[1] for row in _p_res.fetchall()}
        _team_ids = set(_pid_to_team.values())
        _t_res = await db.execute(
            select(Team.id, Team.code).where(Team.id.in_(_team_ids))
        )
        _team_code_map = {row[0]: row[1] for row in _t_res.fetchall()}
        _player_team_code_map = {
            pid: _team_code_map.get(tid, 0)
            for pid, tid in _pid_to_team.items()
        }

    def log_to_dict(l: DecisionLog) -> dict:
        return {
            "id": l.id,
            "gameweek_id": l.gameweek_id,
            "decision_type": l.decision_type,
            "recommended_option": l.recommended_option,
            "user_choice": l.user_choice,
            "expected_points": l.expected_points,
            "actual_points": l.actual_points,
            "actual_gain": l.actual_gain,         # decision-specific gain (not team total)
            "player_id_primary": l.player_id_primary,
            "player_id_secondary": l.player_id_secondary,
            "player_team_code": _player_team_code_map.get(l.player_id_primary) if l.player_id_primary else None,
            "player_out_team_code": _player_team_code_map.get(l.player_id_secondary) if l.player_id_secondary else None,
            "decision_followed": l.decision_followed,
            "rank_before": l.rank_before,
            "rank_after": l.rank_after,
            "rank_delta": l.rank_delta,
            "reasoning": l.reasoning,
            "created_at": l.created_at.isoformat() if l.created_at else None,
        }

    # Net gain vs GW average — your actual score vs the gameweek average for all managers.
    # This is meaningful: positive = you beat the average, negative = below average.
    # The previous formula (actual - sum of expected per followed decision) was wrong
    # because it compared a single team score against stacked per-decision expected values.
    gain_vs_ai = round(hist.points - avg_gw_pts, 1) if (hist and avg_gw_pts) else None

    payload = {
        "team_id": team_id,
        "gameweek_id": gw_id,
        "summary": {
            "total_decisions": len(logs),
            "followed": len(followed),
            "ignored": len(ignored),
            "pending_resolution": len(pending),
            # Adherence = followed / decided (not / total). Pending don't count.
            "adherence_rate": round(len(followed) / max(len(decided), 1), 2),
            "expected_points_if_followed": round(expected_if_followed, 1),
            "actual_gw_points": hist.points if hist else None,
            "gain_vs_ai_pts": gain_vs_ai,
        },
        "user_gw_performance": {
            "gw_points": hist.points if hist else None,
            "overall_rank": hist.overall_rank if hist else None,
            "transfers_made": hist.event_transfers if hist else None,
            "transfer_cost": hist.event_transfers_cost if hist else None,
            "chip_played": hist.active_chip if hist else None,
            "points_on_bench": hist.points_on_bench if hist else None,
            "fpl_avg_pts": avg_gw_pts,  # FPL overall average for this GW (not user's average)
        } if hist else None,
        "decisions": [log_to_dict(l) for l in logs],
        "analysis_mode": "full",
        "session_expires_at": session.expires_at.isoformat() if session else None,
    }
    await set_cached_payload("review_gw", payload, ANALYSIS_TTL, team_id, gw_id, session.session_token if session else "registered")
    return payload


@router.get("/season")
async def get_season_review(
    team_context: dict = Depends(get_team_context),
    db: AsyncSession = Depends(get_db),
):
    """Season-long adherence statistics."""
    team_id = team_context["team_id"]
    session = team_context.get("session")
    cached = await get_cached_payload("review_season", team_id, session.session_token if session else "registered")
    if cached:
        cached["analysis_mode"] = "cached"
        return cached
    log_res = await db.execute(
        select(DecisionLog).where(
            DecisionLog.team_id == team_id,
        ).order_by(DecisionLog.gameweek_id)
    )
    all_logs: list[DecisionLog] = log_res.scalars().all()

    # Auto-mark pending decisions as ignored if their GW deadline has passed
    # AND the GW is finished. Decisions for a GW that is still live (current,
    # not finished) stay as "pending" — the GW is still being played.
    from datetime import datetime as _dt
    _now_utc = _dt.utcnow()
    _pending_logs = [l for l in all_logs if l.decision_followed is None]
    if _pending_logs:
        _pending_gw_ids = {l.gameweek_id for l in _pending_logs if l.gameweek_id}
        _gw_dl_res = await db.execute(
            select(Gameweek).where(Gameweek.id.in_(_pending_gw_ids))
        )
        # Build map: {gw_id: (deadline_time, finished)}
        _gw_map = {gw.id: (gw.deadline_time, gw.finished) for gw in _gw_dl_res.scalars().all()}
        _auto_ignored = 0
        for _l in _pending_logs:
            _gw_info = _gw_map.get(_l.gameweek_id)
            if not _gw_info:
                continue
            _dl, _finished = _gw_info
            # Only auto-ignore when the GW is fully finished (not just deadline-passed)
            if _dl and _dl < _now_utc and _finished:
                _l.decision_followed = False
                _auto_ignored += 1
        if _auto_ignored:
            await db.commit()
            # Re-fetch after commit
            _log_res2 = await db.execute(
                select(DecisionLog).where(DecisionLog.team_id == team_id)
                .order_by(DecisionLog.gameweek_id)
            )
            all_logs = _log_res2.scalars().all()

    # resolved_logs: GWs fully resolved with actual points recorded
    resolved_logs = [l for l in all_logs if l.resolved and l.actual_points is not None]
    # all_decided: all decisions where outcome is known (followed or ignored), inc. in-progress GW
    all_decided = [l for l in all_logs if l.decision_followed is not None]
    # pending_actionable: decisions where GW deadline hasn't passed (user can still act)
    pending_actionable = [l for l in all_logs if l.decision_followed is None]

    # For season stats use all_decided so GW31 ignored decisions count against adherence
    logs = all_decided
    pending_count = len(pending_actionable)

    if not all_logs:
        payload = {
            "team_id": team_id,
            "total_decisions": 0,
            "message": "No decisions logged yet. Sync your squad and make transfers to start tracking.",
            "analysis_mode": "degraded",
            "session_expires_at": session.expires_at.isoformat() if session else None,
        }
        return payload

    if not logs:
        # All decisions are pre-deadline pending — none resolved yet
        payload = {
            "team_id": team_id,
            "total_decisions": len(all_logs),
            "pending_decisions": pending_count,
            "message": f"{len(all_logs)} decision{'s' if len(all_logs) != 1 else ''} logged — awaiting GW resolution to compute outcomes. Run 'Fetch Actual Points' on the Oracle page after the gameweek finishes.",
            "analysis_mode": "pending",
            "session_expires_at": session.expires_at.isoformat() if session else None,
        }
        return payload

    followed = [l for l in logs if l.decision_followed]

    # Fetch GW history to get actual team scores per GW (avoid multiplying by N decisions per GW)
    followed_gw_ids = list({l.gameweek_id for l in followed if l.gameweek_id})
    gw_hist_map: dict[int, int] = {}
    if followed_gw_ids:
        hist_res = await db.execute(
            select(UserGWHistory).where(
                UserGWHistory.team_id == team_id,
                UserGWHistory.gw_id.in_(followed_gw_ids),
            )
        )
        gw_hist_map = {h.gw_id: (h.points or 0) for h in hist_res.scalars().all()}

    # Fetch GW average scores from Gameweek table for "pts vs average" metric
    gw_avg_map: dict[int, float] = {}
    if followed_gw_ids:
        gw_meta_res = await db.execute(
            select(Gameweek).where(Gameweek.id.in_(followed_gw_ids))
        )
        gw_avg_map = {
            gw.id: float(gw.average_entry_score)
            for gw in gw_meta_res.scalars().all()
            if gw.average_entry_score
        }

    # net_pts_vs_ai = mean(user GW score - GW average) for GWs with followed decisions.
    # Meaningful: positive = user consistently beats the GW average on AI-following GWs.
    vs_avg_deltas = [
        gw_hist_map.get(gw, 0) - gw_avg_map[gw]
        for gw in followed_gw_ids
        if gw in gw_avg_map and gw in gw_hist_map
    ]
    net_pts_vs_ai = round(sum(vs_avg_deltas) / len(vs_avg_deltas), 1) if vs_avg_deltas else None

    # Group by decision type — use all_decided (followed + ignored, inc. in-progress GW)
    # Only avg_actual comes from resolved_logs (needs actual_points)
    resolved_gw_ids_set = {l.gameweek_id for l in resolved_logs if l.gameweek_id}
    by_type: dict[str, dict] = {}
    for l in logs:
        # For CHIP_USED: use the specific chip name as the key so TC and FH
        # are shown separately (they have incomparable expected_points values)
        dt = l.decision_type
        if dt == "CHIP_USED" and l.recommended_option:
            chip_map = {
                "triple_captain": "Triple Captain",
                "bench_boost": "Bench Boost",
                "free_hit": "Free Hit",
                "wildcard": "Wildcard",
            }
            chip_label = chip_map.get(l.recommended_option.lower().replace(" ", "_"), l.recommended_option)
            dt = f"Chip: {chip_label}"

        if dt not in by_type:
            by_type[dt] = {
                "followed": 0, "ignored": 0,
                "all_expected": 0.0,   # sum of expected_pts across ALL decisions (followed+ignored)
                "resolved_gws": set(),  # GWs where this type was followed AND resolved
                "actual_gains": [],     # list of actual_gain values (decision-specific)
            }
        xp = l.expected_points or 0
        by_type[dt]["all_expected"] += xp
        # Collect decision-specific actual gains (from FPL live data, not team total)
        if l.actual_gain is not None:
            by_type[dt]["actual_gains"].append(l.actual_gain)
        if l.decision_followed:
            by_type[dt]["followed"] += 1
            # Only count for avg_actual if GW is fully resolved (actual points available)
            if l.gameweek_id and l.gameweek_id in resolved_gw_ids_set:
                by_type[dt]["resolved_gws"].add(l.gameweek_id)
        else:
            by_type[dt]["ignored"] += 1

    # Rank trajectory (only from resolved decisions)
    rank_entries = [l for l in resolved_logs if l.rank_delta is not None]
    total_rank_gain = sum(l.rank_delta for l in rank_entries if l.rank_delta)

    # How many distinct resolved GWs — avg_actual is only meaningful with 2+ GWs
    n_resolved_gws = len(resolved_gw_ids_set)

    payload = {
        "team_id": team_id,
        "total_decisions": len(logs),           # all decided (followed + ignored)
        "pending_decisions": pending_count,     # only truly actionable (deadline not passed)
        "followed": len(followed),
        "ignored": len(logs) - len(followed),
        "adherence_rate": round(len(followed) / max(len(logs), 1), 2),
        "net_pts_vs_ai": net_pts_vs_ai,
        "total_rank_gain_following_ai": total_rank_gain,
        "resolved_gw_count": n_resolved_gws,   # for frontend context
        "by_decision_type": {
            dt: {
                "followed": v["followed"],
                "ignored": v["ignored"],
                "adherence_rate": round(v["followed"] / max(v["followed"] + v["ignored"], 1), 2),
                # avg_expected uses ALL decisions (followed+ignored) — shows the engine's
                # predicted gain regardless of whether user acted. This avoids showing 0.0
                # for fully ignored types (e.g. formation_change where followed=0).
                "avg_expected": round(
                    v["all_expected"] / max(v["followed"] + v["ignored"], 1), 1
                ),
                # avg_actual only shown when 2+ distinct resolved GWs — otherwise it's just
                # one team score repeated for all types and gives a false impression.
                "avg_actual": round(
                    sum(gw_hist_map.get(gw, 0) for gw in v["resolved_gws"]) / max(len(v["resolved_gws"]), 1), 1
                ) if len(v["resolved_gws"]) >= 2 else None,
                # avg_actual_gain: decision-specific gain (player score, not team total)
                # For captain: captain's actual pts scored. For transfer: player_in - player_out.
                "avg_actual_gain": round(
                    sum(v["actual_gains"]) / len(v["actual_gains"]), 1
                ) if v["actual_gains"] else None,
                "last_actual_gain": round(v["actual_gains"][-1], 1) if v["actual_gains"] else None,
            }
            for dt, v in by_type.items()
        },
        "analysis_mode": "full",
        "session_expires_at": session.expires_at.isoformat() if session else None,
    }

    # Include individual decision rows for per-decision audit in frontend.
    # Use all_logs (not just logs=all_decided) so pending decisions show too.

    # Build player_id → team_code map for badge rendering in the frontend
    _pids_season = {
        pid for l in all_logs
        for pid in (l.player_id_primary, l.player_id_secondary)
        if pid is not None
    }
    _season_team_code_map: dict[int, int] = {}
    if _pids_season:
        _sp_res = await db.execute(
            select(Player.id, Player.team_id).where(Player.id.in_(_pids_season))
        )
        _spid_to_team = {row[0]: row[1] for row in _sp_res.fetchall()}
        _steam_ids = set(_spid_to_team.values())
        _st_res = await db.execute(
            select(Team.id, Team.code).where(Team.id.in_(_steam_ids))
        )
        _steam_code_map = {row[0]: row[1] for row in _st_res.fetchall()}
        _season_team_code_map = {
            pid: _steam_code_map.get(tid, 0)
            for pid, tid in _spid_to_team.items()
        }

    def _season_log_to_dict(l: DecisionLog) -> dict:
        return {
            "id": l.id,
            "gameweek_id": l.gameweek_id,
            "decision_type": l.decision_type,
            "recommended_option": l.recommended_option,
            "user_choice": l.user_choice,
            "expected_points": l.expected_points,
            "actual_points": l.actual_points,
            "actual_gain": l.actual_gain,
            "player_id_primary": l.player_id_primary,
            "player_id_secondary": l.player_id_secondary,
            "player_team_code": _season_team_code_map.get(l.player_id_primary) if l.player_id_primary else None,
            "player_out_team_code": _season_team_code_map.get(l.player_id_secondary) if l.player_id_secondary else None,
            "decision_followed": l.decision_followed,
            "reasoning": l.reasoning,
            "created_at": l.created_at.isoformat() if l.created_at else None,
        }

    # Dedup: keep only the latest entry per (decision_type, recommended_option) across the season.
    # This mirrors the GW review dedup logic so we don't show stale duplicates.
    seen_season: set[tuple] = set()
    audit_decisions: list[dict] = []
    for l in sorted(all_logs, key=lambda x: (x.gameweek_id or 0, x.created_at or ""), reverse=True):
        key = (l.gameweek_id, l.decision_type, l.recommended_option)
        if key not in seen_season:
            seen_season.add(key)
            audit_decisions.append(_season_log_to_dict(l))

    payload["decisions"] = audit_decisions
    await set_cached_payload("review_season", payload, ANALYSIS_TTL, team_id, session.session_token if session else "registered")
    return payload


@router.get("/transfers")
async def get_transfer_history_review(
    request: Request,
    team_id: int = Query(..., description="FPL team ID"),
    db: AsyncSession = Depends(get_db),
):
    """
    Fetch real transfer history from the FPL API and cross-reference with
    the AI DecisionLog to show which transfers were AI-recommended vs user-initiated.

    FPL API: GET /api/entry/{team_id}/transfers/
    Each transfer record: {element_in, element_out, element_in_cost, element_out_cost, event, time}
    """
    http_client = request.app.state.http_client
    agent = FPLAgent(http_client)

    try:
        fpl_transfers = await agent.get_transfers(team_id)
    except Exception as e:
        logger.error(f"FPL transfer history fetch failed for team {team_id}: {e}")
        raise HTTPException(502, f"FPL API error fetching transfers: {e}")

    if not fpl_transfers:
        return {
            "team_id": team_id,
            "total_transfers": 0,
            "transfers": [],
            "message": "No transfer history found for this team.",
        }

    # Resolve all player IDs to names + team codes in one DB query
    all_element_ids = set()
    for tx in fpl_transfers:
        all_element_ids.add(tx.get("element_in", 0))
        all_element_ids.add(tx.get("element_out", 0))
    all_element_ids.discard(0)

    player_res = await db.execute(
        select(Player, Team)
        .join(Team, Player.team_id == Team.id, isouter=True)
        .where(Player.id.in_(all_element_ids))
    )
    player_map: dict[int, dict] = {}
    for player, team in player_res.all():
        player_map[player.id] = {
            "web_name": player.web_name,
            "team_short_name": team.short_name if team else None,
            "team_code": team.code if team else None,
            "element_type": player.element_type,
        }

    # Fetch all DecisionLog entries related to transfers for this team.
    # decision_type may be stored as "transfer", "TRANSFER_STRATEGY", "transfer_strategy", etc.
    log_res = await db.execute(
        select(DecisionLog).where(
            and_(
                DecisionLog.team_id == team_id,
                DecisionLog.decision_type.ilike("%transfer%"),
            )
        ).order_by(DecisionLog.gameweek_id)
    )
    decision_logs: list[DecisionLog] = log_res.scalars().all()

    # Build a lookup: (element_in, gameweek_id) → DecisionLog
    # The recommended_option field may contain the player web_name or player ID.
    def _log_matches(log: DecisionLog, element_in: int, gw: int) -> bool:
        if log.gameweek_id != gw:
            return False
        recommended = str(log.recommended_option or "")
        # Match by element ID string OR player web_name
        player_info = player_map.get(element_in, {})
        web_name = player_info.get("web_name", "")
        return str(element_in) in recommended or (web_name and web_name.lower() in recommended.lower())

    enriched = []
    for tx in fpl_transfers:
        element_in: int = tx.get("element_in", 0)
        element_out: int = tx.get("element_out", 0)
        gw: int = tx.get("event", 0)
        cost_in: int = tx.get("element_in_cost", 0)
        cost_out: int = tx.get("element_out_cost", 0)
        tx_time: str = tx.get("time", "")

        p_in = player_map.get(element_in, {})
        p_out = player_map.get(element_out, {})

        # Find matching AI decision log entry
        matched_log = next(
            (l for l in decision_logs if _log_matches(l, element_in, gw)),
            None,
        )

        enriched.append({
            "gameweek": gw,
            "time": tx_time,
            "element_in": element_in,
            "element_in_name": p_in.get("web_name") or f"#{element_in}",
            "element_in_team": p_in.get("team_short_name"),
            "element_in_team_code": p_in.get("team_code"),
            "element_in_position": p_in.get("element_type"),
            "element_out": element_out,
            "element_out_name": p_out.get("web_name") or f"#{element_out}",
            "element_out_team": p_out.get("team_short_name"),
            "element_out_team_code": p_out.get("team_code"),
            "element_out_position": p_out.get("element_type"),
            "element_in_cost_millions": round(cost_in / 10, 1),
            "element_out_cost_millions": round(cost_out / 10, 1),
            # AI recommendation cross-reference
            "ai_recommended": matched_log is not None,
            "ai_decision": {
                "id": matched_log.id,
                "recommended_option": matched_log.recommended_option,
                "user_choice": matched_log.user_choice,
                "decision_followed": matched_log.decision_followed,
                "expected_points": matched_log.expected_points,
                "actual_points": matched_log.actual_points,
                "reasoning": matched_log.reasoning,
            } if matched_log else None,
        })

    # Sort chronologically (newest first)
    enriched.sort(key=lambda t: (t["gameweek"], t["time"]), reverse=True)

    ai_recommended_count = sum(1 for t in enriched if t["ai_recommended"])

    return {
        "team_id": team_id,
        "total_transfers": len(enriched),
        "ai_recommended_count": ai_recommended_count,
        "user_initiated_count": len(enriched) - ai_recommended_count,
        "adherence_rate": round(ai_recommended_count / max(len(enriched), 1), 2),
        "transfers": enriched,
    }


@router.get("/cross-check")
async def cross_check_decisions(
    request: Request,
    team_id: int = Query(..., description="FPL team ID"),
    gameweek: int = Query(..., description="Gameweek to cross-check"),
    db: AsyncSession = Depends(get_db),
):
    """
    Cross-check AI decisions against the user's REAL submitted squad for a GW.
    Pulls live FPL picks (entry/{team_id}/event/{gw}/picks/) and verifies:
      - Captain: did the user actually captain the AI-recommended player?
      - Transfers: (covered by /review/transfers)
    Returns a verified status for each decision type.
    """
    http_client = request.app.state.http_client
    agent = FPLAgent(http_client)

    # Fetch real picks from FPL API
    try:
        picks_data = await agent.get_picks(team_id, gameweek)
        real_picks = picks_data.get("picks", [])
    except Exception as e:
        logger.error(f"FPL picks fetch failed for team {team_id} GW{gameweek}: {e}")
        return {
            "team_id": team_id,
            "gameweek": gameweek,
            "verified": False,
            "error": f"Could not fetch real squad from FPL API: {e}",
            "checks": [],
        }

    # Find actual captain
    real_captain_id = next(
        (p["element"] for p in real_picks if p.get("is_captain")), None
    )
    real_player_ids = {p["element"] for p in real_picks}

    # Resolve real captain name from DB
    real_captain_name = None
    if real_captain_id:
        from models.db.player import Player
        captain_player = await db.get(Player, real_captain_id)
        real_captain_name = captain_player.web_name if captain_player else str(real_captain_id)

    # Fetch AI decision logs for this GW
    log_res = await db.execute(
        select(DecisionLog).where(
            and_(
                DecisionLog.team_id == team_id,
                DecisionLog.gameweek_id == gameweek,
            )
        )
    )
    decisions = log_res.scalars().all()

    checks = []

    # ── Captain check ──────────────────────────────────────────────────────────
    # decision_type may be "captain", "CAPTAIN_PICK", "captain_pick", etc.
    captain_decisions = [d for d in decisions if "captain" in (d.decision_type or "").lower()]
    for dec in captain_decisions:
        recommended = str(dec.recommended_option or "")
        # Check if recommended player name appears in real captain
        matched = (
            real_captain_name is not None and (
                recommended.lower() in (real_captain_name or "").lower()
                or (real_captain_name or "").lower() in recommended.lower()
                or (real_captain_id is not None and str(real_captain_id) in recommended)
            )
        )
        checks.append({
            "decision_id": dec.id,
            "decision_type": "captain",
            "ai_recommended": recommended,
            "real_action": f"Captained {real_captain_name}" if real_captain_name else "Unknown",
            "verified": matched,
            "method": "FPL picks API cross-check",
        })
        # Update DecisionLog with verified result
        if matched and not dec.decision_followed:
            dec.decision_followed = True
            dec.user_choice = f"Captained {real_captain_name}"
            await db.commit()

    # ── Transfer check (player presence in squad) ─────────────────────────────
    # decision_type may be "transfer", "TRANSFER_STRATEGY", "transfer_strategy", etc.
    import re as _re
    transfer_decisions = [d for d in decisions if "transfer" in (d.decision_type or "").lower()]
    for dec in transfer_decisions:
        recommended = str(dec.recommended_option or "")
        player_in_squad = False
        matched_in_player: "Player | None" = None

        for pid in real_player_ids:
            p = await db.get(Player, pid)
            if p and (
                str(pid) in recommended
                or p.web_name.lower() in recommended.lower()
            ):
                player_in_squad = True
                matched_in_player = p
                break

        # Backfill player_id_primary/secondary from "OUT: X / IN: Y" when missing.
        # Without these IDs the actual_gain computation is skipped — model can't learn.
        if dec.player_id_primary is None and "/" in recommended:
            _in_m  = _re.search(r"IN:\s*(.+?)$",      recommended, _re.IGNORECASE)
            _out_m = _re.search(r"OUT:\s*(.+?)\s*/",   recommended, _re.IGNORECASE)
            if _in_m:
                _in_name = _in_m.group(1).strip()
                _in_res = await db.execute(select(Player).where(Player.web_name.ilike(_in_name)))
                _in_p   = _in_res.scalars().first()
                if _in_p:
                    dec.player_id_primary = _in_p.id
                    if matched_in_player is None:
                        matched_in_player = _in_p
            if _out_m:
                _out_name = _out_m.group(1).strip()
                _out_res  = await db.execute(select(Player).where(Player.web_name.ilike(_out_name)))
                _out_p    = _out_res.scalars().first()
                if _out_p:
                    dec.player_id_secondary = _out_p.id

        checks.append({
            "decision_id": dec.id,
            "decision_type": "transfer",
            "ai_recommended": recommended,
            "real_action": "Transfer found in squad" if player_in_squad else "Transfer NOT found in squad",
            "verified": player_in_squad,
            "method": "FPL picks API cross-check",
        })
        if player_in_squad and not dec.decision_followed:
            dec.decision_followed = True

    await db.commit()

    # ── Compute actual_gain for all verified decisions that now have player IDs ─
    # Fetch FPL live data once and compute gain for captain + transfers.
    # This runs immediately so the model can learn without waiting for a second request.
    gw_meta_res = await db.execute(select(Gameweek).where(Gameweek.id == gameweek))
    gw_meta = gw_meta_res.scalar_one_or_none()
    gw_finished = gw_meta is not None and gw_meta.finished

    decisions_needing_gain = [
        d for d in decisions
        if d.player_id_primary and d.actual_gain is None and d.decision_followed is True
    ]
    if gw_finished and decisions_needing_gain:
        try:
            async with httpx.AsyncClient(timeout=10.0) as _client:
                _resp = await _client.get(
                    f"https://fantasy.premierleague.com/api/event/{gameweek}/live/"
                )
            if _resp.status_code == 200:
                _live = _resp.json()
                _pts_map: dict[int, int] = {
                    el["id"]: el.get("stats", {}).get("total_points", 0)
                    for el in _live.get("elements", [])
                    if el.get("id")
                }
                for d in decisions_needing_gain:
                    _dt = (d.decision_type or "").lower()
                    _primary_pts = _pts_map.get(d.player_id_primary)
                    if _primary_pts is None:
                        continue
                    if "captain" in _dt:
                        d.actual_gain = float(_primary_pts)
                    elif "transfer" in _dt:
                        _sec_pts = _pts_map.get(d.player_id_secondary or 0)
                        if _sec_pts is not None:
                            d.actual_gain = float(_primary_pts - _sec_pts)
                await db.commit()
                logger.info(
                    f"Cross-check GW{gameweek}: computed actual_gain for "
                    f"{len(decisions_needing_gain)} decision(s)"
                )
        except Exception as _e:
            logger.warning(f"Cross-check GW{gameweek}: actual_gain compute failed: {_e}")

    verified_count = sum(1 for c in checks if c["verified"])
    return {
        "team_id": team_id,
        "gameweek": gameweek,
        "verified": verified_count == len(checks) and len(checks) > 0,
        "verified_count": verified_count,
        "total_checks": len(checks),
        "real_captain": real_captain_name,
        "real_captain_id": real_captain_id,
        "checks": checks,
    }


@router.post("/chip-check")
async def chip_check(
    team_id: int = Query(..., description="FPL team ID"),
    gameweek: Optional[int] = Query(None, description="GW to check. Defaults to current GW."),
    db: AsyncSession = Depends(get_db),
):
    """
    Auto-detect chip usage from FPL API and log it to DecisionLog.

    Flow:
      1. Read active chip from Redis (set during pipeline sync)
      2. If Redis miss, fall back to FPL /entry/{team_id}/history/
      3. Cross-check against chip DecisionLog entries for this GW
      4. If matched → mark decision_followed = True
      5. If chip used but NOT in DecisionLog → create a new CHIP_USED entry
    """
    from core.redis_client import redis_client
    from datetime import datetime as _dt

    # FPL API uses short-form names — normalize to internal canonical names
    CHIP_FPL_TO_CANONICAL: dict[str, str] = {
        "3xc":    "triple_captain",
        "bboost": "bench_boost",
        "wildcard": "wildcard",
        "freehit":  "free_hit",
        "free_hit": "free_hit",
    }
    CHIP_LABELS: dict[str, str] = {
        "wildcard":       "Wildcard",
        "free_hit":       "Free Hit",
        "freehit":        "Free Hit",
        "bench_boost":    "Bench Boost",
        "bboost":         "Bench Boost",
        "triple_captain": "Triple Captain",
        "3xc":            "Triple Captain",
    }

    # ── Resolve GW ────────────────────────────────────────────────────────────
    if gameweek is None:
        gw_res = await db.execute(select(Gameweek).where(Gameweek.is_current == True))
        current_gw = gw_res.scalars().first()
        gameweek = current_gw.id if current_gw else None
    if gameweek is None:
        return {"chip_used": None, "gameweek": None, "logged": False, "was_recommended": False}

    # ── Read from Redis ────────────────────────────────────────────────────────
    chip_used: Optional[str] = None
    redis_key = f"fpl:chip:active:{team_id}"
    raw = await redis_client.get(redis_key)
    if raw:
        try:
            parts = raw.decode() if isinstance(raw, bytes) else raw
            chip_str, gw_str = parts.split(":", 1)
            if int(gw_str) == gameweek:
                chip_used = chip_str
        except Exception:
            pass

    # ── FPL history fallback ───────────────────────────────────────────────────
    if not chip_used:
        try:
            import httpx as _httpx
            async with _httpx.AsyncClient(timeout=12.0, follow_redirects=True) as _c:
                # Primary: picks endpoint has active_chip directly
                _r = await _c.get(
                    f"https://fantasy.premierleague.com/api/entry/{team_id}/event/{gameweek}/picks/",
                    headers={"User-Agent": "Mozilla/5.0"}
                )
                if _r.status_code == 200:
                    chip_used = _r.json().get("active_chip") or None
                # Fallback: history endpoint has chips[] array
                if not chip_used:
                    _r2 = await _c.get(
                        f"https://fantasy.premierleague.com/api/entry/{team_id}/history/",
                        headers={"User-Agent": "Mozilla/5.0"}
                    )
                    if _r2.status_code == 200:
                        for chip in _r2.json().get("chips", []):
                            if chip.get("event") == gameweek:
                                chip_used = chip.get("name")
                                break
        except Exception as ex:
            logger.warning(f"chip-check FPL history fallback: {ex}")

    if not chip_used:
        return {
            "chip_used": None,
            "gameweek": gameweek,
            "logged": False,
            "was_recommended": False,
            "message": "No chip played this gameweek",
        }

    # Normalize FPL API short-form chip names to canonical internal names
    chip_used_canonical = CHIP_FPL_TO_CANONICAL.get(chip_used, chip_used)
    chip_label = CHIP_LABELS.get(chip_used, chip_used.replace("_", " ").title())

    def _norm(s: str) -> str:
        return s.lower().replace("_", " ").replace("-", " ").strip()

    # ── Look for a proper chip recommendation entry (NOT CHIP_USED self-match) ─
    # Searches chip_recommendation, chip_timing, or any chip-type entry that is
    # NOT the CHIP_USED auto-log (which would falsely self-match).
    dec_res = await db.execute(
        select(DecisionLog).where(
            and_(
                DecisionLog.team_id == team_id,
                DecisionLog.gameweek_id == gameweek,
                DecisionLog.decision_type.ilike("%chip%"),
                DecisionLog.decision_type != "CHIP_USED",   # exclude self-matches
            )
        )
    )
    chip_decisions = dec_res.scalars().all()

    matched_dec = next(
        (d for d in chip_decisions
         if _norm(chip_used_canonical) in _norm(d.recommended_option or "")
         or _norm(chip_used) in _norm(d.recommended_option or "")
         or _norm(d.recommended_option or "") in _norm(chip_used_canonical)),
        None,
    )

    was_recommended = matched_dec is not None
    logged = False

    if matched_dec:
        if not matched_dec.decision_followed:
            matched_dec.decision_followed = True
            matched_dec.user_choice = f"Played {chip_label}"
            await db.commit()
        logged = True
        logger.info(f"chip-check: team={team_id} GW{gameweek} {chip_used} matched log id={matched_dec.id}")

    # ── Always resolve CHIP_USED entry (create or patch) ─────────────────────
    # Runs regardless of whether a prior recommendation was found, so we can
    # patch expected_points on stale entries that were created before this fix.
    if True:
        # Create a usage record if not already present (idempotent)
        existing_res = await db.execute(
            select(DecisionLog).where(
                and_(
                    DecisionLog.team_id == team_id,
                    DecisionLog.gameweek_id == gameweek,
                    DecisionLog.decision_type == "CHIP_USED",
                    DecisionLog.recommended_option.ilike(f"%{chip_used_canonical}%"),
                )
            )
        )
        existing = existing_res.scalars().first()

        # Derive chip expected_points from related decision log entries.
        # Strategy:
        #   1. Try chip_recommendation / chip_timing type entries (explicit)
        #   2. For Triple Captain: derive from captain_pick xPts × 3 (captain plays 3x)
        #   3. For Bench Boost: derive from sum of bench xPts in transfer_strategy
        linked_xpts: float | None = None
        prior_rec = None

        # Strategy 1: explicit chip recommendation entry (chip_recommendation or chip_timing)
        for rec_type in ("chip_recommendation", "chip_timing"):
            prior_rec_res = await db.execute(
                select(DecisionLog).where(
                    and_(
                        DecisionLog.team_id == team_id,
                        DecisionLog.decision_type == rec_type,
                    )
                ).order_by(DecisionLog.created_at.desc())
            )
            prior_rec = next(
                (d for d in prior_rec_res.scalars().all()
                 if _norm(chip_used_canonical) in _norm(d.recommended_option or "")
                 or _norm(chip_used) in _norm(d.recommended_option or "")),
                None,
            )
            if prior_rec:
                linked_xpts = prior_rec.expected_points if prior_rec.expected_points else None
                break

        # Strategy 2: Triple Captain — derive from captain_pick × 3 for same GW
        if linked_xpts is None and chip_used_canonical == "triple_captain":
            cap_res = await db.execute(
                select(DecisionLog).where(
                    and_(
                        DecisionLog.team_id == team_id,
                        DecisionLog.gameweek_id == gameweek,
                        DecisionLog.decision_type == "captain_pick",
                    )
                ).order_by(DecisionLog.created_at.desc()).limit(1)
            )
            cap_entry = cap_res.scalars().first()
            if cap_entry and cap_entry.expected_points:
                # TC scoring: captain scores 3× instead of 2× normal.
                # Standard captain doubles points; TC triples.
                # expected_points stored for captain_pick = full TC projected xPts
                # (set by the captain engine); derive TC bonus = cap_xpts × 3
                linked_xpts = round(cap_entry.expected_points * 3, 1)
                logger.info(
                    f"chip-check: derived TC xPts={linked_xpts} from captain_pick "
                    f"expected_points={cap_entry.expected_points}"
                )

        reasoning = (
            f"{chip_label} played GW{gameweek}. Engine recommended this based on Monte Carlo simulation."
            if prior_rec or linked_xpts
            else f"{chip_label} played GW{gameweek}. Chip usage logged from FPL API."
        )

        if not existing:
            db.add(DecisionLog(
                team_id=team_id,
                gameweek_id=gameweek,
                decision_type="CHIP_USED",
                recommended_option=chip_used_canonical,
                user_choice=f"Played {chip_label}",
                expected_points=linked_xpts,
                decision_followed=True,
                reasoning=reasoning,
                created_at=_dt.utcnow(),
            ))
        else:
            # Patch stale entries: update expected_points + reasoning if they are missing/0
            needs_patch = (
                (not existing.expected_points or existing.expected_points == 0.0) and linked_xpts
            ) or (
                "Auto-detected from FPL API" in (existing.reasoning or "")
                and (prior_rec or linked_xpts)
            )
            if needs_patch:
                existing.expected_points = linked_xpts
                existing.reasoning = reasoning
                logger.info(
                    f"chip-check: patched CHIP_USED id={existing.id} "
                    f"expected_points={linked_xpts} reasoning updated"
                )
        await db.commit()
        logged = True
        # A chip is "recommended" if the engine explicitly recommended it OR
        # if we derived expected_points from a related entry (captain_pick etc.)
        if linked_xpts:
            was_recommended = True
        logger.info(
            f"chip-check: team={team_id} GW{gameweek} {chip_used} — "
            f"CHIP_USED upserted, expected_points={linked_xpts}"
        )

    return {
        "chip_used": chip_used,
        "chip_label": chip_label,
        "gameweek": gameweek,
        "was_recommended": was_recommended,
        "logged": logged,
    }


@router.post("/resolve")
async def resolve_gameweek(
    req: ResolveRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Called after a GW completes — populate actual_points and rank_delta
    for all unresolved DecisionLog entries for this team/GW.
    """
    log_res = await db.execute(
        select(DecisionLog).where(
            and_(
                DecisionLog.team_id == req.team_id,
                DecisionLog.gameweek_id == req.gameweek_id,
                DecisionLog.resolved_at.is_(None),
            )
        )
    )
    logs = log_res.scalars().all()

    if not logs:
        return {"message": "No unresolved decisions found for this GW"}

    from datetime import datetime

    rank_delta = None
    if req.rank_before and req.rank_after:
        rank_delta = req.rank_before - req.rank_after  # positive = rank improved

    updated = 0
    for log in logs:
        log.actual_points = req.actual_team_points
        log.rank_before = req.rank_before
        log.rank_after = req.rank_after
        log.rank_delta = rank_delta
        log.resolved_at = datetime.utcnow()
        log.resolved = True
        updated += 1

    await db.commit()

    logger.info(
        f"GW review resolved: team={req.team_id} gw={req.gameweek_id} "
        f"updated={updated} rank_delta={rank_delta}"
    )

    return {
        "resolved": updated,
        "gameweek_id": req.gameweek_id,
        "rank_delta": rank_delta,
    }

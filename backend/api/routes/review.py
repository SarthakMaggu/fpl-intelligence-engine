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
    # Determine GW — use GW with most recent decisions for this team.
    # This avoids showing a stale finished GW when decisions have been logged
    # for the active GW (decisions are tagged to the GW when made, even if the
    # action applies to the following GW).
    if gw_id is None:
        # Prefer the most recently resolved GW (decisions with actual_points set)
        # so pre-deadline we show last finished GW, not the upcoming GW's pending decisions.
        resolved_log_res = await db.execute(
            select(DecisionLog)
            .where(DecisionLog.team_id == team_id, DecisionLog.resolved == True)
            .order_by(DecisionLog.gameweek_id.desc())
        )
        resolved_log = resolved_log_res.scalars().first()
        if resolved_log:
            gw_id = resolved_log.gameweek_id
        else:
            # No resolved decisions yet — fall back to latest logged decision
            latest_log_res = await db.execute(
                select(DecisionLog)
                .where(DecisionLog.team_id == team_id)
                .order_by(DecisionLog.created_at.desc())
            )
            latest_log = latest_log_res.scalars().first()
            if latest_log:
                gw_id = latest_log.gameweek_id
            else:
                # No decisions at all — fall back to most recent finished GW
                gw_res = await db.execute(
                    select(Gameweek).where(Gameweek.finished == True).order_by(Gameweek.id.desc())
                )
                gw = gw_res.scalars().first()
                if not gw:
                    return {"error": "No completed gameweeks found"}
                gw_id = gw.id

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

    # Dedup: keep only the latest entry per (decision_type, recommended_option) pair.
    # Cleans up historical duplicates caused by multiple page loads before dedup was added.
    seen: set[tuple] = set()
    deduplicated: list[DecisionLog] = []
    for l in sorted(logs, key=lambda x: x.created_at or "", reverse=True):
        key = (l.decision_type, l.recommended_option)
        if key not in seen:
            seen.add(key)
            deduplicated.append(l)
    logs = deduplicated

    # Compute stats
    followed = [l for l in logs if l.decision_followed is True]
    ignored = [l for l in logs if l.decision_followed is False]
    pending = [l for l in logs if l.decision_followed is None]

    expected_if_followed = sum(l.expected_points for l in followed if l.expected_points)
    actual_total = sum(l.actual_points for l in followed if l.actual_points is not None)

    def log_to_dict(l: DecisionLog) -> dict:
        return {
            "id": l.id,
            "gameweek_id": l.gameweek_id,
            "decision_type": l.decision_type,
            "recommended_option": l.recommended_option,
            "user_choice": l.user_choice,
            "expected_points": l.expected_points,
            "actual_points": l.actual_points,
            "decision_followed": l.decision_followed,
            "rank_before": l.rank_before,
            "rank_after": l.rank_after,
            "rank_delta": l.rank_delta,
            "reasoning": l.reasoning,
            "created_at": l.created_at.isoformat() if l.created_at else None,
        }

    # Net gain vs AI advice — only meaningful when actual_points are resolved
    has_resolved = any(l.actual_points is not None for l in followed)
    gain_vs_ai = round(actual_total - expected_if_followed, 1) if has_resolved else None

    payload = {
        "team_id": team_id,
        "gameweek_id": gw_id,
        "summary": {
            "total_decisions": len(logs),
            "followed": len(followed),
            "ignored": len(ignored),
            "pending_resolution": len(pending),
            "adherence_rate": round(len(followed) / max(len(logs), 1), 2),
            "expected_points_if_followed": round(expected_if_followed, 1),
            "actual_points_followed": round(actual_total, 1),
            "gain_vs_ai_pts": round(gain_vs_ai, 1) if gain_vs_ai is not None else None,
        },
        "user_gw_performance": {
            "gw_points": hist.points if hist else None,
            "overall_rank": hist.overall_rank if hist else None,
            "transfers_made": hist.event_transfers if hist else None,
            "transfer_cost": hist.event_transfers_cost if hist else None,
            "chip_played": hist.active_chip if hist else None,
            "points_on_bench": hist.points_on_bench if hist else None,
            "avg_gw_pts": avg_gw_pts,
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
    # Resolved logs have actual_points set (post-GW oracle resolve)
    logs = [l for l in all_logs if l.resolved and l.actual_points is not None]
    pending_count = len([l for l in all_logs if not l.resolved])

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
    total_expected = sum(l.expected_points for l in followed if l.expected_points)
    total_actual = sum(l.actual_points for l in followed if l.actual_points is not None)

    # Group by decision type
    by_type: dict[str, dict] = {}
    for l in logs:
        dt = l.decision_type
        if dt not in by_type:
            by_type[dt] = {"followed": 0, "ignored": 0, "expected": 0.0, "actual": 0.0}
        if l.decision_followed:
            by_type[dt]["followed"] += 1
            by_type[dt]["expected"] += l.expected_points or 0
            by_type[dt]["actual"] += l.actual_points or 0
        else:
            by_type[dt]["ignored"] += 1

    # Rank trajectory
    rank_entries = [l for l in logs if l.rank_delta is not None]
    total_rank_gain = sum(l.rank_delta for l in rank_entries if l.rank_delta)

    payload = {
        "team_id": team_id,
        "total_decisions": len(logs),
        "pending_decisions": pending_count,
        "followed": len(followed),
        "ignored": len(logs) - len(followed),
        "adherence_rate": round(len(followed) / max(len(logs), 1), 2),
        "net_pts_vs_ai": round(total_actual - total_expected, 1),
        "total_rank_gain_following_ai": total_rank_gain,
        "by_decision_type": {
            dt: {
                "followed": v["followed"],
                "ignored": v["ignored"],
                "adherence_rate": round(v["followed"] / max(v["followed"] + v["ignored"], 1), 2),
                "avg_expected": round(v["expected"] / max(v["followed"], 1), 1),
                "avg_actual": round(v["actual"] / max(v["followed"], 1), 1),
            }
            for dt, v in by_type.items()
        },
        "analysis_mode": "full",
        "session_expires_at": session.expires_at.isoformat() if session else None,
    }
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
    transfer_decisions = [d for d in decisions if "transfer" in (d.decision_type or "").lower()]
    for dec in transfer_decisions:
        recommended = str(dec.recommended_option or "")
        # Try to match player ID or name in real squad
        # recommended_option format may be "web_name" or "player_id:xxx"
        player_in_squad = False
        for pid in real_player_ids:
            from models.db.player import Player as PlayerModel
            p = await db.get(PlayerModel, pid)
            if p and (
                str(pid) in recommended
                or p.web_name.lower() in recommended.lower()
            ):
                player_in_squad = True
                break
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

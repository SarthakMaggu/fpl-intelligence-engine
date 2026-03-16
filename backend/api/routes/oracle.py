"""
GW Oracle API — theoretically best £100m team, snapshotted at each GW deadline.

POST /api/oracle/snapshot?team_id=   — compute and store oracle for current GW
GET  /api/oracle/history?team_id=    — fetch all past oracle snapshots
POST /api/oracle/resolve             — fill actual_points after GW completes
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from core.database import get_db
from api.deps import get_db_session, get_team_context
from models.db.gameweek import Gameweek
from models.db.player import Player
from models.db.history import UserGWHistory
from models.db.user_squad import UserSquad, UserBank
from models.db.oracle import GWOracle
from services.cache_service import ANALYSIS_TTL, get_cached_payload, invalidate_cache_prefix, set_cached_payload

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────

class OracleResolveRequest(BaseModel):
    team_id: int
    gameweek_id: int
    oracle_actual_points: Optional[float] = None  # actual pts scored by oracle XI
    algo_actual_points: Optional[float] = None    # actual pts scored by user's real XI


# ── Chip normalisation helper ─────────────────────────────────────────────────

def _normalise_chip_score(
    raw_points: int,
    chip: str | None,
    live_map: dict[int, int],
    captain_id: int | None,
    bench_ids: list[int],
) -> tuple[int, int, str | None]:
    """
    Strip chip contribution from a team's raw GW score so it's comparable
    to the Oracle XI which never uses chips.

    Returns (normalised_score, adjustment_stripped, chip_miss_reason_or_None).

    TC (3xc): captain scores 3× normally; Oracle uses 2×. Strip the extra 1×.
        raw → raw − captain_actual_pts (puts captain back to 2×)
    BB (bboost): bench players scored; Oracle has no bench contribution.
        raw → raw − sum(bench_actual_pts)
    WC / FH: squad was restructured this GW — no reliable adjustment.
    """
    chip_canonical = (chip or "").lower().strip()
    captain_pts = live_map.get(captain_id, 0) if captain_id else 0

    if chip_canonical in ("3xc", "triple_captain"):
        # 3× captain → was counted as cap_pts × 3 in FPL total
        # Oracle counts captain 2×, so strip 1× captain
        adjustment = captain_pts  # remove the extra 1×
        normalised = raw_points - adjustment
        miss_reason = None  # determined later by chip miss logic
        return normalised, adjustment, miss_reason

    if chip_canonical in ("bboost", "bench_boost"):
        bench_pts = sum(live_map.get(pid, 0) for pid in bench_ids)
        adjustment = bench_pts
        normalised = raw_points - adjustment
        miss_reason = None
        return normalised, adjustment, miss_reason

    if chip_canonical in ("wildcard", "freehit", "free_hit"):
        # Full squad rebuild — comparison is unreliable
        miss_reason = f"{chip} used — squad restructured this GW, comparison unreliable"
        return raw_points, 0, miss_reason

    # No chip
    return raw_points, 0, None


# ── Core oracle computation ────────────────────────────────────────────────────

async def _compute_oracle(
    team_id: int,
    gameweek_id: int,
    db: AsyncSession,
) -> GWOracle:
    """
    Compute the theoretically best 15-player squad within £100m, unlimited transfers.

    Strategy:
      - £100m (1000 pence) budget — standard FPL starting budget
      - All available players in pool (status='a', predicted_xpts_next available)
      - ILP optimiser with free_transfers=15 (no hit cost)
      - Valid FPL formation (1 GK, 3-5 DEF, 2-5 FWD, rest MID)
      - No wildcard/chip multipliers (pure prediction benchmark)
    """
    import pandas as pd
    from optimizers.squad_optimizer import SquadOptimizer

    optimizer = SquadOptimizer()

    # Fetch all available players
    result = await db.execute(select(Player))
    all_players: list[Player] = result.scalars().all()

    # Filter to available players with valid xPts
    df = pd.DataFrame([{
        "id": p.id,
        "web_name": p.web_name,
        "element_type": p.element_type,
        "team_id": p.team_id,
        "now_cost": p.now_cost,
        "predicted_xpts_next": p.predicted_xpts_next,
        "status": p.status,
        "form": float(p.form or 0),
        "minutes": p.minutes or 0,
    } for p in all_players])

    # Oracle pool: available players with meaningful xPts predictions
    oracle_pool = df[
        (df["status"] == "a") &
        (df["now_cost"] > 0) &
        (df["predicted_xpts_next"].notna()) &
        (df["predicted_xpts_next"] > 0)
    ].copy()

    oracle_pool["predicted_xpts_next"] = oracle_pool["predicted_xpts_next"].clip(upper=14.0)

    # Run ILP: £100m budget, unlimited free transfers → no hit cost
    ORACLE_BUDGET = 1000  # £100.0m in tenths of £1 (FPL pence)
    FREE_TRANSFERS = 15   # Effectively unlimited — no hit cost penalty

    loop = asyncio.get_event_loop()
    ilp_result = await loop.run_in_executor(
        None,
        lambda: optimizer.optimize_squad(
            players_df=oracle_pool,
            budget=ORACLE_BUDGET,
            existing_squad=None,        # no constraint on current squad
            free_transfers=FREE_TRANSFERS,
            wildcard_active=False,      # pure benchmark, no chip bonuses
            bench_boost_active=False,
            triple_captain_active=False,
        ),
    )

    # Enrich oracle result
    player_map = {p.id: p for p in all_players}

    squad_ids = ilp_result.squad        # 15 player IDs
    xi_ids = ilp_result.starting_xi     # 11 player IDs

    oracle_squad_names = [player_map[pid].web_name for pid in squad_ids if pid in player_map]
    oracle_cost = sum(player_map[pid].now_cost for pid in squad_ids if pid in player_map)

    captain = player_map.get(ilp_result.captain_id)

    # Current user squad (algo squad) for comparison
    squad_res = await db.execute(
        select(UserSquad).where(
            and_(
                UserSquad.team_id == team_id,
                UserSquad.gameweek_id == gameweek_id,
            )
        )
    )
    user_picks = squad_res.scalars().all()
    user_squad_ids = [p.player_id for p in user_picks]
    user_xi_ids = [p.player_id for p in user_picks if p.position <= 11]

    # Compute algo xPts (user's current XI vs predictions)
    algo_xpts = sum(
        float(player_map[pid].predicted_xpts_next or 0)
        for pid in user_xi_ids
        if pid in player_map
    )

    # Check if oracle already exists for this (team, gw) — update instead
    existing_res = await db.execute(
        select(GWOracle).where(
            and_(GWOracle.team_id == team_id, GWOracle.gameweek_id == gameweek_id)
        )
    )
    existing = existing_res.scalars().first()

    if existing:
        record = existing
        record.snapshot_taken_at = datetime.utcnow()
    else:
        record = GWOracle(
            team_id=team_id,
            gameweek_id=gameweek_id,
            snapshot_taken_at=datetime.utcnow(),
        )
        db.add(record)

    record.oracle_squad_json = json.dumps(squad_ids)
    record.oracle_xi_json = json.dumps(xi_ids)
    record.oracle_formation = ilp_result.formation
    record.oracle_xpts = round(ilp_result.total_xpts, 2)
    record.oracle_cost = oracle_cost
    record.oracle_captain_id = ilp_result.captain_id
    record.oracle_captain_name = captain.web_name if captain else None
    record.oracle_captain_xpts = float(captain.predicted_xpts_next or 0) if captain else None
    record.oracle_squad_names = json.dumps(oracle_squad_names)
    record.algo_squad_json = json.dumps(user_squad_ids)
    record.algo_xpts = round(algo_xpts, 2)

    await db.commit()
    await db.refresh(record)

    logger.info(
        f"Oracle snapshot: team={team_id} gw={gameweek_id} "
        f"formation={ilp_result.formation} oracle_xpts={ilp_result.total_xpts:.1f} "
        f"algo_xpts={algo_xpts:.1f} captain={captain.web_name if captain else '?'}"
    )

    return record


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/snapshot")
async def take_oracle_snapshot(
    team_context: dict = Depends(get_team_context),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Compute and store the oracle best team for the current GW.
    Takes 2-8 seconds (ILP solve). Called automatically at GW deadline,
    or manually via this endpoint.
    """
    team_id = team_context["team_id"]
    # Get current GW — if finished, use next GW for snapshot
    gw_res = await db.execute(select(Gameweek).where(Gameweek.is_current == True))
    current_gw = gw_res.scalar_one_or_none()
    if not current_gw:
        raise HTTPException(404, "No active gameweek")

    target_gw = current_gw
    if current_gw.finished:
        next_res = await db.execute(select(Gameweek).where(Gameweek.is_next == True))
        next_gw = next_res.scalar_one_or_none()
        if next_gw:
            target_gw = next_gw

    record = await _compute_oracle(team_id, target_gw.id, db)

    return {
        "status": "ok",
        "team_id": team_id,
        "gameweek_id": record.gameweek_id,
        "oracle_formation": record.oracle_formation,
        "oracle_xpts": record.oracle_xpts,
        "oracle_cost_millions": round((record.oracle_cost or 0) / 10, 1),
        "oracle_captain": {
            "name": record.oracle_captain_name,
            "xpts": record.oracle_captain_xpts,
        },
        "algo_xpts": record.algo_xpts,
        "oracle_vs_algo_gap": round((record.oracle_xpts or 0) - (record.algo_xpts or 0), 2),
        "oracle_squad": json.loads(record.oracle_squad_names or "[]"),
        "snapshot_taken_at": record.snapshot_taken_at.isoformat(),
    }


@router.get("/history")
async def get_oracle_history(
    team_context: dict = Depends(get_team_context),
    limit: int = Query(10, le=38),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Fetch oracle snapshots for the given team, newest first.
    After a GW resolves, actual_oracle_points and actual_algo_points
    are filled so you can see how the algo performed in real life.
    """
    team_id = team_context["team_id"]
    session = team_context.get("session")
    cached = await get_cached_payload("oracle_history", team_id, limit, session.session_token if session else "registered")
    if cached:
        cached["analysis_mode"] = "cached"
        return cached

    res = await db.execute(
        select(GWOracle)
        .where(GWOracle.team_id == team_id)
        .order_by(GWOracle.gameweek_id.desc())
        .limit(limit)
    )
    records: list[GWOracle] = res.scalars().all()

    # Collect all player IDs across all snapshots so we can bulk-load team info
    all_squad_ids: set[int] = set()
    for r in records:
        ids = json.loads(r.oracle_squad_json or "[]")
        all_squad_ids.update(ids)

    from models.db.team import Team
    player_team_map: dict[int, dict] = {}
    gameweek_meta: dict[int, dict] = {}
    user_gw_points: dict[int, int] = {}
    if all_squad_ids:
        player_res = await db.execute(
            select(Player, Team)
            .join(Team, Player.team_id == Team.id, isouter=True)
            .where(Player.id.in_(all_squad_ids))
        )
        for p, t in player_res.all():
            player_team_map[p.id] = {
                "web_name": p.web_name,
                "team_code": t.code if t else None,
                "team_short_name": t.short_name if t else None,
                "element_type": p.element_type,  # 1=GK 2=DEF 3=MID 4=FWD
            }
    gw_res = await db.execute(
        select(Gameweek).where(Gameweek.id.in_([r.gameweek_id for r in records]))
    )
    for gw in gw_res.scalars().all():
        gameweek_meta[gw.id] = {
            "highest_score": gw.highest_score,
            "finished": gw.finished,
        }
    user_hist_res = await db.execute(
        select(UserGWHistory).where(
            and_(
                UserGWHistory.team_id == team_id,
                UserGWHistory.gw_id.in_([r.gameweek_id for r in records]),
            )
        )
    )
    for hist in user_hist_res.scalars().all():
        user_gw_points[hist.gw_id] = hist.points

    def _fmt(r: GWOracle) -> dict:
        oracle_names = json.loads(r.oracle_squad_names or "[]")
        squad_ids = json.loads(r.oracle_squad_json or "[]")
        xi_ids = json.loads(r.oracle_xi_json or "[]") if r.oracle_xi_json else squad_ids[:11]
        # Sort xi_ids by element_type (GK→DEF→MID→FWD) so formation distribution is correct
        xi_ids_sorted = sorted(
            xi_ids[:11],
            key=lambda pid: player_team_map.get(pid, {}).get("element_type", 3),
        )
        # Build enriched XI list with team info for badge display
        oracle_squad_with_teams = []
        for pid in xi_ids_sorted:
            info = player_team_map.get(pid, {})
            oracle_squad_with_teams.append({
                "name": info.get("web_name", str(pid)),
                "team_code": info.get("team_code"),
                "team_short_name": info.get("team_short_name"),
                "element_type": info.get("element_type", 3),
            })
        missed = json.loads(r.missed_players_json or "[]")
        blind_spots = json.loads(r.oracle_blind_spots_json or "{}")
        fallback_highest_score = (gameweek_meta.get(r.gameweek_id) or {}).get("highest_score")
        fallback_top_points = r.top_team_points if r.top_team_points is not None else fallback_highest_score
        fallback_algo_points = r.actual_algo_points if r.actual_algo_points is not None else user_gw_points.get(r.gameweek_id)
        fallback_status = getattr(r, "top_team_status", None) or ("partial" if fallback_top_points is not None else "unavailable")
        return {
            "gameweek_id": r.gameweek_id,
            "oracle_formation": r.oracle_formation,
            "oracle_xpts": r.oracle_xpts,
            "oracle_cost_millions": round((r.oracle_cost or 0) / 10, 1),
            "oracle_captain": {
                "name": r.oracle_captain_name,
                "xpts": r.oracle_captain_xpts,
            },
            "oracle_squad": oracle_names[:11],  # backward-compat list of names
            "oracle_squad_with_teams": oracle_squad_with_teams,  # enriched with team_code
            "algo_xpts": r.algo_xpts,
            "gap_xpts": round((r.oracle_xpts or 0) - (r.algo_xpts or 0), 2),
            # Post-GW resolution
            "actual_oracle_points": r.actual_oracle_points,
            "actual_algo_points": fallback_algo_points,
            "oracle_beat_algo": r.oracle_beat_algo,
            "resolved": r.resolved_at is not None,
            "snapshot_taken_at": r.snapshot_taken_at.isoformat() if r.snapshot_taken_at else None,
            # Top FPL team comparison
            "top_team": {
                "team_id": r.top_team_id,
                "team_name": r.top_team_name or ("GW Top Score" if fallback_top_points is not None else None),
                "points": fallback_top_points,
                "points_normalised": r.top_team_points_normalized,
                "chip_adjustment": r.top_team_chip_adjustment,
                "squad": json.loads(r.top_team_squad_json or "[]"),
                "captain": r.top_team_captain,
                "chip": r.top_team_chip,
                "chip_miss_reason": r.chip_miss_reason,
                "status": fallback_status,
                "display_points": (
                    r.top_team_points_normalized
                    if r.top_team_points_normalized is not None
                    else fallback_top_points
                    if fallback_top_points is not None
                    else "Data unavailable"
                ),
            } if (
                r.top_team_id is not None
                or fallback_top_points is not None
                or getattr(r, "top_team_status", None) is not None
            ) else None,
            "oracle_beat_top": r.oracle_beat_top,
            "missed_players": missed,
            "blind_spots": blind_spots,
            "analysis_mode": "full",
            "session_expires_at": session.expires_at.isoformat() if session else None,
        }

    payload = {
        "team_id": team_id,
        "total": len(records),
        "snapshots": [_fmt(r) for r in records],
    }
    await set_cached_payload("oracle_history", payload, ANALYSIS_TTL, team_id, limit, session.session_token if session else "registered")
    return payload


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8), reraise=True)
async def _fetch_json(client, url: str, *, params: dict | None = None) -> dict:
    response = await client.get(url, params=params, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    return response.json()


@router.post("/auto-resolve")
async def auto_resolve_oracle(
    team_id: int = Query(...),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Auto-resolve all unresolved oracle snapshots for finished GWs.
    Fetches actual GW points from FPL live API for both oracle XI and user squad.
    """
    import httpx

    # 1. Get all finished GWs
    gw_res = await db.execute(select(Gameweek).where(Gameweek.finished == True))
    finished_gw_ids = {gw.id for gw in gw_res.scalars().all()}

    # 2. Get all unresolved snapshots for this team
    snap_res = await db.execute(
        select(GWOracle).where(
            and_(
                GWOracle.team_id == team_id,
                GWOracle.resolved_at.is_(None),
            )
        )
    )
    unresolved = [
        s
        for s in snap_res.scalars().all()
        if s.gameweek_id in finished_gw_ids
        and (
            s.resolved_at is None
            or s.actual_oracle_points is None
            or s.actual_algo_points is None
            or s.top_team_points is None
            or not s.top_team_squad_json
            or getattr(s, "top_team_status", None) in (None, "", "unavailable")
        )
    ]

    if not unresolved:
        return {"resolved": 0, "message": "No unresolved snapshots for finished GWs", "details": []}

    resolved_list = []
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        for snapshot in unresolved:
            gw_id = snapshot.gameweek_id
            try:
                # Fetch FPL live data for this GW
                try:
                    live_payload = await _fetch_json(
                        client,
                        f"https://fantasy.premierleague.com/api/event/{gw_id}/live/",
                    )
                except Exception as live_exc:
                    logger.warning(f"auto-resolve: FPL live/{gw_id} fetch failed: {live_exc}")
                    continue
                live_map: dict[int, int] = {
                    e["id"]: e["stats"]["total_points"]
                    for e in live_payload.get("elements", [])
                }

                # Compute oracle XI actual points (captain 2× unless 3xc, use raw for fair comparison)
                oracle_xi_ids: list[int] = json.loads(snapshot.oracle_xi_json or "[]")[:11]
                oracle_captain_id = snapshot.oracle_captain_id
                oracle_actual = sum(live_map.get(pid, 0) for pid in oracle_xi_ids)
                # Oracle captain always gets 2× (no TC chip for oracle benchmark)
                if oracle_captain_id and oracle_captain_id in live_map:
                    oracle_actual += live_map[oracle_captain_id]  # extra 1× for captain

                # Fetch user squad picks for this GW from FPL API (handles captain multiplier)
                try:
                    picks_data = await _fetch_json(
                        client,
                        f"https://fantasy.premierleague.com/api/entry/{team_id}/event/{gw_id}/picks/",
                    )
                    picks = picks_data.get("picks", [])
                    active_chip = picks_data.get("active_chip") or ""
                    algo_actual = 0
                    for p in picks:
                        if p.get("position", 12) > 11:
                            continue  # bench player
                        raw_pts = live_map.get(p["element"], 0)
                        mult = p.get("multiplier", 1)
                        # TC chip gives 3× captain, regular captain 2×
                        if active_chip == "3xc" and p.get("is_captain"):
                            mult = 3
                        algo_actual += raw_pts * mult
                except Exception:
                    # No historical picks available — use stored algo squad
                    algo_squad_ids: list[int] = json.loads(snapshot.algo_squad_json or "[]")
                    algo_actual = sum(live_map.get(pid, 0) for pid in algo_squad_ids[:11])

                snapshot.actual_oracle_points = round(float(oracle_actual), 1)
                snapshot.actual_algo_points = round(float(algo_actual), 1)
                snapshot.oracle_beat_algo = oracle_actual > algo_actual
                snapshot.resolved_at = datetime.utcnow()

                # ── Fetch top FPL team for this GW and learn from it ──────────
                try:
                    # Multi-page standings scan — top 250 entries (5 pages × 50)
                    # Finds the true GW top scorer, not just the top-50-overall top scorer
                    top_tid, top_name, top_pts = 0, "Unknown", 0
                    top_team_status = "unavailable"
                    try:
                        for _page in range(1, 6):
                            _page_data = await _fetch_json(
                                client,
                                "https://fantasy.premierleague.com/api/leagues-classic/314/standings/",
                                params={"page_standings": _page},
                            )
                            standings = _page_data.get("standings", {})
                            _entries = standings.get("results", [])
                            for _e in _entries:
                                if _e.get("event_total", 0) > top_pts:
                                    top_pts = _e["event_total"]
                                    top_tid = _e["entry"]
                                    top_name = _e.get("entry_name", "Unknown")
                            if not standings.get("has_next", False):
                                break
                        if top_tid:
                            top_team_status = "ok"
                    except Exception as _fetch_exc:
                        logger.warning(f"top-team standings fetch failed GW{gw_id}: {_fetch_exc}")
                        top_team_status = "unavailable"

                    if top_tid:
                        top_entry = {"entry": top_tid, "entry_name": top_name, "event_total": top_pts}
                    else:
                        top_entry = None

                    if top_entry:

                            # Fetch their GW picks
                            top_chip = None
                            top_captain_name = None
                            top_player_names: list[str] = []
                            missed_players: list[str] = []

                            try:
                                top_data = await _fetch_json(
                                    client,
                                    f"https://fantasy.premierleague.com/api/entry/{top_tid}/event/{gw_id}/picks/",
                                )
                                top_chip = top_data.get("active_chip")
                                top_picks = top_data.get("picks", [])
                                xi_pids = [p["element"] for p in top_picks if p.get("position", 12) <= 11]
                                cap_id = next(
                                    (p["element"] for p in top_picks if p.get("is_captain")), None
                                )

                                # Map player IDs to names using live data + DB
                                pid_to_name: dict[int, str] = {}
                                for e in live_payload.get("elements", []):
                                    pid_to_name[e["id"]] = e.get("web_name", str(e["id"]))

                                top_player_names = [pid_to_name.get(pid, str(pid)) for pid in xi_pids]
                                top_captain_name = pid_to_name.get(cap_id, "") if cap_id else None

                                # Players top team had that Oracle missed
                                oracle_xi_set = set(oracle_xi_ids)
                                missed_pids = [pid for pid in xi_pids if pid not in oracle_xi_set]
                                missed_players = [pid_to_name.get(pid, str(pid)) for pid in missed_pids]
                                top_team_status = "ok"
                            except Exception as top_picks_exc:
                                logger.warning(f"top-team picks fetch failed GW{gw_id}: {top_picks_exc}")
                                top_data = {"picks": []}
                                top_picks = []
                                top_team_status = "unavailable"

                            # ── Chip normalisation ─────────────────────────────────────
                            top_bench_ids: list[int] = [
                                p["element"] for p in top_picks if p.get("position", 0) > 11
                            ] if top_picks else []

                            top_cap_id = next(
                                (p["element"] for p in top_data.get("picks", []) if p.get("is_captain")),
                                None,
                            )

                            top_pts_normalised, chip_adjustment, chip_wc_reason = _normalise_chip_score(
                                raw_points=top_pts,
                                chip=top_chip,
                                live_map=live_map,
                                captain_id=top_cap_id,
                                bench_ids=top_bench_ids,
                            )

                            # Chip miss reason: did Oracle's chip engine miss this chip?
                            chip_miss_reason = chip_wc_reason  # WC/FH already has a reason
                            if chip_miss_reason is None:
                                oracle_cap_xpts = snapshot.oracle_captain_xpts or 0.0
                                chip_canonical = (top_chip or "").lower().strip()
                                if chip_canonical in ("3xc", "triple_captain"):
                                    if oracle_cap_xpts >= 7.0:
                                        chip_miss_reason = (
                                            f"TC threshold met (oracle_captain_xpts={oracle_cap_xpts:.1f} ≥ 7.0) "
                                            f"— TC was not recommended but should have been"
                                        )
                                    else:
                                        chip_miss_reason = (
                                            f"TC not triggered: oracle_captain_xpts={oracle_cap_xpts:.1f} < 7.0 threshold "
                                            f"— threshold may need lowering"
                                        )
                                elif chip_canonical in ("bboost", "bench_boost"):
                                    chip_miss_reason = (
                                        "BB used by top team — Oracle had no bench players tracked for BB value"
                                    )

                            snapshot.top_team_id = top_tid
                            snapshot.top_team_name = top_name
                            snapshot.top_team_points = top_pts
                            if hasattr(snapshot, "top_team_status"):
                                snapshot.top_team_status = top_team_status
                            snapshot.top_team_squad_json = json.dumps(top_player_names)
                            snapshot.top_team_captain = top_captain_name
                            snapshot.top_team_chip = top_chip
                            snapshot.top_team_points_normalized = top_pts_normalised
                            snapshot.top_team_chip_adjustment = chip_adjustment
                            snapshot.chip_miss_reason = chip_miss_reason
                            snapshot.oracle_beat_top = oracle_actual >= top_pts_normalised
                            snapshot.missed_players_json = json.dumps(missed_players)

                            # Run ML learner — accumulate blind spots + adjust feature bias
                            try:
                                from agents.oracle_learner import OracleLearner
                                oracle_names_xi = [pid_to_name.get(pid, str(pid)) for pid in oracle_xi_ids]
                                learner = OracleLearner()
                                blind_spots = learner.record_gw_result(
                                    gw_id=gw_id,
                                    oracle_pts=oracle_actual,
                                    top_team_pts=top_pts_normalised,  # compare to normalised score
                                    missed_players=missed_players,
                                    top_chip=top_chip,
                                    oracle_xi=oracle_names_xi,
                                    top_xi=top_player_names,
                                    chip_miss_reason=chip_miss_reason,
                                )
                                snapshot.oracle_blind_spots_json = json.dumps(blind_spots)
                            except Exception as learn_exc:
                                logger.warning(f"oracle learner error GW{gw_id}: {learn_exc}")
                                snapshot.oracle_blind_spots_json = json.dumps({
                                    "missed": missed_players,
                                    "insight": f"Oracle missed: {', '.join(missed_players[:5])}"
                                })
                                logger.info(
                                    f"auto-resolve GW{gw_id}: top_team={top_name} pts={top_pts} "
                                    f"normalised={top_pts_normalised} chip={top_chip} "
                                    f"oracle_beat_top={snapshot.oracle_beat_top} missed={missed_players[:3]}"
                                )
                except Exception as top_exc:
                    logger.warning(f"auto-resolve top-team fetch failed GW{gw_id}: {top_exc}")

                resolved_list.append({
                    "gameweek_id": gw_id,
                    "oracle_actual": snapshot.actual_oracle_points,
                    "algo_actual": snapshot.actual_algo_points,
                    "oracle_beat_algo": snapshot.oracle_beat_algo,
                    "top_team_pts": snapshot.top_team_points,
                    "top_team_pts_normalised": snapshot.top_team_points_normalized,
                    "chip": snapshot.top_team_chip,
                    "chip_adjustment": snapshot.top_team_chip_adjustment,
                    "chip_miss_reason": snapshot.chip_miss_reason,
                    "oracle_beat_top": snapshot.oracle_beat_top,
                    "missed_players": json.loads(snapshot.missed_players_json or "[]"),
                })
                logger.info(
                    f"auto-resolve GW{gw_id}: oracle={snapshot.actual_oracle_points} "
                    f"algo={snapshot.actual_algo_points} team={team_id}"
                )
            except Exception as exc:
                logger.warning(f"auto-resolve failed for GW{gw_id}: {exc}")
                continue

    await db.commit()
    await invalidate_cache_prefix("oracle_history")

    # ── Wire decision log rewards ──────────────────────────────────────────
    try:
        from rl.resolve_decisions import resolve_gw_decisions
        for detail in resolved_list:
            gw_id_resolved = detail.get("gameweek_id")
            chip_played = detail.get("chip")
            if gw_id_resolved:
                await resolve_gw_decisions(
                    team_id=team_id,
                    gw_id=gw_id_resolved,
                    db=db,
                    chip_played=chip_played,
                )
    except Exception as _reward_exc:
        logger.warning(f"Decision reward resolution failed: {_reward_exc}")

    return {
        "resolved": len(resolved_list),
        "team_id": team_id,
        "details": resolved_list,
    }


@router.post("/resolve")
async def resolve_oracle(
    req: OracleResolveRequest,
    db: AsyncSession = Depends(get_db_session),
):
    """
    After a GW completes, fill actual points for the oracle and algo squads.
    Called by the data pipeline's post-GW resolver.
    """
    res = await db.execute(
        select(GWOracle).where(
            and_(
                GWOracle.team_id == req.team_id,
                GWOracle.gameweek_id == req.gameweek_id,
            )
        )
    )
    record = res.scalars().first()
    if not record:
        raise HTTPException(404, f"No oracle snapshot for team={req.team_id} gw={req.gameweek_id}")

    if req.oracle_actual_points is not None:
        record.actual_oracle_points = req.oracle_actual_points
    if req.algo_actual_points is not None:
        record.actual_algo_points = req.algo_actual_points
    if record.actual_oracle_points is not None and record.actual_algo_points is not None:
        record.oracle_beat_algo = record.actual_oracle_points > record.actual_algo_points
    record.resolved_at = datetime.utcnow()

    await db.commit()
    return {
        "updated": True,
        "gameweek_id": req.gameweek_id,
        "oracle_actual": record.actual_oracle_points,
        "algo_actual": record.actual_algo_points,
        "oracle_beat_algo": record.oracle_beat_algo,
    }


@router.get("/learning-summary")
async def get_oracle_learning_summary():
    """
    Returns the Oracle learner's accumulated insights:
    - Win rate vs top FPL team
    - Chronic blind-spot players
    - Feature bias adjustments made
    """
    try:
        from agents.oracle_learner import OracleLearner
        learner = OracleLearner()
        return learner.get_summary()
    except Exception as e:
        return {"error": str(e), "gws_analysed": 0}

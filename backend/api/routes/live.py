"""Live scoring routes."""
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from api.deps import get_db_session
from core.config import settings
from core.redis_client import cache_get_json
from models.db.gameweek import Gameweek
from models.db.player import Player
from models.db.team import Team

router = APIRouter()


@router.get("/score")
async def get_live_score(
    request: Request,
    team_id: int | None = None,
    db: AsyncSession = Depends(get_db_session),
):
    """
    Live GW points for your squad.
    Always pulls the SUBMITTED squad directly from the FPL API (not DB)
    so that pre-kickoff transfers are reflected immediately without needing
    a manual sync. Live scoring data comes from the Redis cache (updated
    every 60s by the scheduler's live-polling job).
    """
    active_team_id = team_id or settings.FPL_TEAM_ID
    if not active_team_id:
        raise HTTPException(400, "No team_id provided")

    result = await db.execute(select(Gameweek).where(Gameweek.is_current == True))
    current_gw = result.scalar_one_or_none()
    if not current_gw:
        raise HTTPException(404, "No active gameweek")

    # Between GWs: current is finished but next hasn't kicked off yet.
    if current_gw.finished:
        next_result = await db.execute(select(Gameweek).where(Gameweek.is_next == True))
        next_gw = next_result.scalar_one_or_none()
        upcoming_id = next_gw.id if next_gw else current_gw.id + 1
        raise HTTPException(
            404,
            f"GW{current_gw.id} has ended. GW{upcoming_id} hasn't kicked off yet.",
        )

    # ── 1. Pull live scoring data from Redis (populated by live polling job) ──
    live_key = f"fpl:live:{current_gw.id}:prev"
    live_data = await cache_get_json(live_key) or {}

    # Fallback: if Redis has no live data, fetch directly from FPL live endpoint.
    # Root cause of live=0 bug: FPL API returns elements as a LIST, but the scheduler
    # was calling .items() on it (only valid for dicts) and silently crashing,
    # so Redis was never populated. This fallback bypasses cache and hits FPL directly.
    if not live_data:
        try:
            from core.redis_client import cache_set_json as _cache_set
            _base = "https://fantasy.premierleague.com/api"
            # Use the shared http_client from app state if available
            _shared = getattr(request.app.state, "http_client", None)
            if _shared:
                _resp = await _shared.get(
                    f"{_base}/event/{current_gw.id}/live/",
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                fallback_raw = _resp.json()
            else:
                async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as _c:
                    _r = await _c.get(
                        f"{_base}/event/{current_gw.id}/live/",
                        headers={"User-Agent": "Mozilla/5.0"},
                    )
                    _r.raise_for_status()
                    fallback_raw = _r.json()

            # FPL returns elements as a LIST: [{id, stats, explain, modified}, ...]
            raw_elements = fallback_raw.get("elements", [])
            if isinstance(raw_elements, list):
                elements_dict = {str(el["id"]): el for el in raw_elements if "id" in el}
            else:
                elements_dict = raw_elements  # dict (unlikely but safe)

            if elements_dict:
                live_data = {
                    pid: {
                        "total_points": el.get("stats", {}).get("total_points", 0),
                        "minutes": el.get("stats", {}).get("minutes", 0),
                        "goals_scored": el.get("stats", {}).get("goals_scored", 0),
                        "assists": el.get("stats", {}).get("assists", 0),
                        "bonus": el.get("stats", {}).get("bonus", 0),
                    }
                    for pid, el in elements_dict.items()
                }
                # Warm Redis so scheduler picks up from here on next poll
                await _cache_set(live_key, live_data, ttl=65)
        except Exception:
            pass  # live_data stays empty — live_data_available=False in response

    # ── 2. Always fetch the REAL submitted picks from FPL API ─────────────────
    # This ensures we always use the up-to-date squad even if the DB is stale
    # (e.g. user made pre-deadline transfers that haven't been synced yet).
    from agents.fpl_agent import FPLAgent
    http_client = getattr(request.app.state, "http_client", None)
    if not http_client:
        http_client = httpx.AsyncClient(timeout=15.0, follow_redirects=True)

    agent = FPLAgent(http_client)
    try:
        picks_data = await agent.get_picks(active_team_id, current_gw.id)
        raw_picks = picks_data.get("picks", [])
    except Exception:
        # FPL API unavailable — fall back to DB squad
        from models.db.user_squad import UserSquad
        result = await db.execute(
            select(UserSquad).where(
                UserSquad.team_id == active_team_id,
                UserSquad.gameweek_id == current_gw.id,
            )
        )
        db_picks = result.scalars().all()
        if not db_picks:
            raise HTTPException(404, "Squad not found for current GW. Please sync first.")
        raw_picks = [
            {
                "element": p.player_id,
                "position": p.position,
                "is_captain": p.is_captain,
                "is_vice_captain": p.is_vice_captain,
                "multiplier": p.multiplier,
            }
            for p in db_picks
        ]

    if not raw_picks:
        raise HTTPException(404, "No picks found for current GW")

    # ── 3. Resolve player names and team info from DB ─────────────────────────
    player_ids = [p["element"] for p in raw_picks]
    players_result = await db.execute(
        select(Player, Team)
        .join(Team, Player.team_id == Team.id, isouter=True)
        .where(Player.id.in_(player_ids))
    )
    player_map: dict[int, dict] = {}
    for player, team in players_result.all():
        player_map[player.id] = {
            "web_name": player.web_name,
            "team_short_name": team.short_name if team else None,
            "team_code": team.code if team else None,
            "element_type": player.element_type,
        }

    # ── 4. Cross-reference picks with live scoring data ───────────────────────
    squad_live = []
    total_live_pts = 0

    for pick in sorted(raw_picks, key=lambda p: p["position"]):
        player_id = pick["element"]
        player_live = live_data.get(str(player_id), {})
        live_pts = player_live.get("total_points", 0)
        multiplier = pick.get("multiplier", 1)
        effective_pts = live_pts * multiplier
        p_info = player_map.get(player_id, {})
        # Handle both Redis scheduler format (only total_points) and direct-fetch format
        minutes = player_live.get("minutes", 0)
        goals = player_live.get("goals_scored", player_live.get("goals", 0))
        assists = player_live.get("assists", 0)
        bonus = player_live.get("bonus", 0)

        squad_live.append({
            "player_id": player_id,
            "web_name": p_info.get("web_name") or str(player_id),
            "team_short_name": p_info.get("team_short_name"),
            "team_code": p_info.get("team_code"),
            "element_type": p_info.get("element_type"),
            "position": pick["position"],
            "is_captain": pick.get("is_captain", False),
            "is_vice_captain": pick.get("is_vice_captain", False),
            "multiplier": multiplier,
            "live_points": live_pts,
            "effective_points": effective_pts,
            "playing": live_pts > 0,
            "minutes": minutes,
            "goals": goals,
            "assists": assists,
            "bonus": bonus,
        })

        if multiplier > 0:  # Starting XI (multiplier=0 means bench/unused)
            total_live_pts += effective_pts

    return {
        "gameweek": current_gw.id,
        "total_live_points": total_live_pts,
        "squad": squad_live,
        "live_data_available": bool(live_data),
        "last_updated_key": live_key,
    }


@router.get("/autosubs")
async def get_autosub_predictions(
    team_id: int | None = None,
    db: AsyncSession = Depends(get_db_session),
):
    """
    Predict likely autosub changes: players with 0 minutes at ~60min
    are flagged for substitution by a bench player.
    Formation must remain valid after sub.
    """
    active_team_id = team_id or settings.FPL_TEAM_ID

    result = await db.execute(select(Gameweek).where(Gameweek.is_current == True))
    current_gw = result.scalar_one_or_none()
    if not current_gw:
        return {"autosubs": []}

    live_key = f"fpl:live:{current_gw.id}:prev"
    live_data = await cache_get_json(live_key) or {}

    result = await db.execute(
        select(UserSquad).where(
            UserSquad.team_id == active_team_id,
            UserSquad.gameweek_id == current_gw.id,
        )
    )
    picks = result.scalars().all()
    if not picks:
        return {"autosubs": []}

    # Separate starting XI (position 1-11) from bench (12-15)
    starters = [p for p in picks if p.position <= 11]
    bench = sorted([p for p in picks if p.position > 11], key=lambda p: p.position)

    # Fetch player details
    all_ids = [p.player_id for p in picks]
    players_map: dict[int, Player] = {}
    for pid in all_ids:
        pl = await db.get(Player, pid)
        if pl:
            players_map[pid] = pl

    # Find starters with 0 minutes who appear to have played (live data populated)
    autosubs = []
    for starter in starters:
        live_info = live_data.get(str(starter.player_id), {})
        # If live data exists (GW active) and minutes=0 → candidate for sub
        if live_data and live_info.get("total_points", -1) == 0:
            starter_player = players_map.get(starter.player_id)
            if not starter_player:
                continue
            starter_type = starter_player.element_type  # 1=GK, 2=DEF, 3=MID, 4=FWD

            # Find eligible bench sub
            for bench_pick in bench:
                bench_player = players_map.get(bench_pick.player_id)
                if not bench_player:
                    continue
                bench_live = live_data.get(str(bench_pick.player_id), {})
                bench_pts = bench_live.get("total_points", 0)

                # GK sub: bench GK must replace starter GK
                if starter_type == 1 and bench_player.element_type != 1:
                    continue
                if starter_type != 1 and bench_player.element_type == 1:
                    continue

                # Check sub is actually playing
                if bench_pts > 0:
                    autosubs.append({
                        "out_player_id": starter.player_id,
                        "out_player_name": starter_player.web_name,
                        "in_player_id": bench_pick.player_id,
                        "in_player_name": bench_player.web_name,
                        "bench_position": bench_pick.position,
                        "bench_live_points": bench_pts,
                        "reason": "Starter at 0 minutes while bench player is active",
                    })
                    break  # Only first eligible sub per starter

    return {"gameweek": current_gw.id, "autosubs": autosubs}

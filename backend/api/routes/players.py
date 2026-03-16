"""Player search, detail, and watchlist routes."""
from fastapi import APIRouter, Depends, Query, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from pydantic import BaseModel
import statistics

from api.deps import get_db_session
from core.redis_client import cache_get_json, cache_set_json
from models.db.player import Player
from models.db.gameweek import Gameweek
from models.db.team import Team
from agents.fpl_agent import FPL_BASE

router = APIRouter()

WATCHLIST_KEY = "fpl:watchlist:{team_id}"


class WatchlistRequest(BaseModel):
    player_id: int


def _player_to_dict(p: Player, team: "Team | None" = None) -> dict:
    return {
        "id": p.id,
        "web_name": p.web_name,
        "element_type": p.element_type,
        "team_id": p.team_id,
        "team_short_name": team.short_name if team else None,
        "team_code": team.code if team else None,
        "now_cost": p.now_cost,
        "selected_by_percent": p.selected_by_percent,
        "form": p.form,
        "status": p.status,
        "news": p.news,
        "chance_of_playing_next_round": p.chance_of_playing_next_round,
        "xg_per_90": p.xg_per_90,
        "xa_per_90": p.xa_per_90,
        "npxg_per_90": p.npxg_per_90,
        "predicted_xpts_next": (
            min(p.predicted_xpts_next, 14.0) if p.predicted_xpts_next is not None else None
        ),
        "predicted_start_prob": p.predicted_start_prob,
        "predicted_price_direction": p.predicted_price_direction,
        "fdr_next": p.fdr_next,
        "is_home_next": p.is_home_next,
        "has_blank_gw": p.has_blank_gw,
        "has_double_gw": p.has_double_gw,
        "form_trend": p.form_trend,
        "suspension_risk": p.suspension_risk,
    }


@router.get("/")
async def list_players(
    search: str | None = Query(None, description="Search by name"),
    element_type: int | None = Query(None, description="1=GK, 2=DEF, 3=MID, 4=FWD"),
    min_xpts: float | None = Query(None),
    max_cost: int | None = Query(None, description="Max cost in pence (e.g. 90 = £9.0m)"),
    blank_only: bool = Query(False),
    double_only: bool = Query(False),
    suspension_risk: bool = Query(False),
    limit: int = Query(50, le=300),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db_session),
):
    """List players with optional filters."""
    query = select(Player)

    if search:
        query = query.where(Player.web_name.ilike(f"%{search}%"))
    if element_type:
        query = query.where(Player.element_type == element_type)
    if min_xpts is not None:
        query = query.where(Player.predicted_xpts_next >= min_xpts)
    if max_cost is not None:
        query = query.where(Player.now_cost <= max_cost * 10)  # pence
    if blank_only:
        query = query.where(Player.has_blank_gw == True)
    if double_only:
        query = query.where(Player.has_double_gw == True)
    if suspension_risk:
        query = query.where(Player.suspension_risk == True)

    query = (
        query
        .order_by(Player.predicted_xpts_next.desc().nullslast())
        .limit(limit)
        .offset(offset)
    )

    result = await db.execute(query)
    players = result.scalars().all()

    # Load teams in one query
    team_ids = {p.team_id for p in players}
    teams_result = await db.execute(select(Team).where(Team.id.in_(team_ids)))
    team_map = {t.id: t for t in teams_result.scalars().all()}

    return [_player_to_dict(p, team_map.get(p.team_id)) for p in players]


@router.get("/watchlist")
async def get_watchlist(
    team_id: int | None = None,
    db: AsyncSession = Depends(get_db_session),
):
    """Get saved player watchlist (stored in Redis)."""
    from core.config import settings
    active_team_id = team_id or settings.FPL_TEAM_ID
    key = WATCHLIST_KEY.format(team_id=active_team_id)
    player_ids = await cache_get_json(key) or []

    players = []
    for pid in player_ids:
        player = await db.get(Player, pid)
        if player:
            players.append(_player_to_dict(player))

    return {"team_id": active_team_id, "watchlist": players}


@router.post("/watchlist")
async def add_to_watchlist(
    body: WatchlistRequest,
    team_id: int | None = None,
):
    """Add a player to the watchlist."""
    from core.config import settings
    active_team_id = team_id or settings.FPL_TEAM_ID
    key = WATCHLIST_KEY.format(team_id=active_team_id)

    player_ids = await cache_get_json(key) or []
    if body.player_id not in player_ids:
        player_ids.append(body.player_id)
        await cache_set_json(key, player_ids, ttl=86400 * 30)  # 30 days

    return {"status": "added", "player_id": body.player_id}


@router.delete("/watchlist/{player_id}")
async def remove_from_watchlist(
    player_id: int,
    team_id: int | None = None,
):
    """Remove a player from the watchlist."""
    from core.config import settings
    active_team_id = team_id or settings.FPL_TEAM_ID
    key = WATCHLIST_KEY.format(team_id=active_team_id)

    player_ids = await cache_get_json(key) or []
    player_ids = [pid for pid in player_ids if pid != player_id]
    await cache_set_json(key, player_ids, ttl=86400 * 30)

    return {"status": "removed", "player_id": player_id}


@router.get("/{player_id}/history")
async def get_player_history(
    player_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """
    Fetch real GW-by-GW minutes, points, and stats from FPL element-summary API.
    Returns last 10 GW history + computed rotation metrics.
    Cached in Redis for 30 min so we don't hammer FPL API.
    """
    CACHE_KEY = f"fpl:player_history:{player_id}"
    cached = await cache_get_json(CACHE_KEY)
    if cached:
        return cached

    # Fetch from FPL element-summary
    http_client = getattr(request.app.state, "http_client", None)
    if not http_client:
        raise HTTPException(503, "HTTP client not available")

    try:
        resp = await http_client.get(f"{FPL_BASE}/element-summary/{player_id}/")
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        raise HTTPException(502, f"FPL API error: {e}")

    history = data.get("history", [])

    # Last 10 GW appearances
    recent = history[-10:] if len(history) > 10 else history

    gw_stats = []
    for gw in recent:
        gw_stats.append({
            "gw": gw.get("round"),
            "minutes": gw.get("minutes", 0),
            "points": gw.get("total_points", 0),
            "goals": gw.get("goals_scored", 0),
            "assists": gw.get("assists", 0),
            "was_home": gw.get("was_home", None),
            "opponent_team": gw.get("opponent_team", None),
            "started": gw.get("minutes", 0) >= 45,
        })

    # Rotation risk metrics
    all_minutes = [g["minutes"] for g in gw_stats]
    recent5 = all_minutes[-5:] if len(all_minutes) >= 5 else all_minutes
    avg_minutes_last5 = round(sum(recent5) / len(recent5), 1) if recent5 else 0
    avg_minutes_season = round(sum(all_minutes) / len(all_minutes), 1) if all_minutes else 0
    starts_last5 = sum(1 for m in recent5 if m >= 45)
    # Variance in minutes → rotation risk (high variance = manager rotates)
    rotation_risk: str
    if len(recent5) >= 3:
        try:
            stdev = statistics.stdev(recent5)
        except statistics.StatisticsError:
            stdev = 0
        if avg_minutes_last5 < 30:
            rotation_risk = "HIGH"
        elif stdev > 25 or avg_minutes_last5 < 55:
            rotation_risk = "MEDIUM"
        else:
            rotation_risk = "LOW"
    else:
        rotation_risk = "UNKNOWN"

    # Manager nuance: how consistent is playing time? Spot rotation patterns
    full90s = sum(1 for m in recent5 if m >= 88)
    sub_appearances = sum(1 for m in recent5 if 0 < m < 45)
    manager_note = None
    if sub_appearances >= 2:
        manager_note = f"Frequently used as a substitute ({sub_appearances} of last {len(recent5)} games)"
    elif full90s == len(recent5) and len(recent5) >= 3:
        manager_note = f"Guaranteed starter — played full 90 in all {full90s} recent games"
    elif rotation_risk == "HIGH":
        manager_note = "Manager rotates heavily — low avg minutes this season"

    result = {
        "player_id": player_id,
        "gw_history": gw_stats,
        "avg_minutes_last5": avg_minutes_last5,
        "avg_minutes_season": avg_minutes_season,
        "starts_last5": starts_last5,
        "rotation_risk": rotation_risk,
        "manager_note": manager_note,
    }
    await cache_set_json(CACHE_KEY, result, ttl=1800)  # 30 min cache
    return result


@router.get("/{player_id}")
async def get_player(
    player_id: int,
    db: AsyncSession = Depends(get_db_session),
):
    """Get single player details."""
    player = await db.get(Player, player_id)
    if not player:
        raise HTTPException(404, "Player not found")
    return _player_to_dict(player)

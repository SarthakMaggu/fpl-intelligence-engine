"""Squad routes — retrieve and sync user squad."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from loguru import logger

from api.deps import get_db_session, get_fetcher, get_team_context
from core.config import settings
from core.exceptions import PipelineRunningError
from models.db.user_squad import UserSquad, UserBank
from models.db.player import Player
from models.db.team import Team
from models.db.gameweek import Gameweek
from agents.fpl_agent import FPLAgent
from services.cache_service import ANALYSIS_TTL, get_cached_payload, set_cached_payload
from services.job_queue import enqueue_job

router = APIRouter()


async def _run_news_background() -> None:
    """
    Fetch injury news from BBC Sport RSS (and Reddit if configured) then cache
    alerts in Redis at key 'news:injuries' (TTL 1h).

    Runs as a BackgroundTask after squad sync so the transfer route can
    annotate suggestions with injury/suspension warnings without blocking.
    """
    from core.database import AsyncSessionLocal
    from agents.news_agent import NewsAgent

    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Player.web_name))
            player_names = [row[0] for row in result.fetchall() if row[0]]

        agent = NewsAgent()
        alerts = await agent.run(player_names)
        logger.info(f"News agent background task complete: {len(alerts)} alerts for {len(player_names)} players")
    except Exception as exc:
        logger.warning(f"News agent background task failed (non-fatal): {exc}")


@router.get("/")
async def get_squad(
    team_context: dict = Depends(get_team_context),
    db: AsyncSession = Depends(get_db_session),
):
    """Get current squad picks with player data and predictions."""
    active_team_id = team_context["team_id"]
    session = team_context.get("session")
    cached = await get_cached_payload("squad", active_team_id, session.session_token if session else "registered")
    if cached:
        cached["analysis_mode"] = "cached"
        return cached

    # Get current GW
    result = await db.execute(select(Gameweek).where(Gameweek.is_current == True))
    current_gw = result.scalar_one_or_none()
    if not current_gw:
        result = await db.execute(select(Gameweek).order_by(Gameweek.id.desc()))
        current_gw = result.scalars().first()

    if not current_gw:
        raise HTTPException(404, "No gameweek data. Run /api/squad/sync first.")

    # When between GWs (current finished, next upcoming), display the upcoming
    # GW number and deadline so the user knows what they're planning for.
    display_gw = current_gw
    if current_gw.finished:
        next_result = await db.execute(select(Gameweek).where(Gameweek.is_next == True))
        next_gw = next_result.scalar_one_or_none()
        if next_gw:
            display_gw = next_gw

    # Get bank data early so empty-squad responses are safe.
    bank_result = await db.execute(
        select(UserBank).where(UserBank.team_id == active_team_id)
    )
    bank = bank_result.scalar_one_or_none()

    # Get squad picks (always keyed to current_gw in DB, even between GWs)
    result = await db.execute(
        select(UserSquad, Player)
        .join(Player, UserSquad.player_id == Player.id)
        .where(
            UserSquad.team_id == active_team_id,
            UserSquad.gameweek_id == current_gw.id,
        )
        .order_by(UserSquad.position)
    )
    picks = result.all()

    if not picks:
        # Return empty squad with bank data rather than 404 — frontend handles gracefully
        payload = {
            "team_id": active_team_id,
            "gameweek": display_gw.id,
            "deadline": display_gw.deadline_time.isoformat() if display_gw.deadline_time else None,
            "picks": [],
            "bank": bank.bank if bank else 0,
            "free_transfers": bank.free_transfers if bank else 1,
            "total_points": bank.total_points if bank else 0,
            "overall_rank": bank.overall_rank if bank else None,
            "team_name": bank.team_name if bank else "",
            "message": f"No squad data for team {active_team_id} GW{current_gw.id}. Run /api/squad/sync first.",
            "analysis_mode": "degraded",
            "data_freshness": None,
            "session_expires_at": session.expires_at.isoformat() if session else None,
        }
        await set_cached_payload("squad", payload, ANALYSIS_TTL, active_team_id, session.session_token if session else "registered")
        return payload

    # Load team lookup for badges (team_id → {short_name, code})
    result_teams = await db.execute(select(Team))
    team_map: dict[int, Team] = {t.id: t for t in result_teams.scalars().all()}

    pick_list = []
    for pick, player in picks:
        team = team_map.get(player.team_id)
        pick_list.append({
            "position": pick.position,
            "is_captain": pick.is_captain,
            "is_vice_captain": pick.is_vice_captain,
            "multiplier": pick.multiplier,
            "purchase_price": pick.purchase_price,
            "selling_price": pick.selling_price,
            "player": {
                "id": player.id,
                "web_name": player.web_name,
                "first_name": player.first_name,
                "second_name": player.second_name,
                "element_type": player.element_type,
                "team_id": player.team_id,
                "team_short_name": team.short_name if team else None,
                "team_code": team.code if team else None,
                "now_cost": player.now_cost,
                "selected_by_percent": player.selected_by_percent,
                "form": player.form,
                "form_trend": player.form_trend,
                "status": player.status,
                "news": player.news,
                "chance_of_playing_this_round": player.chance_of_playing_this_round,
                "predicted_xpts_next": player.predicted_xpts_next,
                "predicted_start_prob": player.predicted_start_prob,
                "predicted_price_direction": player.predicted_price_direction,
                "fdr_next": player.fdr_next,
                "is_home_next": player.is_home_next,
                "has_blank_gw": player.has_blank_gw,
                "has_double_gw": player.has_double_gw,
                "suspension_risk": player.suspension_risk,
                "xg_per_90": player.xg_per_90,
                "xa_per_90": player.xa_per_90,
                "total_points": player.total_points,
                "points_per_game": player.points_per_game,
            },
        })

    payload = {
        "team_id": active_team_id,
        "gameweek": display_gw.id,
        "deadline": display_gw.deadline_time.isoformat(),
        "picks": pick_list,
        "bank": bank.bank if bank else 0,
        "free_transfers": bank.free_transfers if bank else 1,
        "total_points": bank.total_points if bank else 0,
        "overall_rank": bank.overall_rank if bank else None,
        "team_name": bank.team_name if bank else "",
        "analysis_mode": "full",
        "data_freshness": datetime.now(timezone.utc).isoformat(),
        "session_expires_at": session.expires_at.isoformat() if session else None,
    }
    await set_cached_payload("squad", payload, ANALYSIS_TTL, active_team_id, session.session_token if session else "registered")
    return payload


@router.post("/sync")
async def sync_squad(
    team_id: int | None = None,
    background_tasks: BackgroundTasks = None,
    fetcher=Depends(get_fetcher),
):
    """
    Trigger full data pipeline to sync squad from FPL API.
    Uses Redis lock — returns immediately if already running.
    Also kicks off the news agent to populate injury/suspension alerts.
    Same pattern as war-intel-dashboard POST /api/refresh.
    """
    active_team_id = team_id or settings.FPL_TEAM_ID
    try:
        job = await enqueue_job(job_type="pipeline.full", payload={"team_id": active_team_id})
        # Populate injury/suspension news alerts from BBC Sport RSS + Reddit
        # into Redis so transfer suggestions can surface relevant warnings.
        background_tasks.add_task(_run_news_background)
        return {"status": "queued", "message": "Syncing squad from FPL API...", "job_id": job["job_id"]}
    except PipelineRunningError as e:
        from fastapi import Response
        return {"status": "already_running", "message": str(e)}


@router.get("/status")
async def get_sync_status(fetcher=Depends(get_fetcher)):
    """Check if pipeline is running and when it last ran."""
    return await fetcher.get_pipeline_status()


@router.get("/leagues")
async def get_user_leagues(
    request: Request,
    team_id: int = Query(None),
):
    """
    Fetch the user's classic and H2H leagues from the FPL API.
    Returns name, current rank, last rank, total entries per league.
    """
    active_team_id = team_id or settings.FPL_TEAM_ID
    if not active_team_id:
        raise HTTPException(400, "No FPL_TEAM_ID configured.")

    # Use the app-level shared HTTP client
    http_client = request.app.state.http_client
    agent = FPLAgent(http_client)

    try:
        entry = await agent.get_entry(active_team_id)
    except Exception as e:
        logger.error(f"Failed to fetch entry for team {active_team_id}: {e}")
        raise HTTPException(502, f"FPL API error: {e}")

    leagues_raw = entry.get("leagues", {})
    classic = leagues_raw.get("classic", [])
    h2h = leagues_raw.get("h2h", [])

    def format_league(lg: dict, league_type: str) -> dict:
        return {
            "id": lg.get("id"),
            "name": lg.get("name", ""),
            "type": league_type,
            "rank": lg.get("entry_rank") or lg.get("rank"),
            "last_rank": lg.get("entry_last_rank") or lg.get("last_rank"),
            "entry_percentile_rank": lg.get("entry_percentile_rank"),
            "total_entries": lg.get("total_entries"),
            "start_event": lg.get("start_event", 1),
        }

    return {
        "team_id": active_team_id,
        "classic": [format_league(lg, "classic") for lg in classic],
        "h2h": [format_league(lg, "h2h") for lg in h2h],
    }


@router.get("/{team_id}")
async def get_squad_by_id(
    team_id: int,
    db: AsyncSession = Depends(get_db_session),
):
    """Get any team's squad (for rival tracking)."""
    return await get_squad(team_id=team_id, db=db)

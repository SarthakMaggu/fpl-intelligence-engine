"""Rival tracking routes."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from api.deps import get_db_session
from core.config import settings
from models.db.rival import Rival
from models.db.gameweek import Gameweek

router = APIRouter()


class AddRivalRequest(BaseModel):
    rival_team_id: int


@router.get("/")
async def list_rivals(
    team_id: int | None = None,
    db: AsyncSession = Depends(get_db_session),
):
    """List tracked rival team IDs."""
    active_team_id = team_id or settings.FPL_TEAM_ID
    result = await db.execute(
        select(Rival).where(Rival.owner_team_id == active_team_id)
    )
    rivals = result.scalars().all()
    return [{"rival_team_id": r.rival_team_id, "rival_name": r.rival_name} for r in rivals]


@router.post("/add")
async def add_rival(
    body: AddRivalRequest,
    team_id: int | None = None,
    db: AsyncSession = Depends(get_db_session),
):
    """Add a rival team to track."""
    active_team_id = team_id or settings.FPL_TEAM_ID
    rival = Rival(owner_team_id=active_team_id, rival_team_id=body.rival_team_id)
    db.add(rival)
    try:
        await db.commit()
        return {"status": "added", "rival_team_id": body.rival_team_id}
    except Exception:
        await db.rollback()
        raise HTTPException(409, "Rival already tracked")


@router.delete("/{rival_team_id}")
async def remove_rival(
    rival_team_id: int,
    team_id: int | None = None,
    db: AsyncSession = Depends(get_db_session),
):
    """Remove a tracked rival."""
    active_team_id = team_id or settings.FPL_TEAM_ID
    result = await db.execute(
        select(Rival).where(
            Rival.owner_team_id == active_team_id,
            Rival.rival_team_id == rival_team_id,
        )
    )
    rival = result.scalar_one_or_none()
    if not rival:
        raise HTTPException(404, "Rival not found")
    await db.delete(rival)
    await db.commit()
    return {"status": "removed"}


@router.get("/captain-picks")
async def get_rival_captain_picks(
    team_id: int | None = None,
    db: AsyncSession = Depends(get_db_session),
):
    """Get all rivals' captain picks for current GW."""
    from data_pipeline.fetcher import DataFetcher
    import httpx

    active_team_id = team_id or settings.FPL_TEAM_ID
    result = await db.execute(
        select(Rival).where(Rival.owner_team_id == active_team_id)
    )
    rivals = result.scalars().all()

    result = await db.execute(select(Gameweek).where(Gameweek.is_current == True))
    current_gw = result.scalar_one_or_none()
    if not current_gw:
        return {"rivals": []}

    from agents.fpl_agent import FPLAgent
    from models.db.player import Player

    rival_picks = []
    async with httpx.AsyncClient() as client:
        agent = FPLAgent(client)
        for rival in rivals:
            try:
                picks_data = await agent.get_picks(rival.rival_team_id, current_gw.id)
                captain_pick = next(
                    (p for p in picks_data.get("picks", []) if p.get("is_captain")), None
                )
                if captain_pick:
                    player_id = captain_pick["element"]
                    player = await db.get(Player, player_id)
                    rival_picks.append({
                        "rival_team_id": rival.rival_team_id,
                        "rival_name": rival.rival_name,
                        "captain_player_id": player_id,
                        "captain_name": player.web_name if player else str(player_id),
                        "captain_xpts": player.predicted_xpts_next if player else 0,
                    })
            except Exception:
                continue

    return {"gameweek": current_gw.id, "rivals": rival_picks}

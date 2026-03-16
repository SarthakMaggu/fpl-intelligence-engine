"""RL/Bandit routes — recommendation and outcome recording."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from datetime import datetime

from api.deps import get_db_session
from core.config import settings
from models.db.gameweek import Gameweek
from models.db.bandit import BanditDecision
from optimizers.bandit import UCB1Bandit, DECISION_ARMS

router = APIRouter()
bandit = UCB1Bandit()


class OutcomeRequest(BaseModel):
    team_id: int | None = None
    decision_type: str
    arm: str
    predicted_value: float
    actual_value: float
    gw_id: int | None = None


@router.get("/recommend")
async def get_bandit_recommendation(
    decision_type: str,
    team_id: int | None = None,
    db: AsyncSession = Depends(get_db_session),
):
    """
    Get UCB1 bandit recommendation for a decision type.

    decision_type: transfer_strategy | captain_pick | chip_timing | hit_decision

    Returns the recommended arm plus Q-values and exploration state.
    On first use (no history) the bandit explores arms in round-robin order.
    """
    if decision_type not in DECISION_ARMS:
        raise HTTPException(
            400,
            f"Unknown decision_type. Valid: {list(DECISION_ARMS.keys())}",
        )

    active_team_id = team_id or settings.FPL_TEAM_ID
    if not active_team_id:
        raise HTTPException(400, "No team_id provided")

    result = await db.execute(select(Gameweek).where(Gameweek.is_current == True))
    current_gw = result.scalar_one_or_none()
    gw_id = current_gw.id if current_gw else 0

    rec = await bandit.recommend(active_team_id, decision_type)

    # Log the decision to DB for auditability
    decision = BanditDecision(
        team_id=active_team_id,
        gw_id=gw_id,
        decision_type=decision_type,
        arm_chosen=rec["arm"],
        context_json=str(rec.get("context", {})),
        predicted_value=0.0,
    )
    db.add(decision)
    await db.commit()

    return {
        "gameweek": gw_id,
        **rec,
    }


@router.get("/state")
async def get_bandit_state(
    team_id: int | None = None,
):
    """
    Return full UCB1 bandit state for all decision types.
    Useful for inspecting what the bandit has learned about your decision patterns.
    """
    active_team_id = team_id or settings.FPL_TEAM_ID
    if not active_team_id:
        raise HTTPException(400, "No team_id provided")

    states = await bandit.get_all_states(active_team_id)
    return {"team_id": active_team_id, "decision_states": states}


@router.post("/outcome")
async def record_outcome(
    body: OutcomeRequest,
    db: AsyncSession = Depends(get_db_session),
):
    """
    Record actual outcome after a GW and update Q-values.

    Call this after each GW completes with the actual points earned.
    The bandit computes reward = (actual - predicted) / max(|predicted|, 1)
    and updates the Q-value for the chosen arm.

    Example: after GW30, if you followed 'ilp' strategy and scored 82 pts
    vs predicted 75, call with actual_value=82, predicted_value=75, arm='ilp'.
    """
    active_team_id = body.team_id or settings.FPL_TEAM_ID
    if not active_team_id:
        raise HTTPException(400, "No team_id provided")

    result = await bandit.record_outcome(
        team_id=active_team_id,
        decision_type=body.decision_type,
        arm=body.arm,
        predicted_value=body.predicted_value,
        actual_value=body.actual_value,
    )

    # Update the matching DB record if gw_id is known
    gw_id = body.gw_id
    if gw_id:
        db_result = await db.execute(
            select(BanditDecision).where(
                BanditDecision.team_id == active_team_id,
                BanditDecision.gw_id == gw_id,
                BanditDecision.decision_type == body.decision_type,
                BanditDecision.arm_chosen == body.arm,
                BanditDecision.actual_value == None,  # noqa: E711
            )
        )
        record = db_result.scalars().first()
        if record:
            record.actual_value = body.actual_value
            record.predicted_value = body.predicted_value
            record.reward = result["reward"]
            record.resolved_at = datetime.utcnow()
            await db.commit()

    return result


@router.get("/history")
async def get_bandit_history(
    team_id: int | None = None,
    decision_type: str | None = None,
    limit: int = 20,
    db: AsyncSession = Depends(get_db_session),
):
    """Return recent bandit decisions with outcomes for a team."""
    active_team_id = team_id or settings.FPL_TEAM_ID
    if not active_team_id:
        raise HTTPException(400, "No team_id provided")

    query = select(BanditDecision).where(BanditDecision.team_id == active_team_id)
    if decision_type:
        query = query.where(BanditDecision.decision_type == decision_type)
    query = query.order_by(BanditDecision.created_at.desc()).limit(limit)

    result = await db.execute(query)
    records = result.scalars().all()

    return {
        "team_id": active_team_id,
        "decisions": [
            {
                "id": r.id,
                "gw_id": r.gw_id,
                "decision_type": r.decision_type,
                "arm_chosen": r.arm_chosen,
                "predicted_value": r.predicted_value,
                "actual_value": r.actual_value,
                "reward": r.reward,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in records
        ],
    }

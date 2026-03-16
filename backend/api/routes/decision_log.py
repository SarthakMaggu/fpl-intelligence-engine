"""
Decision Log API — CRUD for FPL decision records.

POST /api/decisions/         — log a new recommendation
GET  /api/decisions/         — list decisions for a team
PATCH /api/decisions/{id}    — update user_choice + decision_followed
"""
from __future__ import annotations

from typing import Optional
from datetime import datetime
import json

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from core.database import get_db
from models.db.decision_log import DecisionLog

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────

class DecisionCreateRequest(BaseModel):
    team_id: int
    gameweek_id: int
    decision_type: str          # transfer | captain | chip | hit
    recommended_option: str     # e.g. "Salah → Mbappé" or "Haaland (C)"
    expected_points: float = 0.0
    reasoning: Optional[str] = None
    # Bandit wiring fields (optional — populated by recommendation engine)
    engine_strategy_arm: Optional[str] = None
    engine_confidence: Optional[float] = None
    engine_predicted_gain: Optional[float] = None
    decision_score: Optional[float] = None
    validation_status: Optional[str] = None
    risk_preference: Optional[str] = None
    floor_projection: Optional[float] = None
    median_projection: Optional[float] = None
    ceiling_projection: Optional[float] = None
    projection_variance: Optional[float] = None
    explanation_summary: Optional[str] = None
    inputs_used: Optional[dict] = None
    simulation_summary: Optional[dict] = None
    # Whether this decision involved paying a -4pt transfer hit
    hit_taken: bool = False


class DecisionUpdateRequest(BaseModel):
    user_choice: Optional[str] = None
    decision_followed: Optional[bool] = None
    notes: Optional[str] = None
    user_action: Optional[str] = None   # followed | ignored | partially_followed
    # Allow updating hit_taken after the fact (user confirms they took a hit)
    hit_taken: Optional[bool] = None


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/")
async def create_decision(
    req: DecisionCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Log a new AI recommendation for later tracking.

    Idempotent: if the same (team_id, gameweek_id, decision_type, recommended_option)
    already exists and is unresolved, returns that record instead of creating a duplicate.
    This prevents review showing 12 entries for only 4 real decisions (multiple sessions).
    """
    # Deduplication — same recommendation already logged this GW?
    existing_res = await db.execute(
        select(DecisionLog).where(
            and_(
                DecisionLog.team_id == req.team_id,
                DecisionLog.gameweek_id == req.gameweek_id,
                DecisionLog.decision_type == req.decision_type,
                DecisionLog.recommended_option == req.recommended_option,
                DecisionLog.resolved_at.is_(None),
            )
        ).order_by(DecisionLog.created_at.desc()).limit(1)
    )
    existing = existing_res.scalars().first()
    if existing:
        return {"id": existing.id, "created": False, "deduplicated": True}

    # Cross-GW deduplication — same recommendation in previous GW already logged?
    # Prevents: GW29 "OUT: X / IN: Y" being re-logged as GW30 entry when same
    # action cards appear because the underlying issue hasn't changed.
    prev_gw_res = await db.execute(
        select(DecisionLog).where(
            and_(
                DecisionLog.team_id == req.team_id,
                DecisionLog.gameweek_id == req.gameweek_id - 1,
                DecisionLog.decision_type == req.decision_type,
                DecisionLog.recommended_option == req.recommended_option,
            )
        ).limit(1)
    )
    prev_gw_existing = prev_gw_res.scalars().first()
    if prev_gw_existing:
        return {"id": prev_gw_existing.id, "created": False, "deduplicated": True, "cross_gw": True}

    record = DecisionLog(
        team_id=req.team_id,
        gameweek_id=req.gameweek_id,
        decision_type=req.decision_type,
        recommended_option=req.recommended_option,
        expected_points=req.expected_points,
        reasoning=req.reasoning,
        engine_strategy_arm=req.engine_strategy_arm,
        engine_confidence=req.engine_confidence,
        engine_predicted_gain=req.engine_predicted_gain,
        decision_score=req.decision_score,
        validation_status=req.validation_status,
        risk_preference=req.risk_preference,
        floor_projection=req.floor_projection,
        median_projection=req.median_projection,
        ceiling_projection=req.ceiling_projection,
        projection_variance=req.projection_variance,
        explanation_summary=req.explanation_summary,
        inputs_used_json=json.dumps(req.inputs_used) if req.inputs_used is not None else None,
        simulation_summary_json=json.dumps(req.simulation_summary) if req.simulation_summary is not None else None,
        hit_taken=req.hit_taken,
        created_at=datetime.utcnow(),
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return {"id": record.id, "created": True}


@router.get("/")
async def list_decisions(
    team_id: int = Query(...),
    gameweek_id: Optional[int] = Query(None),
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db),
):
    """List recent decisions for a team."""
    conditions = [DecisionLog.team_id == team_id]
    if gameweek_id is not None:
        conditions.append(DecisionLog.gameweek_id == gameweek_id)

    res = await db.execute(
        select(DecisionLog)
        .where(and_(*conditions))
        .order_by(DecisionLog.created_at.desc())
        .limit(limit)
    )
    logs = res.scalars().all()

    return {
        "team_id": team_id,
        "total": len(logs),
        "decisions": [
            {
                "id": l.id,
                "gameweek_id": l.gameweek_id,
                "decision_type": l.decision_type,
                "recommended_option": l.recommended_option,
                "user_choice": l.user_choice,
                "expected_points": l.expected_points,
                "actual_points": l.actual_points,
                "decision_followed": l.decision_followed,
                "reasoning": l.reasoning,
                "decision_score": l.decision_score,
                "validation_status": l.validation_status,
                "risk_preference": l.risk_preference,
                "floor_projection": l.floor_projection,
                "median_projection": l.median_projection,
                "ceiling_projection": l.ceiling_projection,
                "projection_variance": l.projection_variance,
                "explanation_summary": l.explanation_summary,
                "inputs_used": json.loads(l.inputs_used_json) if l.inputs_used_json else None,
                "simulation_summary": json.loads(l.simulation_summary_json) if l.simulation_summary_json else None,
                "notes": l.notes,
                "created_at": l.created_at.isoformat() if l.created_at else None,
                "resolved_at": l.resolved_at.isoformat() if l.resolved_at else None,
            }
            for l in logs
        ],
    }


@router.patch("/{decision_id}")
async def update_decision(
    decision_id: int,
    req: DecisionUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Update a decision with the user's actual choice.
    Called from the frontend when user confirms or rejects a transfer/captain pick.
    """
    res = await db.execute(select(DecisionLog).where(DecisionLog.id == decision_id))
    record = res.scalars().first()

    if not record:
        raise HTTPException(status_code=404, detail="Decision not found")

    if req.user_choice is not None:
        record.user_choice = req.user_choice
    if req.decision_followed is not None:
        record.decision_followed = req.decision_followed
    if req.notes is not None:
        record.notes = req.notes
    if req.user_action is not None:
        record.user_action = req.user_action
    if req.hit_taken is not None:
        record.hit_taken = req.hit_taken

    await db.commit()
    return {
        "id": decision_id,
        "updated": True,
        "decision_followed": record.decision_followed,
        "hit_taken": record.hit_taken,
    }


@router.delete("/{decision_id}")
async def delete_decision(
    decision_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete a decision record (e.g. if logged in error)."""
    res = await db.execute(select(DecisionLog).where(DecisionLog.id == decision_id))
    record = res.scalars().first()
    if not record:
        raise HTTPException(status_code=404, detail="Decision not found")
    await db.delete(record)
    await db.commit()
    return {"deleted": True}

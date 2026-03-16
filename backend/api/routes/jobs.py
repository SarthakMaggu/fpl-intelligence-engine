"""
Jobs API — async job status tracking via Redis.

GET /api/jobs/{job_id}  — poll status of a background job (backtest, retrain, etc.)
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from services.job_queue import get_job_state

router = APIRouter()


@router.get("/{job_id}")
async def get_job_status(job_id: str):
    """
    Return the current status of a background job.

    States: pending → running → done | error

    Response:
    {
      "job_id": "...",
      "status": "done",
      "created_at": "...",
      "completed_at": "...",
      "result": { ... }   // present when status == "done"
      "error": "..."       // present when status == "error"
    }
    """
    state = await get_job_state(job_id)
    if not state:
        raise HTTPException(
            status_code=404,
            detail=f"Job '{job_id}' not found. It may have expired (TTL: 24h).",
        )
    return state

"""
User Profile API — stores FPL manager email for pre-deadline alerts.

POST /api/user/profile          — upsert email + team_id (called from Onboarding)
                                   Enforces 500-user cap; adds to waitlist if at capacity.
GET  /api/user/profile          — retrieve profile by team_id
DELETE /api/user/profile        — remove (unsubscribe); notifies next waitlist entry
GET  /api/user/subscribers      — ADMIN ONLY: list all registered users + waitlist stats
                                   Requires X-Admin-Token header.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query, Request
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import func, select, text

from core.config import settings
from core.database import AsyncSessionLocal
from models.db.anonymous_session import AnonymousAnalysisSession
from models.db.user_profile import UserProfile
from models.db.waitlist import Waitlist
from notifications.email_service import EmailService
from services.session_service import create_anonymous_session

router = APIRouter()

# Maximum number of registered users (email subscribers)
USER_CAP = settings.USER_CAP

# Advisory lock key — unique integer to serialise concurrent registrations.
# Prevents race: two requests both read "499 users" and both register, bypassing cap.
_REG_LOCK_KEY = 7_461_100  # arbitrary stable integer for pg_advisory_xact_lock


def _require_admin(x_admin_token: Optional[str]) -> None:
    """Raise 403 if the admin token is missing or wrong."""
    if not settings.ADMIN_TOKEN:
        raise HTTPException(
            status_code=503,
            detail="Admin access not configured — set ADMIN_TOKEN environment variable",
        )
    if x_admin_token != settings.ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid or missing X-Admin-Token")


class ProfileRequest(BaseModel):
    team_id: int
    email: str
    name: Optional[str] = None
    pre_deadline_email: bool = True


class AnonymousSessionRequest(BaseModel):
    team_id: int


@router.post("/profile")
async def upsert_profile(req: ProfileRequest):
    """
    Save or update an FPL manager's email profile.

    Race-condition safety: uses PostgreSQL advisory transaction lock so concurrent
    registrations cannot both bypass the cap by reading the same count.
    All cap-check + insert happens atomically inside a single BEGIN…COMMIT.
    """
    email = req.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Invalid email address")

    _at_cap = False
    _waitlist_position = 0
    registered_count_new = 0

    async with AsyncSessionLocal() as db:
        async with db.begin():
            # Fast path: existing team_id — just update, no cap check needed
            existing_res = await db.execute(
                select(UserProfile).where(UserProfile.team_id == req.team_id)
            )
            existing_profile = existing_res.scalar_one_or_none()

            if existing_profile:
                existing_profile.email = email
                existing_profile.name = req.name
                existing_profile.pre_deadline_email = req.pre_deadline_email
                existing_profile.updated_at = datetime.utcnow()
                logger.info(f"User profile updated: team_id={req.team_id} email={email}")
                return {
                    "status": "updated",
                    "team_id": existing_profile.team_id,
                    "email": existing_profile.email,
                    "pre_deadline_email": existing_profile.pre_deadline_email,
                }

            # Acquire advisory lock — serialises concurrent new registrations
            await db.execute(text(f"SELECT pg_advisory_xact_lock({_REG_LOCK_KEY})"))

            registered_count = await db.scalar(select(func.count()).select_from(UserProfile)) or 0

            if registered_count >= USER_CAP:
                # Cap reached — add to waitlist atomically
                wl_res = await db.execute(
                    select(Waitlist).where(Waitlist.team_id == req.team_id)
                )
                on_waitlist = wl_res.scalar_one_or_none()

                if not on_waitlist:
                    current_wl_count = (
                        await db.scalar(select(func.count()).select_from(Waitlist)) or 0
                    )
                    db.add(Waitlist(
                        team_id=req.team_id,
                        email=email,
                        position=current_wl_count + 1,
                    ))
                    logger.info(f"User cap reached ({USER_CAP}), added to waitlist: team_id={req.team_id}")

                _waitlist_position = (
                    on_waitlist.position
                    if on_waitlist and on_waitlist.position
                    else (await db.scalar(select(func.count()).select_from(Waitlist)) or 1)
                )
                _at_cap = True
                # flush so the waitlist INSERT commits when the begin() block exits
                await db.flush()
            else:
                db.add(UserProfile(
                    team_id=req.team_id,
                    email=email,
                    name=req.name,
                    pre_deadline_email=req.pre_deadline_email,
                ))
                registered_count_new = registered_count + 1

    # Outside transaction — raise after commit if cap was hit
    if _at_cap:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "WAITLIST",
                "message": (
                    f"We're at capacity ({USER_CAP} users). "
                    "You've been added to the waitlist."
                ),
                "position": _waitlist_position,
            },
        )

    logger.info(
        f"User profile created: team_id={req.team_id} email={email} "
        f"(total registered: {registered_count_new}/{USER_CAP})"
    )
    return {
        "status": "created",
        "team_id": req.team_id,
        "email": email,
        "pre_deadline_email": req.pre_deadline_email,
        "registered_count": registered_count_new,
        "cap": USER_CAP,
    }


@router.get("/profile")
async def get_profile(team_id: int = Query(..., description="FPL team entry ID")):
    """Retrieve user profile by team_id."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(UserProfile).where(UserProfile.team_id == team_id)
        )
        profile = result.scalar_one_or_none()

    if not profile:
        return {"team_id": team_id, "email": None, "pre_deadline_email": False}

    return {
        "team_id": profile.team_id,
        "email": profile.email,
        "name": profile.name,
        "pre_deadline_email": profile.pre_deadline_email,
        "created_at": profile.created_at.isoformat() if profile.created_at else None,
    }


@router.delete("/profile")
async def delete_profile(team_id: int = Query(...)):
    """
    Remove user profile (unsubscribe from all alerts).

    Atomic: deletion + waitlist promotion in a single transaction with advisory lock.
    No window where the slot appears free but promotion hasn't happened yet.
    """
    promoted_team_id = None
    promoted_email = None

    async with AsyncSessionLocal() as db:
        async with db.begin():
            # Hold the same lock so no concurrent registration slips into the freed slot
            await db.execute(text(f"SELECT pg_advisory_xact_lock({_REG_LOCK_KEY})"))

            result = await db.execute(
                select(UserProfile).where(UserProfile.team_id == team_id)
            )
            profile = result.scalar_one_or_none()
            if not profile:
                return {"status": "not_found", "team_id": team_id}

            await db.delete(profile)

            # Promote oldest un-notified waitlist entry in the same transaction
            wl_res = await db.execute(
                select(Waitlist)
                .where(Waitlist.notified == False)  # noqa: E712
                .order_by(Waitlist.created_at)
                .limit(1)
            )
            next_in_line = wl_res.scalar_one_or_none()
            if next_in_line:
                db.add(UserProfile(
                    team_id=next_in_line.team_id,
                    email=next_in_line.email,
                    pre_deadline_email=True,
                    email_verified=False,
                ))
                next_in_line.notified = True
                next_in_line.notified_at = datetime.utcnow()
                next_in_line.promoted_at = datetime.utcnow()
                promoted_team_id = next_in_line.team_id
                promoted_email = next_in_line.email
                logger.info(
                    f"Waitlist: spot opened by team {team_id} — "
                    f"team_id={next_in_line.team_id} promoted into user_profile"
                )

    logger.info(f"User profile deleted: team_id={team_id}")

    # Send emails outside the transaction (no DB state needed)
    if promoted_email and settings.email_enabled:
        try:
            notifier = EmailService()
            await notifier.send_deadline_alert(
                to_email=promoted_email,
                gw_id=0,
                intel_data={"message": "A place is now available on FPL Intelligence."},
            )
            await notifier.send_admin_alert(
                subject="User Unsubscribed — Spot Opened",
                body=(
                    f"Team {team_id} deleted their profile.\n\n"
                    f"Waitlist promotion: team_id={promoted_team_id} "
                    f"({promoted_email}) has been moved from waitlist → user_profile."
                ),
            )
        except Exception as exc:
            logger.warning(f"Waitlist promotion email failed: {exc}")

    return {
        "status": "deleted",
        "team_id": team_id,
        "promoted_team_id": promoted_team_id,
    }


@router.post("/anonymous-session")
async def create_session(req: AnonymousSessionRequest, request: Request):
    async with AsyncSessionLocal() as db:
        session = await create_anonymous_session(req.team_id, db, request=request)
    return {
        "session_token": session.session_token,
        "team_id": session.team_id,
        "expires_at": session.expires_at.isoformat(),
        "analysis_mode": "full",
    }


@router.get("/anonymous-session/{session_token}")
async def get_session(session_token: str):
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(AnonymousAnalysisSession).where(
                AnonymousAnalysisSession.session_token == session_token
            )
        )
        session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Anonymous session not found")
    return {
        "session_token": session.session_token,
        "team_id": session.team_id,
        "status": session.status,
        "expires_at": session.expires_at.isoformat(),
    }


@router.get("/spots")
async def get_spots():
    """
    Public endpoint — returns how many registration spots remain.
    Result is cached in Redis for 60 s to avoid DB hammering.
    Used by the frontend to show a live "N spots left" counter.
    """
    from core.redis_client import redis_client
    import json as _json

    _SPOTS_CACHE_KEY = "cache:user:spots"
    _SPOTS_CACHE_TTL = 60  # seconds

    try:
        cached = await redis_client.get(_SPOTS_CACHE_KEY)
        if cached:
            return _json.loads(cached)
    except Exception:
        pass  # Redis unavailable — fall through to DB

    async with AsyncSessionLocal() as db:
        registered = await db.scalar(select(func.count()).select_from(UserProfile)) or 0
        waitlisted = await db.scalar(select(func.count()).select_from(Waitlist)) or 0

    spots_remaining = max(0, USER_CAP - registered)
    payload = {
        "registered": registered,
        "cap": USER_CAP,
        "spots_remaining": spots_remaining,
        "waitlist": waitlisted,
        "is_full": spots_remaining == 0,
    }

    try:
        await redis_client.set(_SPOTS_CACHE_KEY, _json.dumps(payload), ex=_SPOTS_CACHE_TTL)
    except Exception:
        pass

    return payload


@router.get("/subscribers")
async def list_subscribers(
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
):
    """
    Admin-only: list all registered users + waitlist stats.
    Requires X-Admin-Token header matching the ADMIN_TOKEN environment variable.
    """
    _require_admin(x_admin_token)

    async with AsyncSessionLocal() as db:
        reg_res = await db.execute(select(UserProfile).order_by(UserProfile.created_at))
        profiles = reg_res.scalars().all()

        wl_res = await db.execute(select(Waitlist).order_by(Waitlist.created_at))
        waitlist = wl_res.scalars().all()

    return {
        "registered": len(profiles),
        "cap": USER_CAP,
        "spots_remaining": max(0, USER_CAP - len(profiles)),
        "waitlist": len(waitlist),
        "users": [
            {
                "team_id": p.team_id,
                "email": p.email,
                "name": p.name,
                "pre_deadline_email": p.pre_deadline_email,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in profiles
        ],
        "waitlist_entries": [
            {
                "team_id": w.team_id,
                "email": w.email,
                "created_at": w.created_at.isoformat() if w.created_at else None,
                "notified": w.notified,
            }
            for w in waitlist
        ],
    }

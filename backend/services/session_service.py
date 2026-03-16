from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import HTTPException, Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from models.db.anonymous_session import AnonymousAnalysisSession


def build_session_token() -> str:
    return secrets.token_urlsafe(24)


async def create_anonymous_session(
    team_id: int,
    db: AsyncSession,
    request: Optional[Request] = None,
) -> AnonymousAnalysisSession:
    now = datetime.utcnow()
    session = AnonymousAnalysisSession(
        session_token=build_session_token(),
        team_id=team_id,
        status="active",
        client_ip=request.client.host if request and request.client else None,
        user_agent=request.headers.get("user-agent") if request else None,
        expires_at=now + timedelta(hours=settings.ANONYMOUS_SESSION_TTL_HOURS),
        last_accessed_at=now,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def resolve_team_context(
    db: AsyncSession,
    *,
    team_id: Optional[int] = None,
    session_token: Optional[str] = None,
    allow_default: bool = False,
) -> tuple[int, Optional[AnonymousAnalysisSession]]:
    if session_token:
        result = await db.execute(
            select(AnonymousAnalysisSession).where(
                AnonymousAnalysisSession.session_token == session_token
            )
        )
        session = result.scalar_one_or_none()
        if not session:
            raise HTTPException(status_code=404, detail="Anonymous analysis session not found")
        if session.expires_at <= datetime.utcnow() or session.status != "active":
            session.status = "expired"
            await db.commit()
            raise HTTPException(status_code=410, detail="Anonymous analysis session expired")
        session.last_accessed_at = datetime.utcnow()
        await db.commit()
        return session.team_id, session

    if team_id:
        return team_id, None

    if allow_default and settings.FPL_TEAM_ID:
        return settings.FPL_TEAM_ID, None

    raise HTTPException(status_code=400, detail="Provide either team_id or session_token")


async def expire_sessions(db: AsyncSession) -> int:
    result = await db.execute(
        update(AnonymousAnalysisSession)
        .where(
            AnonymousAnalysisSession.status == "active",
            AnonymousAnalysisSession.expires_at <= datetime.utcnow(),
        )
        .values(status="expired")
    )
    await db.commit()
    return result.rowcount or 0

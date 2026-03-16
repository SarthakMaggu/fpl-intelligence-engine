"""FastAPI dependency injection helpers."""
from typing import AsyncGenerator
from fastapi import Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import get_db
from data_pipeline.fetcher import DataFetcher
from services.session_service import resolve_team_context

# Singleton fetcher instance shared across requests
_fetcher: DataFetcher | None = None


def get_fetcher() -> DataFetcher:
    global _fetcher
    if _fetcher is None:
        _fetcher = DataFetcher()
    return _fetcher


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async for session in get_db():
        yield session


async def get_team_context(
    db: AsyncSession = Depends(get_db_session),
    team_id: int | None = Query(None),
    session_token: str | None = Query(None),
):
    resolved_team_id, session = await resolve_team_context(
        db,
        team_id=team_id,
        session_token=session_token,
        allow_default=False,
    )
    return {
        "team_id": resolved_team_id,
        "session": session,
    }

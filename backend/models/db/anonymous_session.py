from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class AnonymousAnalysisSession(Base):
    __tablename__ = "anonymous_analysis_session"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_token: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    team_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    client_ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    last_accessed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


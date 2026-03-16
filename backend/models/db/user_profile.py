"""
UserProfile — stores FPL manager email + preferences for deadline alerts.

One row per FPL team_id. Created when a user enters their email on the
Onboarding screen. Used by the pre-deadline email scheduler to send
personalised HTML alerts 24h before each GW deadline.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, Boolean, Integer, DateTime, func

from core.database import Base


class UserProfile(Base):
    __tablename__ = "user_profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    team_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    pre_deadline_email: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

"""
Waitlist — overflow queue for when the 500-user registered cap is reached.

When POST /api/user/profile is called and the registered user count hits 500,
the requester is added here instead. When a spot opens (user deletes profile),
the first waitlist entry is notified.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class Waitlist(Base):
    __tablename__ = "waitlist"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    team_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    position: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    promoted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # Flipped to True once the user is notified that a spot is available
    notified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"<Waitlist team={self.team_id} email={self.email} notified={self.notified}>"

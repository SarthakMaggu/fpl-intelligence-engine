from sqlalchemy import Integer, String, DateTime, UniqueConstraint, Index
from sqlalchemy.orm import mapped_column, Mapped
from datetime import datetime
from core.database import Base


class Rival(Base):
    """Tracked rival FPL teams."""
    __tablename__ = "rivals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_team_id: Mapped[int] = mapped_column(Integer)     # your FPL team ID
    rival_team_id: Mapped[int] = mapped_column(Integer)     # rival's FPL team ID
    rival_name: Mapped[str] = mapped_column(String(200), default="")
    added_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("owner_team_id", "rival_team_id", name="uq_rival"),
        Index("ix_rivals_owner", "owner_team_id"),
    )

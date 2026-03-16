"""
CompetitionFixture — cross-competition fixture store.

Tracks upcoming and completed fixtures across ALL competitions a PL club
participates in:
  PL   — Premier League (sourced from FPL API, no key required)
  UCL  — UEFA Champions League (football-data.org, requires FOOTBALL_DATA_API_KEY)
  UEL  — UEFA Europa League (football-data.org)
  FAC  — FA Cup (football-data.org)
  CC   — EFL Carabao Cup (football-data.org, plan-dependent)

Used by:
  - player_features.py → rotation_risk / expected_minutes adjustment
  - predictions pipeline → fixture congestion scoring
  - Scheduler: daily sync at 02:00 AM
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class CompetitionFixture(Base):
    __tablename__ = "competition_fixtures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Competition identifier
    competition: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    season: Mapped[str] = mapped_column(String(16), nullable=False, index=True)  # e.g. "2024-25"

    # Raw team names from the source API
    home_team_name: Mapped[str] = mapped_column(String(120), nullable=False)
    away_team_name: Mapped[str] = mapped_column(String(120), nullable=False)

    # Mapped FPL team IDs (nullable — non-PL clubs won't have one)
    home_fpl_team_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    away_fpl_team_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)

    # Kick-off time (UTC)
    match_utc: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    # Match state
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="SCHEDULED"
    )  # SCHEDULED | IN_PLAY | PAUSED | FINISHED | POSTPONED | CANCELLED

    # Score (None until finished)
    home_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    away_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Round label from source ("Matchday 6", "Round of 16", "Semi-Final", etc.)
    fixture_round: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)

    # Source-API match ID (de-duplication key)
    external_id: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        # Composite unique: one row per (competition, external source ID)
        UniqueConstraint(
            "competition", "external_id",
            name="uq_cf_competition_external_id",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<CompetitionFixture {self.competition} "
            f"{self.home_team_name} v {self.away_team_name} "
            f"({self.match_utc})>"
        )

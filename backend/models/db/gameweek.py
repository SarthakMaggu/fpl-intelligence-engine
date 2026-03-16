from sqlalchemy import String, Integer, Float, Boolean, DateTime, Text, Index
from sqlalchemy.orm import mapped_column, Mapped
from datetime import datetime
from typing import Optional
from core.database import Base


class Gameweek(Base):
    __tablename__ = "gameweeks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)      # 1-38
    name: Mapped[str] = mapped_column(String(50))                   # "Gameweek 1"
    deadline_time: Mapped[datetime] = mapped_column(DateTime)
    deadline_time_epoch: Mapped[int] = mapped_column(Integer, default=0)

    # Status flags
    finished: Mapped[bool] = mapped_column(Boolean, default=False)
    data_checked: Mapped[bool] = mapped_column(Boolean, default=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)
    is_next: Mapped[bool] = mapped_column(Boolean, default=False)
    is_previous: Mapped[bool] = mapped_column(Boolean, default=False)

    # Computed: blank/double GW detection
    is_blank: Mapped[bool] = mapped_column(Boolean, default=False)   # some teams have no fixture
    is_double: Mapped[bool] = mapped_column(Boolean, default=False)  # some teams have 2 fixtures

    # GW aggregate stats
    average_entry_score: Mapped[int] = mapped_column(Integer, default=0)
    highest_score: Mapped[int] = mapped_column(Integer, default=0)
    highest_scoring_entry: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    chip_plays: Mapped[str] = mapped_column(Text, default="[]")      # JSON array
    top_element: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    top_element_info: Mapped[str] = mapped_column(Text, default="{}")  # JSON

    transfers_made: Mapped[int] = mapped_column(Integer, default=0)

    def __repr__(self) -> str:
        return f"<Gameweek id={self.id} current={self.is_current}>"


class Fixture(Base):
    __tablename__ = "fixtures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)      # FPL fixture ID
    code: Mapped[int] = mapped_column(Integer, unique=True)         # FPL code

    # GW assignment — None means postponed
    gameweek_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    event_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # alias

    # Teams (FK references to teams.id)
    team_home_id: Mapped[int] = mapped_column(Integer)
    team_away_id: Mapped[int] = mapped_column(Integer)

    # Kickoff
    kickoff_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    kickoff_time_provisional: Mapped[bool] = mapped_column(Boolean, default=False)

    # Result
    finished: Mapped[bool] = mapped_column(Boolean, default=False)
    finished_provisional: Mapped[bool] = mapped_column(Boolean, default=False)
    started: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    team_home_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    team_away_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Fixture difficulty rating (1=easiest, 5=hardest)
    team_h_difficulty: Mapped[int] = mapped_column(Integer, default=3)
    team_a_difficulty: Mapped[int] = mapped_column(Integer, default=3)

    # Pulse ID for live data linking
    pulse_id: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        Index("ix_fixtures_gameweek_id", "gameweek_id"),
        Index("ix_fixtures_team_home", "team_home_id"),
        Index("ix_fixtures_team_away", "team_away_id"),
    )

    def __repr__(self) -> str:
        return f"<Fixture id={self.id} gw={self.gameweek_id} h={self.team_home_id} a={self.team_away_id}>"

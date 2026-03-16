"""Historical data models — player GW stats and user GW performance."""
from sqlalchemy import String, Integer, Float, Boolean, UniqueConstraint, Index
from sqlalchemy.orm import mapped_column, Mapped
from typing import Optional
from core.database import Base


class PlayerGWHistory(Base):
    """Per-player per-GW stats from FPL /api/element-summary/{id}/."""
    __tablename__ = "player_gw_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(Integer, index=True)
    gw_id: Mapped[int] = mapped_column(Integer)

    # Core performance
    total_points: Mapped[int] = mapped_column(Integer, default=0)
    minutes: Mapped[int] = mapped_column(Integer, default=0)
    goals_scored: Mapped[int] = mapped_column(Integer, default=0)
    assists: Mapped[int] = mapped_column(Integer, default=0)
    clean_sheets: Mapped[int] = mapped_column(Integer, default=0)
    yellow_cards: Mapped[int] = mapped_column(Integer, default=0)
    red_cards: Mapped[int] = mapped_column(Integer, default=0)
    saves: Mapped[int] = mapped_column(Integer, default=0)
    bonus: Mapped[int] = mapped_column(Integer, default=0)
    bps: Mapped[int] = mapped_column(Integer, default=0)

    # Ownership & price that GW
    value: Mapped[int] = mapped_column(Integer, default=0)          # price in pence × 10
    selected: Mapped[int] = mapped_column(Integer, default=0)       # ownership count
    transfers_in: Mapped[int] = mapped_column(Integer, default=0)
    transfers_out: Mapped[int] = mapped_column(Integer, default=0)

    # xG / xA (if available from FPL)
    expected_goals: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    expected_assists: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    expected_goal_involvements: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    expected_goals_conceded: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Was this a home game?
    was_home: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    opponent_team: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    team_h_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    team_a_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        UniqueConstraint("player_id", "gw_id", name="uq_player_gw_history"),
        Index("ix_player_gw_history_player", "player_id"),
        Index("ix_player_gw_history_gw", "gw_id"),
    )

    def __repr__(self) -> str:
        return f"<PlayerGWHistory player={self.player_id} gw={self.gw_id} pts={self.total_points}>"


class UserGWHistory(Base):
    """Per-team per-GW performance from FPL /api/entry/{team_id}/history/."""
    __tablename__ = "user_gw_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    team_id: Mapped[int] = mapped_column(Integer, index=True)
    gw_id: Mapped[int] = mapped_column(Integer)

    # GW performance
    points: Mapped[int] = mapped_column(Integer, default=0)             # GW points (after deductions)
    total_points: Mapped[int] = mapped_column(Integer, default=0)       # cumulative
    rank: Mapped[Optional[int]] = mapped_column(Integer, nullable=True) # GW rank
    rank_sort: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    overall_rank: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    percentile_rank: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Transfers
    event_transfers: Mapped[int] = mapped_column(Integer, default=0)
    event_transfers_cost: Mapped[int] = mapped_column(Integer, default=0)

    # Chip played (e.g. "wildcard", "bboost", "3xc", "freehit", or None)
    active_chip: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Squad value & bank
    bank: Mapped[int] = mapped_column(Integer, default=0)       # pence in bank
    value: Mapped[int] = mapped_column(Integer, default=1000)   # squad value pence

    # Points breakdown (useful for ML)
    points_on_bench: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        UniqueConstraint("team_id", "gw_id", name="uq_user_gw_history"),
        Index("ix_user_gw_history_team", "team_id"),
    )

    def __repr__(self) -> str:
        return f"<UserGWHistory team={self.team_id} gw={self.gw_id} pts={self.points}>"

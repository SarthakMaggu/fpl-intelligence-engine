from sqlalchemy import String, Integer, Float, Boolean, DateTime, Text, Index, UniqueConstraint
from sqlalchemy.orm import mapped_column, Mapped
from datetime import datetime
from typing import Optional
from core.database import Base


class UserSquad(Base):
    """Current and historical squad picks per team per gameweek."""
    __tablename__ = "user_squads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    team_id: Mapped[int] = mapped_column(Integer)           # FPL entry ID
    gameweek_id: Mapped[int] = mapped_column(Integer)
    player_id: Mapped[int] = mapped_column(Integer)         # FK → players.id

    # Position 1-15 in squad. 1-11 = starting XI, 12-15 = bench (priority order)
    position: Mapped[int] = mapped_column(Integer)
    is_captain: Mapped[bool] = mapped_column(Boolean, default=False)
    is_vice_captain: Mapped[bool] = mapped_column(Boolean, default=False)

    # 0=bench, 1=starting, 2=captain (×2), 3=triple captain (×3)
    multiplier: Mapped[int] = mapped_column(Integer, default=1)

    # Pricing at pick time
    purchase_price: Mapped[int] = mapped_column(Integer, default=0)   # pence
    selling_price: Mapped[int] = mapped_column(Integer, default=0)    # pence (FPL sell-on cap)

    __table_args__ = (
        Index("ix_user_squads_team_gw", "team_id", "gameweek_id"),
        Index("ix_user_squads_player", "player_id"),
        UniqueConstraint("team_id", "gameweek_id", "player_id", name="uq_user_squad_pick"),
    )

    def __repr__(self) -> str:
        return f"<UserSquad team={self.team_id} gw={self.gameweek_id} player={self.player_id} pos={self.position}>"


class UserSquadSnapshot(Base):
    """Stores pre-Free-Hit squad snapshot for revert after GW."""
    __tablename__ = "user_squad_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    team_id: Mapped[int] = mapped_column(Integer)
    snapshot_gw: Mapped[int] = mapped_column(Integer)       # GW when Free Hit was activated
    picks_json: Mapped[str] = mapped_column(Text)           # JSON serialized picks
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_squad_snapshots_team_gw", "team_id", "snapshot_gw"),
    )


class UserBank(Base):
    """Per-team financial state and chip tracking."""
    __tablename__ = "user_bank"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    team_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    team_name: Mapped[str] = mapped_column(String(200), default="")
    player_first_name: Mapped[str] = mapped_column(String(100), default="")
    player_last_name: Mapped[str] = mapped_column(String(100), default="")

    # Financial state
    free_transfers: Mapped[int] = mapped_column(Integer, default=1)
    bank: Mapped[int] = mapped_column(Integer, default=0)           # pence remaining
    value: Mapped[int] = mapped_column(Integer, default=1000)       # total squad value in pence

    # Performance
    overall_rank: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_points: Mapped[int] = mapped_column(Integer, default=0)
    last_deadline_bank: Mapped[int] = mapped_column(Integer, default=0)
    last_deadline_value: Mapped[int] = mapped_column(Integer, default=1000)
    last_deadline_total_transfers: Mapped[int] = mapped_column(Integer, default=0)

    # Chip tracking — 2025/26 rule: each chip available once per half (GW1-18 / GW20-38)
    wildcard_1_used_gw: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    wildcard_2_used_gw: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    free_hit_1_used_gw: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    free_hit_2_used_gw: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    bench_boost_1_used_gw: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    bench_boost_2_used_gw: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    triple_captain_1_used_gw: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    triple_captain_2_used_gw: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def get_current_half(self, current_gw: int) -> str:
        return "first" if current_gw <= 18 else "second"

    def chip_available(self, chip: str, current_gw: int) -> bool:
        """Check if a chip is available in the current half."""
        half = self.get_current_half(current_gw)
        col = f"{chip}_{'1' if half == 'first' else '2'}_used_gw"
        return getattr(self, col, None) is None

    def __repr__(self) -> str:
        return f"<UserBank team={self.team_id} ft={self.free_transfers} bank={self.bank}>"

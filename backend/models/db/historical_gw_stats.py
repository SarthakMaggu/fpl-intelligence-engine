"""
Historical GW Stats — raw per-player per-GW data ingested from the vaastav
Fantasy-Premier-League open dataset.

https://github.com/vaastav/Fantasy-Premier-League

One row per (player_id, gw, season).  This table is the source of truth for
historical model training and backtesting across past seasons.

Separate from `player_gw_history` which stores live-season FPL API data.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import Boolean, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class HistoricalGWStats(Base):
    """Raw per-player per-GW stats from the vaastav open dataset."""

    __tablename__ = "historical_gw_stats"
    __table_args__ = (
        UniqueConstraint("player_id", "gw", "season", name="uq_hgws_player_gw_season"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Season identifier, e.g. "2022-23", "2023-24", "2024-25"
    season: Mapped[str] = mapped_column(String(16), nullable=False, index=True)

    # vaastav column `element` → FPL player ID
    player_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    # vaastav column `round` → GW number (1–38)
    gw: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    # Position as in vaastav ("GKP", "DEF", "MID", "FWD")
    position: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)

    # ── Core performance ────────────────────────────────────────────────────
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

    # ── Advanced / ICT ──────────────────────────────────────────────────────
    ict_index: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    creativity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    threat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    influence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # ── Price / ownership ───────────────────────────────────────────────────
    value: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)       # pence × 10
    selected: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)    # ownership count
    transfers_in: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    transfers_out: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # ── Match context ───────────────────────────────────────────────────────
    was_home: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    team_h_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    team_a_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    opponent_team: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # ── Expected stats ──────────────────────────────────────────────────────
    # vaastav column `xP` — per-GW expected FPL points (from underlying xG/xA)
    expected_points: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    expected_goals: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    expected_assists: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<HistoricalGWStats player={self.player_id} gw={self.gw} "
            f"season={self.season} pts={self.total_points}>"
        )

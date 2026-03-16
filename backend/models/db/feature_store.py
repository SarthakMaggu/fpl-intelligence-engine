"""
Feature Store — lightweight per-player feature snapshot per GW.

player_features_latest: one row per player, always the most recent GW's features.
player_features_history: append-only log, one row per (player, gw).

Used by the backtest engine and model evaluation to replay exact features
that were available at decision time without recomputing them.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from sqlalchemy import DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class PlayerFeaturesLatest(Base):
    """One row per player — overwritten each GW pipeline run."""

    __tablename__ = "player_features_latest"

    player_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    gw_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    features_json: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<PlayerFeaturesLatest player={self.player_id} gw={self.gw_id}>"


class PlayerFeaturesHistory(Base):
    """
    Append-only log — one row per (player_id, gw_id, season), never updated.

    `season` distinguishes historical GW data (e.g. "2022-23") from current-season
    data ("2024-25") so GW numbers 1–38 don't collide across seasons.
    Existing rows (pre-season column) default to "2024-25".
    """

    __tablename__ = "player_features_history"
    __table_args__ = (
        # Dropped: uq_pfh_player_gw (player_id, gw_id)
        # Replaced by: uq_pfh_player_gw_season (player_id, gw_id, season)
        # Migration is applied in main.py startup.
        UniqueConstraint("player_id", "gw_id", "season", name="uq_pfh_player_gw_season"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    gw_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    # Season tag — "2024-25" for current-season features, "2022-23"/"2023-24" for historical
    season: Mapped[str] = mapped_column(
        String(16), nullable=False, default="2024-25", index=True
    )
    features_json: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<PlayerFeaturesHistory player={self.player_id} gw={self.gw_id} season={self.season}>"

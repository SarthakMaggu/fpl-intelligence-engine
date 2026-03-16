"""
ModelRegistry — versioned ML model artefacts with train/val metrics.

Each time the xPts model is retrained (MAE-triggered or manual), a new row is
inserted with the artefact path and evaluation metrics. Only one row should
have is_current_production=True at any time.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class ModelRegistry(Base):
    __tablename__ = "model_registry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Identity
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)   # e.g. "xpts_lgbm"
    version: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)  # "2026.03.15.001"

    # Training window
    train_gw_start: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    train_gw_end: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    train_seasons: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )  # JSON list, e.g. '["2023-24","2024-25"]'

    # Evaluation metrics (on held-out validation set)
    val_mae: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    val_rmse: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    val_rank_corr: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    val_top10_hit_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Artefact storage
    artifact_path: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True
    )  # path inside model_artifacts Docker volume

    # Production flag — only one row True at a time
    is_current_production: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<ModelRegistry {self.model_name}@{self.version} "
            f"mae={self.val_mae} prod={self.is_current_production}>"
        )

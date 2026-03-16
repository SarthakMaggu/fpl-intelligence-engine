from sqlalchemy import Integer, Float, String, DateTime, Index, UniqueConstraint
from sqlalchemy.orm import mapped_column, Mapped
from datetime import datetime
from typing import Optional
from core.database import Base


class Prediction(Base):
    """ML model predictions per player per gameweek."""
    __tablename__ = "predictions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(Integer)
    gameweek_id: Mapped[int] = mapped_column(Integer)

    predicted_xpts: Mapped[float] = mapped_column(Float, default=0.0)
    predicted_start_prob: Mapped[float] = mapped_column(Float, default=0.0)
    predicted_60min_prob: Mapped[float] = mapped_column(Float, default=0.0)
    predicted_price_direction: Mapped[int] = mapped_column(Integer, default=0)  # -1/0/1
    predicted_expected_minutes: Mapped[float] = mapped_column(Float, default=0.0)
    predicted_goal_prob: Mapped[float] = mapped_column(Float, default=0.0)
    predicted_assist_prob: Mapped[float] = mapped_column(Float, default=0.0)
    predicted_clean_sheet_prob: Mapped[float] = mapped_column(Float, default=0.0)
    predicted_card_prob: Mapped[float] = mapped_column(Float, default=0.0)
    predicted_bonus_points: Mapped[float] = mapped_column(Float, default=0.0)
    predicted_bench_prob: Mapped[float] = mapped_column(Float, default=0.0)
    predicted_sub_appearance_prob: Mapped[float] = mapped_column(Float, default=0.0)

    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    model_version: Mapped[str] = mapped_column(String(50), default="v1.0")
    data_snapshot_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    feature_version_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    model_version_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_predictions_player_gw", "player_id", "gameweek_id"),
        UniqueConstraint("player_id", "gameweek_id", "model_version", name="uq_prediction"),
    )

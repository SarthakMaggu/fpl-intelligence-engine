from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class DataSnapshot(Base):
    __tablename__ = "data_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="pipeline")
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class FeatureVersion(Base):
    __tablename__ = "feature_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    training_distribution_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class ModelVersion(Base):
    __tablename__ = "model_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    artifact_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    metrics_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class PredictionEvaluation(Base):
    __tablename__ = "prediction_evaluation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    gameweek_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    predicted_points: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    actual_points: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    error: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    model_version_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    feature_version_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    data_snapshot_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class FeatureDriftResult(Base):
    __tablename__ = "feature_drift_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    feature_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    feature_version_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    drift_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.2)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ok")
    details_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


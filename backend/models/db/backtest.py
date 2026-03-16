"""
Backtest metric tables — offline simulation results.

backtest_model_metrics:   per-GW accuracy of a model version on historical data
backtest_strategy_metrics: per-GW cumulative points of a decision strategy
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class BacktestModelMetrics(Base):
    """
    Accuracy metrics for a given model version on a specific GW.

    `season` distinguishes multi-season historical backtests — the same GW number
    (e.g. GW 1) exists in every season, so (model_version, gw_id, season) is unique.
    Existing rows default season to "2024-25" via migration in main.py startup.
    """

    __tablename__ = "backtest_model_metrics"
    __table_args__ = (
        # Replaced uq_bmm_version_gw (model_version, gw_id)
        # with uq_bmm_version_gw_season (model_version, gw_id, season)
        UniqueConstraint("model_version", "gw_id", "season", name="uq_bmm_version_gw_season"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_version: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    gw_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    # Season the GW belongs to, e.g. "2022-23", "2023-24", "2024-25"
    season: Mapped[str] = mapped_column(
        String(16), nullable=False, default="2024-25", index=True
    )

    mae: Mapped[float] = mapped_column(Float, nullable=False)
    rmse: Mapped[float] = mapped_column(Float, nullable=False)
    rank_corr: Mapped[float] = mapped_column(Float, nullable=False)
    top_10_hit_rate: Mapped[float] = mapped_column(
        Float, nullable=False
    )  # fraction of top-10 actual scorers in top-10 predicted

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<BacktestModelMetrics model={self.model_version} gw={self.gw_id} "
            f"season={self.season} mae={self.mae:.3f}>"
        )


class BacktestStrategyMetrics(Base):
    """Simulated season performance for a named decision strategy."""

    __tablename__ = "backtest_strategy_metrics"
    __table_args__ = (
        UniqueConstraint("strategy_name", "season", "gw_id", name="uq_bsm_strategy_season_gw"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strategy_name: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )  # e.g. "bandit_ilp" | "greedy_xpts" | "baseline_no_transfer"
    gw_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    season: Mapped[str] = mapped_column(String(16), nullable=False)  # e.g. "2024-25"

    gw_points: Mapped[float] = mapped_column(Float, nullable=False)
    cumulative_points: Mapped[float] = mapped_column(Float, nullable=False)
    rank_simulated: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<BacktestStrategyMetrics strategy={self.strategy_name} "
            f"season={self.season} gw={self.gw_id} cumpts={self.cumulative_points:.1f}>"
        )

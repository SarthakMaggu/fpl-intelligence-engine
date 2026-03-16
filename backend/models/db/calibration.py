"""
Prediction Calibration and Points Distribution DB models.

PredictionCalibration — tracks predicted vs actual for Bayesian correction.
PointsDistribution    — stores Monte Carlo simulation percentiles per player.
"""
from datetime import datetime

from sqlalchemy import Integer, Float, String, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import mapped_column, Mapped

from core.database import Base


class PredictionCalibration(Base):
    """Tracks prediction accuracy for Bayesian EMA calibration."""
    __tablename__ = "prediction_calibration"
    __table_args__ = (
        UniqueConstraint("player_id", "gameweek_id", name="uq_calibration_player_gw"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(Integer, ForeignKey("players.id", ondelete="CASCADE"))
    gameweek_id: Mapped[int] = mapped_column(Integer, ForeignKey("gameweeks.id", ondelete="CASCADE"))

    predicted_xpts: Mapped[float] = mapped_column(Float, default=0.0)
    actual_points: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[float] = mapped_column(Float, default=0.0)          # actual - predicted
    abs_error: Mapped[float] = mapped_column(Float, default=0.0)      # |error|
    model_version: Mapped[str] = mapped_column(String(32), default="v1")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return (
            f"<PredictionCalibration player={self.player_id} "
            f"gw={self.gameweek_id} err={self.error:.2f}>"
        )


class PointsDistribution(Base):
    """Monte Carlo simulation outputs — probability distribution over GW points."""
    __tablename__ = "points_distribution"
    __table_args__ = (
        UniqueConstraint("player_id", "gameweek_id", name="uq_distribution_player_gw"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(Integer, ForeignKey("players.id", ondelete="CASCADE"))
    gameweek_id: Mapped[int] = mapped_column(Integer, ForeignKey("gameweeks.id", ondelete="CASCADE"))

    # Distribution stats
    mean_xpts: Mapped[float] = mapped_column(Float, default=0.0)
    std_xpts: Mapped[float] = mapped_column(Float, default=0.0)
    p10: Mapped[float] = mapped_column(Float, default=0.0)     # 10th percentile
    p25: Mapped[float] = mapped_column(Float, default=0.0)     # 25th percentile
    p50: Mapped[float] = mapped_column(Float, default=0.0)     # median
    p75: Mapped[float] = mapped_column(Float, default=0.0)     # 75th percentile
    p90: Mapped[float] = mapped_column(Float, default=0.0)     # 90th percentile

    # Key probability thresholds
    prob_blank: Mapped[float] = mapped_column(Float, default=0.0)     # P(≤2 pts)
    prob_5_plus: Mapped[float] = mapped_column(Float, default=0.0)    # P(≥5 pts)
    prob_10_plus: Mapped[float] = mapped_column(Float, default=0.0)   # P(≥10 pts)

    # Rank impact
    rank_volatility_score: Mapped[float] = mapped_column(Float, default=0.0)

    n_simulations: Mapped[int] = mapped_column(Integer, default=2000)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return (
            f"<PointsDistribution player={self.player_id} "
            f"gw={self.gameweek_id} mean={self.mean_xpts:.1f}>"
        )

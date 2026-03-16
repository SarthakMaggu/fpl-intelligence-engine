"""
DecisionLog — persistent record of every AI recommendation and user outcome.

Enables GW review: did following AI advice gain or lose rank?
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import Integer, Float, String, Boolean, DateTime, ForeignKey, Text, Index
from sqlalchemy.orm import mapped_column, Mapped

from core.database import Base


class DecisionLog(Base):
    """
    Records each recommended decision and the eventual outcome.

    Lifecycle:
      1. On recommendation:  INSERT with recommended_option, expected_points, decision_followed=None
      2. After GW:           UPDATE with actual_points, decision_followed, rank_delta
    """
    __tablename__ = "decision_log"
    __table_args__ = (
        # Composite index for the most common query pattern: list decisions for a team+GW
        Index("ix_decision_log_team_gw", "team_id", "gameweek_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    team_id: Mapped[int] = mapped_column(Integer, index=True)
    gameweek_id: Mapped[int] = mapped_column(Integer, ForeignKey("gameweeks.id", ondelete="CASCADE"))

    # Decision metadata
    decision_type: Mapped[str] = mapped_column(String(64))   # transfer | captain | chip | hit
    recommended_option: Mapped[str] = mapped_column(String(128))  # e.g. "Salah → Mbappé"
    user_choice: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    # Prediction vs outcome
    expected_points: Mapped[float] = mapped_column(Float, default=0.0)
    actual_points: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Did the user follow the AI recommendation?
    decision_followed: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    # Rank context
    rank_before: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rank_after: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rank_delta: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # positive = improved

    # Free-text reasoning from the AI at decision time
    reasoning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # user notes

    # --- Phase 3: Bandit wiring & reward loop ---
    # Whether the user took a -4pt transfer hit for this decision (affects reward)
    hit_taken: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Which bandit arm drove this recommendation (e.g. "ilp_optimizer", "top_xpts")
    engine_strategy_arm: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # Model confidence at recommendation time (0–1)
    engine_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Predicted pts delta vs baseline at recommendation time
    engine_predicted_gain: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # User's recorded action (followed / ignored / partially_followed)
    user_action: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    # Computed post-GW reward signal (clipped to [-1, 1])
    reward: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Flipped to True after auto_resolve_oracle processes this row
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    # Quant decision synthesis metadata
    decision_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    validation_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    risk_preference: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    floor_projection: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    median_projection: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ceiling_projection: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    projection_variance: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    explanation_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    inputs_used_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    simulation_summary_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<DecisionLog team={self.team_id} gw={self.gameweek_id} "
            f"type={self.decision_type} followed={self.decision_followed}>"
        )

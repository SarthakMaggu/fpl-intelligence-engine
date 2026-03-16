"""RL/Bandit decision tracking model."""
from sqlalchemy import String, Integer, Float, Text, DateTime, Index, UniqueConstraint
from sqlalchemy.orm import mapped_column, Mapped
from datetime import datetime
from typing import Optional
from core.database import Base


class BanditDecision(Base):
    """
    Tracks each FPL decision made under bandit guidance.

    After each GW completes, actual_value is filled in and reward computed.
    The bandit uses reward history to update Q-values for future decisions.
    """
    __tablename__ = "bandit_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    team_id: Mapped[int] = mapped_column(Integer, index=True)
    gw_id: Mapped[int] = mapped_column(Integer)

    # Which category of decision
    # "transfer_strategy" | "captain_pick" | "chip_timing" | "hit_decision"
    decision_type: Mapped[str] = mapped_column(String(50))

    # Which arm was recommended/chosen
    # transfer_strategy: "greedy" | "ilp" | "hold"
    # captain_pick:      "top_xpts" | "differential" | "form_weighted"
    # chip_timing:       "play_now" | "wait_1_gw" | "skip"
    # hit_decision:      "take_hit" | "hold"
    arm_chosen: Mapped[str] = mapped_column(String(50))

    # Context snapshot (JSON) — e.g. {"captain_xpts": 10.8, "ownership": 0.40}
    context_json: Mapped[str] = mapped_column(Text, default="{}")

    # Predicted value at decision time (xPts or confidence score)
    predicted_value: Mapped[float] = mapped_column(Float, default=0.0)

    # Actual value after GW results (filled by /api/bandit/outcome)
    actual_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # reward = actual_value - predicted_value (positive = better than expected)
    reward: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_bandit_team_gw", "team_id", "gw_id"),
        Index("ix_bandit_type", "decision_type"),
    )

    def __repr__(self) -> str:
        return f"<BanditDecision team={self.team_id} gw={self.gw_id} type={self.decision_type} arm={self.arm_chosen}>"

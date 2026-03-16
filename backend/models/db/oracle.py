"""
GW Oracle — stores the theoretically best possible team for each gameweek.

The oracle runs the ILP with:
  - £100m budget (1000 pence), unlimited transfers, no hit cost
  - All available players in the pool (ignores current squad)
  - Best formation within FPL rules (1 GK + min 3 DEF + min 2 FWD + 10 outfield)
  - No chip bonuses (pure prediction quality benchmark)

Captured at each GW deadline. After the GW completes, actual_oracle_points
is filled via the resolve endpoint so we can see how the oracle prediction
compared to reality over time.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import Integer, Float, String, Boolean, DateTime, Text, JSON, UniqueConstraint, Index
from sqlalchemy.orm import mapped_column, Mapped

from core.database import Base


class GWOracle(Base):
    """
    One row per (team_id, gameweek_id) — the oracle snapshot.

    oracle_squad_json:  list of 15 player IDs (optimal 15 within £100m)
    oracle_xi_json:     list of 11 player IDs (optimal starting XI)
    algo_squad_json:    list of 15 player IDs that were in user's actual squad
                        at snapshot time (what the user had, not what was suggested)
    """
    __tablename__ = "gw_oracle"
    __table_args__ = (
        UniqueConstraint("team_id", "gameweek_id", name="uq_gw_oracle_team_gw"),
        Index("ix_gw_oracle_team_gw", "team_id", "gameweek_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    team_id: Mapped[int] = mapped_column(Integer, nullable=False)
    gameweek_id: Mapped[int] = mapped_column(Integer, nullable=False)

    # Oracle — theoretically best £100m team, unlimited transfers
    oracle_squad_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON list of 15 IDs
    oracle_xi_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)     # JSON list of 11 IDs
    oracle_formation: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    oracle_xpts: Mapped[Optional[float]] = mapped_column(Float, nullable=True)     # Predicted total XI xPts
    oracle_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)     # Total squad cost (pence)
    oracle_captain_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    oracle_captain_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    oracle_captain_xpts: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    oracle_squad_names: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON list of names

    # Actual squad at snapshot time (user's real 15 for comparison)
    algo_squad_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    algo_xpts: Mapped[Optional[float]] = mapped_column(Float, nullable=True)       # Predicted XI xPts for user squad

    # Post-GW resolution — filled after the GW completes
    actual_oracle_points: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    actual_algo_points: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    oracle_beat_algo: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    # Top FPL team of the week — fetched after GW resolves for comparison + learning
    top_team_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    top_team_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    top_team_points: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    top_team_points_normalized: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    top_team_chip_adjustment: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    top_team_squad_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)   # JSON list of player names
    top_team_captain: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    top_team_chip: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    chip_miss_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    top_team_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    oracle_beat_top: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    missed_players_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)   # players top team had, oracle missed
    oracle_blind_spots_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # pattern learning notes

    snapshot_taken_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<GWOracle team={self.team_id} gw={self.gameweek_id} "
            f"oracle_xpts={self.oracle_xpts} formation={self.oracle_formation}>"
        )

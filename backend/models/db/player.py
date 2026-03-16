from sqlalchemy import String, Integer, Float, Boolean, DateTime, Text, Index
from sqlalchemy.orm import mapped_column, Mapped
from datetime import datetime
from core.database import Base


class Player(Base):
    __tablename__ = "players"

    # FPL identifiers
    id: Mapped[int] = mapped_column(Integer, primary_key=True)       # FPL element ID
    code: Mapped[int] = mapped_column(Integer, unique=True, index=True)  # FPL photo code
    web_name: Mapped[str] = mapped_column(String(100))
    first_name: Mapped[str] = mapped_column(String(100), default="")
    second_name: Mapped[str] = mapped_column(String(100), default="")

    # Position: 1=GK, 2=DEF, 3=MID, 4=FWD
    element_type: Mapped[int] = mapped_column(Integer)
    team_id: Mapped[int] = mapped_column(Integer)

    # Pricing (stored as int × 10p — 55 = £5.5m)
    now_cost: Mapped[int] = mapped_column(Integer, default=0)
    cost_change_start: Mapped[int] = mapped_column(Integer, default=0)

    # Ownership + form
    selected_by_percent: Mapped[float] = mapped_column(Float, default=0.0)
    form: Mapped[float] = mapped_column(Float, default=0.0)
    form_trend: Mapped[str] = mapped_column(String(10), default="stable")  # rising/falling/stable
    total_points: Mapped[int] = mapped_column(Integer, default=0)
    points_per_game: Mapped[float] = mapped_column(Float, default=0.0)
    event_points: Mapped[int] = mapped_column(Integer, default=0)

    # Transfer data (for price prediction)
    transfers_in_event: Mapped[int] = mapped_column(Integer, default=0)
    transfers_out_event: Mapped[int] = mapped_column(Integer, default=0)
    transfers_in: Mapped[int] = mapped_column(Integer, default=0)
    transfers_out: Mapped[int] = mapped_column(Integer, default=0)

    # Season stats from FPL API
    minutes: Mapped[int] = mapped_column(Integer, default=0)
    goals_scored: Mapped[int] = mapped_column(Integer, default=0)
    assists: Mapped[int] = mapped_column(Integer, default=0)
    clean_sheets: Mapped[int] = mapped_column(Integer, default=0)
    goals_conceded: Mapped[int] = mapped_column(Integer, default=0)
    own_goals: Mapped[int] = mapped_column(Integer, default=0)
    penalties_saved: Mapped[int] = mapped_column(Integer, default=0)
    penalties_missed: Mapped[int] = mapped_column(Integer, default=0)
    yellow_cards: Mapped[int] = mapped_column(Integer, default=0)
    red_cards: Mapped[int] = mapped_column(Integer, default=0)
    saves: Mapped[int] = mapped_column(Integer, default=0)
    bonus: Mapped[int] = mapped_column(Integer, default=0)
    bps: Mapped[int] = mapped_column(Integer, default=0)
    influence: Mapped[float] = mapped_column(Float, default=0.0)
    creativity: Mapped[float] = mapped_column(Float, default=0.0)
    threat: Mapped[float] = mapped_column(Float, default=0.0)
    ict_index: Mapped[float] = mapped_column(Float, default=0.0)

    # Expected stats from FPL API (available from GW1)
    expected_goals: Mapped[float] = mapped_column(Float, default=0.0)
    expected_assists: Mapped[float] = mapped_column(Float, default=0.0)
    expected_goal_involvements: Mapped[float] = mapped_column(Float, default=0.0)
    expected_goals_conceded: Mapped[float] = mapped_column(Float, default=0.0)

    # xG/xA from understat (per-90 metrics)
    xg_per_90: Mapped[float] = mapped_column(Float, default=0.0)
    xa_per_90: Mapped[float] = mapped_column(Float, default=0.0)
    npxg_per_90: Mapped[float] = mapped_column(Float, default=0.0)
    xg_season: Mapped[float] = mapped_column(Float, default=0.0)
    xa_season: Mapped[float] = mapped_column(Float, default=0.0)
    understat_id: Mapped[str] = mapped_column(String(20), default="")

    # Set piece taker (inferred from creativity + assists)
    is_set_piece_taker: Mapped[bool] = mapped_column(Boolean, default=False)

    # Injury/status
    status: Mapped[str] = mapped_column(String(1), default="a")  # a/d/i/s/u/n
    chance_of_playing_this_round: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chance_of_playing_next_round: Mapped[int | None] = mapped_column(Integer, nullable=True)
    news: Mapped[str] = mapped_column(Text, default="")
    news_added: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Suspension risk (yellow card accumulation)
    suspension_risk: Mapped[bool] = mapped_column(Boolean, default=False)

    # Fixture context (updated each GW sync)
    fdr_next: Mapped[int] = mapped_column(Integer, default=3)
    is_home_next: Mapped[bool] = mapped_column(Boolean, default=True)
    has_blank_gw: Mapped[bool] = mapped_column(Boolean, default=False)
    has_double_gw: Mapped[bool] = mapped_column(Boolean, default=False)

    # ML predictions (updated nightly)
    predicted_xpts_next: Mapped[float] = mapped_column(Float, default=0.0)
    predicted_start_prob: Mapped[float] = mapped_column(Float, default=0.0)
    predicted_60min_prob: Mapped[float] = mapped_column(Float, default=0.0)
    predicted_price_direction: Mapped[int] = mapped_column(Integer, default=0)  # -1/0/1

    # Metadata
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        Index("ix_players_team_id", "team_id"),
        Index("ix_players_element_type", "element_type"),
        Index("ix_players_predicted_xpts", "predicted_xpts_next"),
        Index("ix_players_selected_by", "selected_by_percent"),
    )

    def __repr__(self) -> str:
        return f"<Player id={self.id} name={self.web_name} pos={self.element_type}>"

from sqlalchemy import String, Integer, Boolean
from sqlalchemy.orm import mapped_column, Mapped
from core.database import Base


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)      # FPL team ID
    code: Mapped[int] = mapped_column(Integer, unique=True)         # FPL club code
    name: Mapped[str] = mapped_column(String(100))
    short_name: Mapped[str] = mapped_column(String(10))
    pulse_id: Mapped[int] = mapped_column(Integer, default=0)

    # Strength ratings (used in xPts feature matrix)
    strength_overall_home: Mapped[int] = mapped_column(Integer, default=3)
    strength_overall_away: Mapped[int] = mapped_column(Integer, default=3)
    strength_attack_home: Mapped[int] = mapped_column(Integer, default=3)
    strength_attack_away: Mapped[int] = mapped_column(Integer, default=3)
    strength_defence_home: Mapped[int] = mapped_column(Integer, default=3)
    strength_defence_away: Mapped[int] = mapped_column(Integer, default=3)

    # Season stats
    played: Mapped[int] = mapped_column(Integer, default=0)
    win: Mapped[int] = mapped_column(Integer, default=0)
    draw: Mapped[int] = mapped_column(Integer, default=0)
    loss: Mapped[int] = mapped_column(Integer, default=0)
    points: Mapped[int] = mapped_column(Integer, default=0)
    position: Mapped[int] = mapped_column(Integer, default=0)

    unavailable: Mapped[bool] = mapped_column(Boolean, default=False)

    def __repr__(self) -> str:
        return f"<Team id={self.id} name={self.short_name}>"

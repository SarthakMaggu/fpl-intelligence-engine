import os
import sys
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

# Add backend dir to path so model imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.config import settings
from core.database import Base

# ── Import every model so Alembic's autogenerate sees all tables ────────────
from models.db.player import Player  # noqa: F401
from models.db.team import Team  # noqa: F401
from models.db.gameweek import Gameweek, Fixture  # noqa: F401
from models.db.user_squad import UserSquad, UserSquadSnapshot, UserBank  # noqa: F401
from models.db.prediction import Prediction  # noqa: F401
from models.db.rival import Rival  # noqa: F401
from models.db.history import UserGWHistory, PlayerGWHistory  # noqa: F401
from models.db.decision_log import DecisionLog  # noqa: F401
from models.db.oracle import GWOracle  # noqa: F401
from models.db.user_profile import UserProfile  # noqa: F401
from models.db.waitlist import Waitlist  # noqa: F401
from models.db.anonymous_session import AnonymousAnalysisSession  # noqa: F401
from models.db.bandit import BanditDecision  # noqa: F401
from models.db.feature_store import PlayerFeaturesLatest, PlayerFeaturesHistory  # noqa: F401
from models.db.model_registry import ModelRegistry  # noqa: F401
from models.db.backtest import BacktestModelMetrics, BacktestStrategyMetrics  # noqa: F401
from models.db.calibration import PredictionCalibration, PointsDistribution  # noqa: F401
from models.db.background_job import BackgroundJob  # noqa: F401
from models.db.competition_fixture import CompetitionFixture  # noqa: F401
from models.db.historical_gw_stats import HistoricalGWStats  # noqa: F401
from models.db.versioning import (  # noqa: F401
    DataSnapshot,
    FeatureVersion,
    ModelVersion,
    PredictionEvaluation,
    FeatureDriftResult,
)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _build_sync_url() -> str:
    """
    Build a synchronous psycopg2 URL for Alembic.

    Handles every URL scheme that Railway, Docker Compose, or a .env might inject:
      postgres://...            → postgresql+psycopg2://...  (Railway plugin default)
      postgresql://...          → postgresql+psycopg2://...
      postgresql+asyncpg://...  → postgresql+psycopg2://...  (.env.example default)
      postgresql+psycopg2://... → unchanged (already correct)

    Priority:
      1. DATABASE_URL environment variable  (Railway injects this)
      2. DATABASE_PRIVATE_URL               (Railway private networking fallback)
      3. settings.DATABASE_URL              (pydantic-settings / .env file fallback)
    """
    raw = (
        os.environ.get("DATABASE_URL")
        or os.environ.get("DATABASE_PRIVATE_URL")
        or settings.DATABASE_URL
    )

    for prefix in ("postgres://", "postgresql://", "postgresql+asyncpg://"):
        if raw.startswith(prefix):
            return "postgresql+psycopg2://" + raw[len(prefix):]

    # Already postgresql+psycopg2:// or unrecognised — return unchanged
    return raw


config.set_main_option("sqlalchemy.url", _build_sync_url())


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

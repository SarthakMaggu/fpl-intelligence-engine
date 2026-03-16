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
    Build a synchronous psycopg2 URL for Alembic migrations.

    Resolution order — most reliable first:

    1. PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE
       Railway's PostgreSQL plugin injects these individually.
       They are PLUGIN variables — they cannot be overridden by a user
       clicking "Import variables from source code" in Railway's UI,
       which is the most common cause of DATABASE_URL being set to
       a localhost value that breaks migrations on Railway.

    2. DATABASE_URL / DATABASE_PRIVATE_URL env var
       Used when PGHOST is absent or is localhost (local Docker Compose).

    3. settings.DATABASE_URL
       Pydantic default — local development fallback only.
    """
    # Step 1: individual PG* vars (Railway plugin — cannot be user-overridden)
    pg_host = os.environ.get("PGHOST", "")
    if pg_host and pg_host not in ("localhost", "127.0.0.1"):
        pg_port = os.environ.get("PGPORT", "5432")
        pg_user = os.environ.get("PGUSER", "postgres")
        pg_pass = os.environ.get("PGPASSWORD", "")
        pg_db   = os.environ.get("PGDATABASE", "railway")
        return f"postgresql+psycopg2://{pg_user}:{pg_pass}@{pg_host}:{pg_port}/{pg_db}"

    # Step 2: full URL env var (docker-compose or correctly configured Railway)
    raw = (
        os.environ.get("DATABASE_URL")
        or os.environ.get("DATABASE_PRIVATE_URL")
        or settings.DATABASE_URL
    )

    for prefix in ("postgres://", "postgresql://", "postgresql+asyncpg://"):
        if raw.startswith(prefix):
            return "postgresql+psycopg2://" + raw[len(prefix):]

    return raw  # already postgresql+psycopg2:// or unrecognised


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

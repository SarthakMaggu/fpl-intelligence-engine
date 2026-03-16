import os
import sys
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

# Add backend dir to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.config import settings
from core.database import Base

# Import all models so Alembic sees them
from models.db.player import Player  # noqa: F401
from models.db.team import Team  # noqa: F401
from models.db.gameweek import Gameweek, Fixture  # noqa: F401
from models.db.user_squad import UserSquad, UserSquadSnapshot, UserBank  # noqa: F401
from models.db.prediction import Prediction  # noqa: F401
from models.db.rival import Rival  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Override alembic.ini URL with settings (sync psycopg2 for migrations)
sync_url = settings.DATABASE_URL.replace("+asyncpg", "+psycopg2")
config.set_main_option("sqlalchemy.url", sync_url)


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

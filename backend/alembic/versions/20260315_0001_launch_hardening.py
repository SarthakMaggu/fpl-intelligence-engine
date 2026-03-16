"""launch hardening — initial schema

Revision ID: 20260315_0001
Revises:
Create Date: 2026-03-15 22:15:00.000000

Strategy: use SQLAlchemy's create_all(checkfirst=True) so the models are
the single source of truth for the schema. This creates every table that
doesn't exist yet (fresh DB) and is a no-op for tables that already exist.
All subsequent migrations use inspector-based column checks so they are safe
to run regardless of whether create_all already added the columns.
"""

from alembic import op


revision = "20260315_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    from core.database import Base

    # Create every table defined in models that doesn't exist yet.
    # On a fresh DB this creates the full schema in one shot.
    # On an existing DB this is a no-op for tables that already exist.
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    pass  # intentionally empty — dropping the full schema is a manual operation

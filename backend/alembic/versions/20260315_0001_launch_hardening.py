"""launch hardening

Revision ID: 20260315_0001
Revises:
Create Date: 2026-03-15 22:15:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260315_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect
    from core.database import Base

    bind = op.get_bind()

    # ── Step 1: create every table that doesn't exist yet ─────────────────────
    # On a fresh Railway DB this creates ALL tables (players, predictions,
    # waitlist, background_jobs, decision_log, etc.) with their FULL current
    # schema in one shot.
    # On an existing DB, checkfirst=True skips tables that already exist.
    Base.metadata.create_all(bind=bind, checkfirst=True)

    inspector = inspect(bind)

    # ── Step 2: add columns to predictions only if missing ────────────────────
    # create_all(checkfirst=True) skips EXISTING tables, so existing DBs that
    # already had a predictions table without these columns need them added here.
    pred_cols = {c["name"] for c in inspector.get_columns("predictions")}
    for col_name, col_type in [
        ("predicted_expected_minutes", sa.Float()),
        ("predicted_goal_prob", sa.Float()),
        ("predicted_assist_prob", sa.Float()),
        ("predicted_clean_sheet_prob", sa.Float()),
        ("predicted_card_prob", sa.Float()),
        ("predicted_bonus_points", sa.Float()),
        ("predicted_bench_prob", sa.Float()),
        ("predicted_sub_appearance_prob", sa.Float()),
        ("data_snapshot_id", sa.Integer()),
        ("feature_version_id", sa.Integer()),
        ("model_version_id", sa.Integer()),
    ]:
        if col_name not in pred_cols:
            op.add_column("predictions", sa.Column(col_name, col_type, nullable=True))

    # ── Step 3: add columns to waitlist only if missing ───────────────────────
    wait_cols = {c["name"] for c in inspector.get_columns("waitlist")}
    for col_name, col_type in [
        ("position", sa.Integer()),
        ("promoted_at", sa.DateTime()),
    ]:
        if col_name not in wait_cols:
            op.add_column("waitlist", sa.Column(col_name, col_type, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("waitlist") as batch_op:
        batch_op.drop_column("promoted_at")
        batch_op.drop_column("position")

    with op.batch_alter_table("predictions") as batch_op:
        batch_op.drop_column("model_version_id")
        batch_op.drop_column("feature_version_id")
        batch_op.drop_column("data_snapshot_id")
        batch_op.drop_column("predicted_sub_appearance_prob")
        batch_op.drop_column("predicted_bench_prob")
        batch_op.drop_column("predicted_bonus_points")
        batch_op.drop_column("predicted_card_prob")
        batch_op.drop_column("predicted_clean_sheet_prob")
        batch_op.drop_column("predicted_assist_prob")
        batch_op.drop_column("predicted_goal_prob")
        batch_op.drop_column("predicted_expected_minutes")

    op.drop_table("background_jobs")
    op.drop_table("feature_drift_results")
    op.drop_table("prediction_evaluation")
    op.drop_table("model_versions")
    op.drop_table("feature_versions")
    op.drop_table("data_snapshots")
    op.drop_table("anonymous_analysis_session")

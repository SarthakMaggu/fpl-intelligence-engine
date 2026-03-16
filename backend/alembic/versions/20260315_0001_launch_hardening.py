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
    # waitlist, background_jobs, etc.) in one shot using the current models.
    # On an existing DB with tables already present, checkfirst=True is a no-op
    # for those tables and only creates genuinely missing ones.
    Base.metadata.create_all(bind=bind, checkfirst=True)

    inspector = inspect(bind)

    # ── Step 2: add new columns to predictions (idempotent) ───────────────────
    # create_all(checkfirst=True) skips tables that already exist, so existing
    # DBs won't get the new columns automatically — we add them here only when
    # they're missing.
    pred_cols = {c["name"] for c in inspector.get_columns("predictions")}
    float_cols = [
        "predicted_expected_minutes",
        "predicted_goal_prob",
        "predicted_assist_prob",
        "predicted_clean_sheet_prob",
        "predicted_card_prob",
        "predicted_bonus_points",
        "predicted_bench_prob",
        "predicted_sub_appearance_prob",
    ]
    int_cols = ["data_snapshot_id", "feature_version_id", "model_version_id"]

    for col_name in float_cols:
        if col_name not in pred_cols:
            op.add_column("predictions", sa.Column(col_name, sa.Float(), nullable=True))
    for col_name in int_cols:
        if col_name not in pred_cols:
            op.add_column("predictions", sa.Column(col_name, sa.Integer(), nullable=True))

    # ── Step 3: add new columns to waitlist (idempotent) ──────────────────────
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

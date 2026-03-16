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
    op.create_table(
        "anonymous_analysis_session",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_token", sa.String(length=128), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("client_ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("last_accessed_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_anonymous_analysis_session_session_token", "anonymous_analysis_session", ["session_token"], unique=True)
    op.create_index("ix_anonymous_analysis_session_team_id", "anonymous_analysis_session", ["team_id"], unique=False)

    op.create_table(
        "data_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("snapshot_key", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("source", sa.String(length=64), nullable=False, server_default="pipeline"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_data_snapshots_snapshot_key", "data_snapshots", ["snapshot_key"], unique=True)

    op.create_table(
        "feature_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("training_distribution_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_feature_versions_version", "feature_versions", ["version"], unique=True)

    op.create_table(
        "model_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("model_name", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("artifact_path", sa.String(length=512), nullable=True),
        sa.Column("metrics_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_model_versions_version", "model_versions", ["version"], unique=True)

    op.create_table(
        "prediction_evaluation",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.Column("gameweek_id", sa.Integer(), nullable=False),
        sa.Column("predicted_points", sa.Float(), nullable=False, server_default="0"),
        sa.Column("actual_points", sa.Float(), nullable=False, server_default="0"),
        sa.Column("error", sa.Float(), nullable=False, server_default="0"),
        sa.Column("model_version_id", sa.Integer(), nullable=True),
        sa.Column("feature_version_id", sa.Integer(), nullable=True),
        sa.Column("data_snapshot_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "feature_drift_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("feature_name", sa.String(length=128), nullable=False),
        sa.Column("feature_version_id", sa.Integer(), nullable=True),
        sa.Column("drift_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("threshold", sa.Float(), nullable=False, server_default="0.2"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="ok"),
        sa.Column("details_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "background_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("job_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_background_jobs_job_id", "background_jobs", ["job_id"], unique=True)

    with op.batch_alter_table("predictions") as batch_op:
        batch_op.add_column(sa.Column("predicted_expected_minutes", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("predicted_goal_prob", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("predicted_assist_prob", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("predicted_clean_sheet_prob", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("predicted_card_prob", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("predicted_bonus_points", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("predicted_bench_prob", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("predicted_sub_appearance_prob", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("data_snapshot_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("feature_version_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("model_version_id", sa.Integer(), nullable=True))

    with op.batch_alter_table("waitlist") as batch_op:
        batch_op.add_column(sa.Column("position", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("promoted_at", sa.DateTime(), nullable=True))


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

    op.drop_index("ix_background_jobs_job_id", table_name="background_jobs")
    op.drop_table("background_jobs")
    op.drop_table("feature_drift_results")
    op.drop_table("prediction_evaluation")
    op.drop_index("ix_model_versions_version", table_name="model_versions")
    op.drop_table("model_versions")
    op.drop_index("ix_feature_versions_version", table_name="feature_versions")
    op.drop_table("feature_versions")
    op.drop_index("ix_data_snapshots_snapshot_key", table_name="data_snapshots")
    op.drop_table("data_snapshots")
    op.drop_index("ix_anonymous_analysis_session_team_id", table_name="anonymous_analysis_session")
    op.drop_index("ix_anonymous_analysis_session_session_token", table_name="anonymous_analysis_session")
    op.drop_table("anonymous_analysis_session")

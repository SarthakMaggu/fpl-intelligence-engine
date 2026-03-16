"""quant decision engine metadata

Revision ID: 20260316_0002
Revises: 20260315_0001
Create Date: 2026-03-16 10:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260316_0002"
down_revision = "20260315_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect

    bind = op.get_bind()
    inspector = inspect(bind)

    # If the table doesn't exist at all, create_all in 0001 should have made it.
    # Guard here so we never crash on a missing table.
    if "decision_log" not in inspector.get_table_names():
        return

    existing_cols = {c["name"] for c in inspector.get_columns("decision_log")}

    new_cols = [
        ("decision_score", sa.Float()),
        ("validation_status", sa.String(length=32)),
        ("risk_preference", sa.String(length=32)),
        ("floor_projection", sa.Float()),
        ("median_projection", sa.Float()),
        ("ceiling_projection", sa.Float()),
        ("projection_variance", sa.Float()),
        ("explanation_summary", sa.Text()),
        ("inputs_used_json", sa.Text()),
        ("simulation_summary_json", sa.Text()),
    ]
    for col_name, col_type in new_cols:
        if col_name not in existing_cols:
            op.add_column("decision_log", sa.Column(col_name, col_type, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("decision_log") as batch_op:
        batch_op.drop_column("simulation_summary_json")
        batch_op.drop_column("inputs_used_json")
        batch_op.drop_column("explanation_summary")
        batch_op.drop_column("projection_variance")
        batch_op.drop_column("ceiling_projection")
        batch_op.drop_column("median_projection")
        batch_op.drop_column("floor_projection")
        batch_op.drop_column("risk_preference")
        batch_op.drop_column("validation_status")
        batch_op.drop_column("decision_score")

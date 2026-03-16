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
    with op.batch_alter_table("decision_log") as batch_op:
        batch_op.add_column(sa.Column("decision_score", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("validation_status", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("risk_preference", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("floor_projection", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("median_projection", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("ceiling_projection", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("projection_variance", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("explanation_summary", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("inputs_used_json", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("simulation_summary_json", sa.Text(), nullable=True))


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

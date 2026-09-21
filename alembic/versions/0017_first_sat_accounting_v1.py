"""Durable first-SAT accounting evidence with explicit unknown costs.

Revision ID: 0017_first_sat_accounting_v1
Revises: 0016_official_data_execution_v1
"""

from alembic import op
import sqlalchemy as sa


revision = "0017_first_sat_accounting_v1"
down_revision = "0016_official_data_execution_v1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "route_intelligence_purchases",
        sa.Column("accounting_evidence", sa.JSON(), nullable=True),
    )


def downgrade():
    op.drop_column("route_intelligence_purchases", "accounting_evidence")

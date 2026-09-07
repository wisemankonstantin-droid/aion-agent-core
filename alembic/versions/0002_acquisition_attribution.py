"""add acquisition attribution

Revision ID: 0002_acquisition_attribution
Revises: 0001_initial
"""
from alembic import op
import sqlalchemy as sa

revision = '0002_acquisition_attribution'
down_revision = '0001_initial'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('agents', sa.Column('acquisition_source', sa.String(length=120), nullable=True))
    op.add_column('agents', sa.Column('referrer', sa.String(length=160), nullable=True))
    op.create_index('ix_agents_acquisition_source', 'agents', ['acquisition_source'], unique=False)

def downgrade():
    op.drop_index('ix_agents_acquisition_source', table_name='agents')
    op.drop_column('agents', 'referrer')
    op.drop_column('agents', 'acquisition_source')

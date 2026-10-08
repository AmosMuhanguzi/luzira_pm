"""Add structured details to disciplinary incidents.

Revision ID: 7d3a9f4c2b81
Revises: 6a2c9e41b7d5
Create Date: 2026-10-08 13:45:00
"""
from alembic import op
import sqlalchemy as sa


revision = '7d3a9f4c2b81'
down_revision = '6a2c9e41b7d5'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('disciplinary_logs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('incident_time', sa.Time(), nullable=True))
        batch_op.add_column(
            sa.Column(
                'is_violent',
                sa.Boolean(),
                nullable=True,
            )
        )
        batch_op.add_column(sa.Column('injured_count', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('disciplinary_logs', schema=None) as batch_op:
        batch_op.drop_column('injured_count')
        batch_op.drop_column('is_violent')
        batch_op.drop_column('incident_time')

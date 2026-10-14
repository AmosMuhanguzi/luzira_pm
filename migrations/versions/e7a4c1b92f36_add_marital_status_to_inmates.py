"""Add marital status to inmates.

Revision ID: e7a4c1b92f36
Revises: d4f8b0c36e53
Create Date: 2026-10-14 13:25:00
"""
from alembic import op
import sqlalchemy as sa


revision = 'e7a4c1b92f36'
down_revision = 'd4f8b0c36e53'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('inmates', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('marital_status', sa.String(length=30), nullable=True)
        )


def downgrade():
    with op.batch_alter_table('inmates', schema=None) as batch_op:
        batch_op.drop_column('marital_status')

"""Add next court date to inmates.

Revision ID: d4f8b0c36e53
Revises: c3e7a9b25d42
Create Date: 2026-10-10 21:30:00
"""
from alembic import op
import sqlalchemy as sa


revision = 'd4f8b0c36e53'
down_revision = 'c3e7a9b25d42'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('inmates', schema=None) as batch_op:
        batch_op.add_column(sa.Column('next_court_date', sa.Date(), nullable=True))


def downgrade():
    with op.batch_alter_table('inmates', schema=None) as batch_op:
        batch_op.drop_column('next_court_date')

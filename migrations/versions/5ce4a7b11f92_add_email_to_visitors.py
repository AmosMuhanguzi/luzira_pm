"""Add email to visitors.

Revision ID: 5ce4a7b11f92
Revises: 3b6d1c9a4f20
Create Date: 2026-10-05 00:35:00
"""
from alembic import op
import sqlalchemy as sa


revision = '5ce4a7b11f92'
down_revision = '3b6d1c9a4f20'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('visitors', schema=None) as batch_op:
        batch_op.add_column(sa.Column('email', sa.String(length=255), nullable=True))


def downgrade():
    with op.batch_alter_table('visitors', schema=None) as batch_op:
        batch_op.drop_column('email')

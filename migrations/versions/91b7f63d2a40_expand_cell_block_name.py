"""Allow longer cell block names.

Revision ID: 91b7f63d2a40
Revises: 7a2d8e1f4c60
Create Date: 2026-10-05 00:58:00
"""
from alembic import op
import sqlalchemy as sa


revision = '91b7f63d2a40'
down_revision = '7a2d8e1f4c60'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('cell_blocks', schema=None) as batch_op:
        batch_op.alter_column(
            'name',
            existing_type=sa.String(length=10),
            type_=sa.String(length=50),
            existing_nullable=False,
        )


def downgrade():
    with op.batch_alter_table('cell_blocks', schema=None) as batch_op:
        batch_op.alter_column(
            'name',
            existing_type=sa.String(length=50),
            type_=sa.String(length=10),
            existing_nullable=False,
        )

"""Add security classification to cell blocks.

Revision ID: 7a2d8e1f4c60
Revises: 5ce4a7b11f92
Create Date: 2026-10-05 00:55:00
"""
from alembic import op
import sqlalchemy as sa


revision = '7a2d8e1f4c60'
down_revision = '5ce4a7b11f92'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('cell_blocks', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('security_classification', sa.String(length=20), nullable=True)
        )


def downgrade():
    with op.batch_alter_table('cell_blocks', schema=None) as batch_op:
        batch_op.drop_column('security_classification')

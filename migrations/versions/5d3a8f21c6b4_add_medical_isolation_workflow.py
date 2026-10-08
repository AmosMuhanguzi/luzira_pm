"""Add medical-isolation designations and inmate status.

Revision ID: 5d3a8f21c6b4
Revises: 9c71d2e5a4f8
Create Date: 2026-10-08 18:09:00
"""
from alembic import op
import sqlalchemy as sa


revision = '5d3a8f21c6b4'
down_revision = '9c71d2e5a4f8'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('cell_blocks', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'medical_isolation_unit',
                sa.Boolean(),
                server_default=sa.false(),
                nullable=False,
            )
        )

    with op.batch_alter_table('inmates', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'medical_isolation_required',
                sa.Boolean(),
                server_default=sa.false(),
                nullable=False,
            )
        )
        batch_op.add_column(sa.Column('medical_isolation_reason', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('inmates', schema=None) as batch_op:
        batch_op.drop_column('medical_isolation_reason')
        batch_op.drop_column('medical_isolation_required')

    with op.batch_alter_table('cell_blocks', schema=None) as batch_op:
        batch_op.drop_column('medical_isolation_unit')

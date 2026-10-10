"""Add overall description, education and arrested-from to inmates.

Revision ID: b2d6f8a14c31
Revises: a1c5e7d93b20
Create Date: 2026-10-10 20:45:00
"""
from alembic import op
import sqlalchemy as sa


revision = 'b2d6f8a14c31'
down_revision = 'a1c5e7d93b20'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('inmates', schema=None) as batch_op:
        batch_op.add_column(sa.Column('overall_description', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('education', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('arrested_from', sa.String(length=150), nullable=True))


def downgrade():
    with op.batch_alter_table('inmates', schema=None) as batch_op:
        batch_op.drop_column('arrested_from')
        batch_op.drop_column('education')
        batch_op.drop_column('overall_description')

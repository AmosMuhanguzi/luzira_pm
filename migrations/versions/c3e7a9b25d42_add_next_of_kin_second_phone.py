"""Add second next-of-kin phone to inmates.

Revision ID: c3e7a9b25d42
Revises: b2d6f8a14c31
Create Date: 2026-10-10 21:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = 'c3e7a9b25d42'
down_revision = 'b2d6f8a14c31'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('inmates', schema=None) as batch_op:
        batch_op.add_column(sa.Column('next_of_kin_phone_2', sa.String(length=20), nullable=True))


def downgrade():
    with op.batch_alter_table('inmates', schema=None) as batch_op:
        batch_op.drop_column('next_of_kin_phone_2')

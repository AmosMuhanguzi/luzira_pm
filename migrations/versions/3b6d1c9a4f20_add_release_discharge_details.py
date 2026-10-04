"""Add discharge details to admission episodes.

Revision ID: 3b6d1c9a4f20
Revises: 991799592304
Create Date: 2026-10-04 22:50:00
"""
from alembic import op
import sqlalchemy as sa


revision = '3b6d1c9a4f20'
down_revision = '991799592304'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('admission_episodes', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'release_cash_amount',
                sa.Numeric(precision=12, scale=2),
                nullable=False,
                server_default='0',
            )
        )
        batch_op.add_column(sa.Column('release_property_claims', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('released_at', sa.DateTime(), nullable=True))
        batch_op.add_column(
            sa.Column('release_fingerprint_score', sa.Numeric(precision=5, scale=2), nullable=True)
        )


def downgrade():
    with op.batch_alter_table('admission_episodes', schema=None) as batch_op:
        batch_op.drop_column('release_fingerprint_score')
        batch_op.drop_column('released_at')
        batch_op.drop_column('release_property_claims')
        batch_op.drop_column('release_cash_amount')

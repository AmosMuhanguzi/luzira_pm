"""Add structured escape-attempt history for inmates.

Revision ID: 8e4c1a6b93f2
Revises: 7d3a9f4c2b81
Create Date: 2026-10-08 14:10:00
"""
from alembic import op
import sqlalchemy as sa


revision = '8e4c1a6b93f2'
down_revision = '7d3a9f4c2b81'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'escape_attempt_logs',
        sa.Column('event_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('inmate_id', sa.Integer(), nullable=False),
        sa.Column('incident_date', sa.Date(), nullable=False),
        sa.Column('incident_time', sa.Time(), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('outcome', sa.Text(), nullable=True),
        sa.Column('action_taken', sa.Text(), nullable=True),
        sa.Column('reported_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ['inmate_id'],
            ['inmates.inmate_id'],
            name='fk_escape_attempt_logs_inmate_id_inmates',
        ),
        sa.ForeignKeyConstraint(
            ['reported_by'],
            ['user_accounts.user_id'],
            name='fk_escape_attempt_logs_reported_by_user_accounts',
        ),
        sa.PrimaryKeyConstraint('event_id', name='pk_escape_attempt_logs'),
    )
    with op.batch_alter_table('escape_attempt_logs', schema=None) as batch_op:
        batch_op.create_index(
            'ix_escape_attempt_logs_inmate_id',
            ['inmate_id'],
            unique=False,
        )


def downgrade():
    with op.batch_alter_table('escape_attempt_logs', schema=None) as batch_op:
        batch_op.drop_index('ix_escape_attempt_logs_inmate_id')
    op.drop_table('escape_attempt_logs')

"""Add visitor blacklist incident and clearance history.

Revision ID: 3e8b1d6a904f
Revises: 5d3a8f21c6b4
Create Date: 2026-10-08 19:13:00
"""
from alembic import op
import sqlalchemy as sa


revision = '3e8b1d6a904f'
down_revision = '5d3a8f21c6b4'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'visitor_blacklist_events',
        sa.Column('event_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('visitor_id', sa.Integer(), nullable=False),
        sa.Column('action', sa.String(length=10), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('recorded_by', sa.Integer(), nullable=True),
        sa.Column('event_at', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ['visitor_id'],
            ['visitors.visitor_id'],
            name='fk_visitor_blacklist_events_visitor_id_visitors',
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['recorded_by'],
            ['user_accounts.user_id'],
            name='fk_visitor_blacklist_events_recorded_by_user_accounts',
        ),
        sa.PrimaryKeyConstraint('event_id', name='pk_visitor_blacklist_events'),
    )
    op.create_index(
        'ix_visitor_blacklist_events_visitor_id',
        'visitor_blacklist_events',
        ['visitor_id'],
        unique=False,
    )
    op.create_index(
        'ix_visitor_blacklist_events_action',
        'visitor_blacklist_events',
        ['action'],
        unique=False,
    )
    op.create_index(
        'ix_visitor_blacklist_events_event_at',
        'visitor_blacklist_events',
        ['event_at'],
        unique=False,
    )

    op.execute(sa.text(
        """
        INSERT INTO visitor_blacklist_events
            (visitor_id, action, reason, recorded_by, event_at, created_at, updated_at)
        SELECT visitor_id, 'Blocked',
               COALESCE(NULLIF(flag_reason, ''), 'Existing blacklist before incident tracking'),
               NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM visitors
        WHERE is_flagged = 1
        """
    ))


def downgrade():
    op.drop_index(
        'ix_visitor_blacklist_events_event_at',
        table_name='visitor_blacklist_events',
    )
    op.drop_index(
        'ix_visitor_blacklist_events_action',
        table_name='visitor_blacklist_events',
    )
    op.drop_index(
        'ix_visitor_blacklist_events_visitor_id',
        table_name='visitor_blacklist_events',
    )
    op.drop_table('visitor_blacklist_events')

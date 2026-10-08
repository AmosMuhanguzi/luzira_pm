"""Add temporary work-transfer tracking and permanent transfer destination.

Revision ID: 9c71d2e5a4f8
Revises: 8e4c1a6b93f2
Create Date: 2026-10-08 14:40:00
"""
from alembic import op
import sqlalchemy as sa


revision = '9c71d2e5a4f8'
down_revision = '8e4c1a6b93f2'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('admission_episodes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('transfer_to', sa.String(length=100), nullable=True))

    op.create_table(
        'work_transfer_logs',
        sa.Column('transfer_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('inmate_id', sa.Integer(), nullable=False),
        sa.Column('work_location', sa.String(length=200), nullable=False),
        sa.Column('work_description', sa.Text(), nullable=True),
        sa.Column('checked_out_at', sa.DateTime(), nullable=False),
        sa.Column('checkout_fingerprint_score', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('checked_out_by', sa.Integer(), nullable=True),
        sa.Column('checked_in_at', sa.DateTime(), nullable=True),
        sa.Column('checkin_fingerprint_score', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('checked_in_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ['inmate_id'],
            ['inmates.inmate_id'],
            name='fk_work_transfer_logs_inmate_id_inmates',
        ),
        sa.ForeignKeyConstraint(
            ['checked_out_by'],
            ['user_accounts.user_id'],
            name='fk_work_transfer_logs_checked_out_by_user_accounts',
        ),
        sa.ForeignKeyConstraint(
            ['checked_in_by'],
            ['user_accounts.user_id'],
            name='fk_work_transfer_logs_checked_in_by_user_accounts',
        ),
        sa.PrimaryKeyConstraint('transfer_id', name='pk_work_transfer_logs'),
    )
    op.create_index(
        'ix_work_transfer_logs_inmate_id',
        'work_transfer_logs',
        ['inmate_id'],
        unique=False,
    )
    op.create_index(
        'uq_work_transfer_open_inmate',
        'work_transfer_logs',
        ['inmate_id'],
        unique=True,
        sqlite_where=sa.text('checked_in_at IS NULL'),
        postgresql_where=sa.text('checked_in_at IS NULL'),
    )


def downgrade():
    op.drop_index('uq_work_transfer_open_inmate', table_name='work_transfer_logs')
    op.drop_index('ix_work_transfer_logs_inmate_id', table_name='work_transfer_logs')
    op.drop_table('work_transfer_logs')
    with op.batch_alter_table('admission_episodes', schema=None) as batch_op:
        batch_op.drop_column('transfer_to')

"""Add inmate property register.

Revision ID: f1b6d9a24c80
Revises: e7a4c1b92f36
Create Date: 2026-10-14 15:40:00
"""
from alembic import op
import sqlalchemy as sa


revision = 'f1b6d9a24c80'
down_revision = 'e7a4c1b92f36'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'inmate_properties',
        sa.Column('property_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('inmate_id', sa.Integer(), nullable=False),
        sa.Column('episode_id', sa.Integer(), nullable=True),
        sa.Column('item_name', sa.String(length=150), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('recorded_by', sa.Integer(), nullable=True),
        sa.Column('handed_to_name', sa.String(length=150), nullable=True),
        sa.Column('handed_to_relationship', sa.String(length=80), nullable=True),
        sa.Column('handed_over_at', sa.DateTime(), nullable=True),
        sa.Column('handed_over_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['inmate_id'], ['inmates.inmate_id']),
        sa.ForeignKeyConstraint(['episode_id'], ['admission_episodes.episode_id']),
        sa.ForeignKeyConstraint(['recorded_by'], ['user_accounts.user_id']),
        sa.ForeignKeyConstraint(['handed_over_by'], ['user_accounts.user_id']),
        sa.PrimaryKeyConstraint('property_id'),
    )
    with op.batch_alter_table('inmate_properties', schema=None) as batch_op:
        batch_op.create_index('ix_inmate_properties_inmate_id', ['inmate_id'])
        batch_op.create_index('ix_inmate_properties_status', ['status'])


def downgrade():
    with op.batch_alter_table('inmate_properties', schema=None) as batch_op:
        batch_op.drop_index('ix_inmate_properties_status')
        batch_op.drop_index('ix_inmate_properties_inmate_id')
    op.drop_table('inmate_properties')

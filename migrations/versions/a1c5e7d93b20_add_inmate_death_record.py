"""Add death record fields to inmates.

Revision ID: a1c5e7d93b20
Revises: 3e8b1d6a904f
Create Date: 2026-10-10 14:10:00
"""
from alembic import op
import sqlalchemy as sa


revision = 'a1c5e7d93b20'
down_revision = '3e8b1d6a904f'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('inmates', schema=None) as batch_op:
        batch_op.add_column(sa.Column('date_of_death', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('time_of_death', sa.Time(), nullable=True))
        batch_op.add_column(sa.Column('place_of_death', sa.String(length=150), nullable=True))
        batch_op.add_column(sa.Column('cause_of_death', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('death_recorded_by', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('death_recorded_at', sa.DateTime(), nullable=True))
        batch_op.create_index(batch_op.f('ix_inmates_date_of_death'), ['date_of_death'], unique=False)
        batch_op.create_foreign_key(
            'fk_inmates_death_recorded_by_user_accounts',
            'user_accounts',
            ['death_recorded_by'],
            ['user_id'],
        )


def downgrade():
    with op.batch_alter_table('inmates', schema=None) as batch_op:
        batch_op.drop_constraint('fk_inmates_death_recorded_by_user_accounts', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_inmates_date_of_death'))
        batch_op.drop_column('death_recorded_at')
        batch_op.drop_column('death_recorded_by')
        batch_op.drop_column('cause_of_death')
        batch_op.drop_column('place_of_death')
        batch_op.drop_column('time_of_death')
        batch_op.drop_column('date_of_death')

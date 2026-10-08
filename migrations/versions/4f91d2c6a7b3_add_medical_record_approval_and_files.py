"""Add attachments and approval workflow to medical records.

Revision ID: 4f91d2c6a7b3
Revises: 91b7f63d2a40
Create Date: 2026-10-08 11:45:00
"""
from alembic import op
import sqlalchemy as sa


revision = '4f91d2c6a7b3'
down_revision = '91b7f63d2a40'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('medical_records', schema=None) as batch_op:
        batch_op.add_column(sa.Column('attachment_path', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('attachment_name', sa.String(length=255), nullable=True))
        batch_op.add_column(
            sa.Column(
                'approval_status',
                sa.String(length=20),
                nullable=False,
                server_default='Approved',
            )
        )
        batch_op.add_column(sa.Column('reviewed_by', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('reviewed_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('review_notes', sa.Text(), nullable=True))
        batch_op.create_index(
            'ix_medical_records_approval_status',
            ['approval_status'],
            unique=False,
        )
        batch_op.create_foreign_key(
            'fk_medical_records_reviewed_by_user_accounts',
            'user_accounts',
            ['reviewed_by'],
            ['user_id'],
        )

    bind = op.get_bind()
    roles = sa.table(
        'roles',
        sa.column('role_name', sa.String(length=50)),
        sa.column('description', sa.Text()),
    )
    role_exists = bind.execute(
        sa.select(roles.c.role_name).where(roles.c.role_name == 'Medical Officer')
    ).first()
    if not role_exists:
        bind.execute(
            roles.insert().values(
                role_name='Medical Officer',
                description='View inmate records and submit medical records for approval',
            )
        )


def downgrade():
    bind = op.get_bind()
    role = bind.execute(
        sa.text("SELECT role_id FROM roles WHERE role_name = 'Medical Officer'")
    ).first()
    if role:
        assigned_users = bind.execute(
            sa.text('SELECT 1 FROM user_accounts WHERE role_id = :role_id LIMIT 1'),
            {'role_id': role[0]},
        ).first()
        if not assigned_users:
            bind.execute(
                sa.text('DELETE FROM roles WHERE role_id = :role_id'),
                {'role_id': role[0]},
            )

    with op.batch_alter_table('medical_records', schema=None) as batch_op:
        batch_op.drop_constraint(
            'fk_medical_records_reviewed_by_user_accounts',
            type_='foreignkey',
        )
        batch_op.drop_index('ix_medical_records_approval_status')
        batch_op.drop_column('review_notes')
        batch_op.drop_column('reviewed_at')
        batch_op.drop_column('reviewed_by')
        batch_op.drop_column('approval_status')
        batch_op.drop_column('attachment_name')
        batch_op.drop_column('attachment_path')

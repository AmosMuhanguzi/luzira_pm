"""Add multiple file attachments to medical records.

Revision ID: 6a2c9e41b7d5
Revises: 4f91d2c6a7b3
Create Date: 2026-10-08 12:36:00
"""
from alembic import op
import sqlalchemy as sa


revision = '6a2c9e41b7d5'
down_revision = '4f91d2c6a7b3'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'medical_record_attachments',
        sa.Column('attachment_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('medical_record_id', sa.Integer(), nullable=False),
        sa.Column('file_path', sa.String(length=255), nullable=False),
        sa.Column('original_name', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ['medical_record_id'],
            ['medical_records.record_id'],
            name='fk_medical_record_attachments_medical_record_id_medical_records',
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('attachment_id', name='pk_medical_record_attachments'),
    )
    with op.batch_alter_table('medical_record_attachments', schema=None) as batch_op:
        batch_op.create_index(
            'ix_medical_record_attachments_medical_record_id',
            ['medical_record_id'],
            unique=False,
        )


def downgrade():
    with op.batch_alter_table('medical_record_attachments', schema=None) as batch_op:
        batch_op.drop_index('ix_medical_record_attachments_medical_record_id')
    op.drop_table('medical_record_attachments')

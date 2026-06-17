"""add document_expiry table

Revision ID: darchiva_doc_expiry
Revises: fa71c2c795a9
Create Date: 2026-06-17 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'darchiva_doc_expiry'
down_revision: Union[str, None] = 'fa71c2c795a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
	op.create_table(
		'document_expiry',
		sa.Column('id', sa.String(36), nullable=False),
		sa.Column('document_id', sa.String(36), nullable=False),
		sa.Column('expires_at', sa.DateTime(), nullable=False),
		sa.Column('reminder_days', sa.String(255), nullable=False, server_default='[30,7,1]'),
		sa.Column('notified_milestones', sa.String(255), nullable=False, server_default='[]'),
		sa.Column('created_by_id', sa.String(36), nullable=True),
		sa.Column('tenant_id', sa.String(36), nullable=False),
		sa.Column('created_at', sa.DateTime(), nullable=False),
		sa.Column('updated_at', sa.DateTime(), nullable=False),
		sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
		sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
		sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
		sa.PrimaryKeyConstraint('id'),
		sa.UniqueConstraint('document_id', name='uq_document_expiry_document_id'),
	)
	op.create_index(
		'ix_document_expiry_tenant_expires',
		'document_expiry',
		['tenant_id', 'expires_at'],
	)
	op.create_index(
		'ix_document_expiry_expires_at',
		'document_expiry',
		['expires_at'],
	)


def downgrade() -> None:
	op.drop_index('ix_document_expiry_expires_at', table_name='document_expiry')
	op.drop_index('ix_document_expiry_tenant_expires', table_name='document_expiry')
	op.drop_table('document_expiry')

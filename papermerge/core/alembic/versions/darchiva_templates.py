"""add document_templates table

Revision ID: a1b2c3d4e5f6
Revises: fa71c2c795a9
Create Date: 2026-06-17 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'fa71c2c795a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
	op.create_table(
		'document_templates',
		sa.Column('id', sa.String(36), primary_key=True, nullable=False),
		sa.Column('name', sa.String(255), nullable=False),
		sa.Column('description', sa.Text(), nullable=False, server_default=''),
		sa.Column('category', sa.String(100), nullable=False, server_default='general'),
		sa.Column(
			'template_file_id',
			sa.String(36),
			sa.ForeignKey('documents.node_id', ondelete='SET NULL', name='fk_doc_templates_file_id'),
			nullable=True,
		),
		sa.Column('field_definitions', sa.Text(), nullable=False, server_default='[]'),
		sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
		sa.Column(
			'created_by_id',
			sa.String(36),
			sa.ForeignKey('users.id', ondelete='RESTRICT', name='fk_doc_templates_created_by'),
			nullable=False,
		),
		sa.Column('tenant_id', sa.String(36), nullable=False),
		sa.Column(
			'created_at',
			sa.TIMESTAMP(timezone=True),
			nullable=False,
			server_default=sa.text('now()'),
		),
		sa.Column(
			'updated_at',
			sa.TIMESTAMP(timezone=True),
			nullable=False,
			server_default=sa.text('now()'),
		),
		sa.Column('use_count', sa.Integer(), nullable=False, server_default='0'),
	)

	op.create_index('ix_document_templates_tenant_id', 'document_templates', ['tenant_id'])
	op.create_index('ix_document_templates_category', 'document_templates', ['category'])
	op.create_index('ix_document_templates_created_by_id', 'document_templates', ['created_by_id'])


def downgrade() -> None:
	op.drop_index('ix_document_templates_created_by_id', table_name='document_templates')
	op.drop_index('ix_document_templates_category', table_name='document_templates')
	op.drop_index('ix_document_templates_tenant_id', table_name='document_templates')
	op.drop_table('document_templates')

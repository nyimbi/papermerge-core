"""darchiva: document relationship linking

Revision ID: a1b2c3d4e5f6
Revises: fa71c2c795a9
Create Date: 2026-06-17 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'fa71c2c795a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
	op.create_table(
		'document_relationships',
		sa.Column('id', sa.UUID(), nullable=False),
		sa.Column('source_document_id', sa.UUID(), nullable=False),
		sa.Column('target_document_id', sa.UUID(), nullable=False),
		sa.Column('relationship_type', sa.String(64), nullable=False),
		sa.Column('note', sa.Text(), nullable=True),
		sa.Column('tenant_id', sa.String(), nullable=True),
		sa.Column('created_by_id', sa.UUID(), nullable=False),
		sa.Column(
			'created_at',
			postgresql.TIMESTAMP(timezone=True),
			nullable=False,
			server_default=sa.text('now()'),
		),
		sa.PrimaryKeyConstraint('id'),
		sa.ForeignKeyConstraint(
			['source_document_id'],
			['documents.node_id'],
			ondelete='CASCADE',
		),
		sa.ForeignKeyConstraint(
			['target_document_id'],
			['documents.node_id'],
			ondelete='CASCADE',
		),
		sa.ForeignKeyConstraint(
			['created_by_id'],
			['users.id'],
			ondelete='RESTRICT',
			deferrable=True,
			initially='DEFERRED',
		),
		sa.UniqueConstraint(
			'source_document_id',
			'target_document_id',
			'relationship_type',
			name='uq_doc_relationship_src_tgt_type',
		),
	)

	op.create_index(
		'ix_doc_relationships_source_id',
		'document_relationships',
		['source_document_id'],
	)
	op.create_index(
		'ix_doc_relationships_target_id',
		'document_relationships',
		['target_document_id'],
	)
	op.create_index(
		'ix_doc_relationships_created_by',
		'document_relationships',
		['created_by_id'],
	)


def downgrade() -> None:
	op.drop_index('ix_doc_relationships_created_by', table_name='document_relationships')
	op.drop_index('ix_doc_relationships_target_id', table_name='document_relationships')
	op.drop_index('ix_doc_relationships_source_id', table_name='document_relationships')
	op.drop_table('document_relationships')

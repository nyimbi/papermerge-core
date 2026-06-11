# (c) Copyright Datacraft, 2026
"""Add scanning_batch_documents table to link scanned documents to batches.

Revision ID: d4rc_0014
Revises: d4rc_0013
Create Date: 2026-01-23

This table tracks which documents have been scanned as part of which batch,
enabling persistence of scanned pages across page refreshes in the UI.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'd4rc_0014'
down_revision: Union[str, None] = 'd4rc_0013'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
	# Create batch document status enum
	op.execute("""
		CREATE TYPE batchdocumentstatus AS ENUM ('pending', 'accepted', 'rejected', 'rescanning')
	""")

	# scanning_batch_documents table - links scanned documents to batches
	op.create_table(
		'scanning_batch_documents',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('batch_id', postgresql.UUID(as_uuid=True),
			sa.ForeignKey('scanning_batches.id', ondelete='CASCADE'), nullable=False, index=True),
		sa.Column('document_id', postgresql.UUID(as_uuid=True),
			sa.ForeignKey('nodes.id', ondelete='CASCADE'), nullable=False, index=True),
		sa.Column('page_number', sa.Integer, nullable=False),
		sa.Column('scan_job_id', sa.String(36)),
		sa.Column('quality_score', sa.Integer, server_default='90'),
		sa.Column('status', postgresql.ENUM(
			'pending', 'accepted', 'rejected', 'rescanning',
			name='batchdocumentstatus', create_type=False), server_default='accepted'),
		sa.Column('needs_review', sa.Boolean, server_default='false'),
		sa.Column('has_issues', sa.Boolean, server_default='false'),
		sa.Column('issue_details', postgresql.JSONB),
		sa.Column('scanned_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
	)
	op.create_index('idx_batch_documents_batch', 'scanning_batch_documents', ['batch_id', 'page_number'])


def downgrade() -> None:
	op.drop_table('scanning_batch_documents')
	op.execute('DROP TYPE IF EXISTS batchdocumentstatus')

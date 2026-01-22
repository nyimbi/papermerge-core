# (c) Copyright Datacraft, 2026
"""Add ingestion batch, template, and validation models.

Revision ID: d4rc_0010
Revises: d4rc_0009
Create Date: 2026-01-22
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'd4rc_0010'
down_revision: Union[str, None] = 'd4rc_0009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
	# Create ingestion_templates table
	op.create_table(
		'ingestion_templates',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True),
		sa.Column('name', sa.String(255), nullable=False),
		sa.Column('description', sa.Text, nullable=True),
		sa.Column('target_folder_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('nodes.id', ondelete='SET NULL'), nullable=True),
		sa.Column('document_type_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('document_types.id', ondelete='SET NULL'), nullable=True),
		sa.Column('apply_ocr', sa.Boolean, default=True, nullable=False),
		sa.Column('auto_classify', sa.Boolean, default=False, nullable=False),
		sa.Column('duplicate_check', sa.Boolean, default=True, nullable=False),
		sa.Column('validation_rules', postgresql.JSONB, nullable=True),
		sa.Column('is_active', sa.Boolean, default=True, nullable=False),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
	)

	# Create ingestion_batches table
	op.create_table(
		'ingestion_batches',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True),
		sa.Column('name', sa.String(255), nullable=True),
		sa.Column('template_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('ingestion_templates.id', ondelete='SET NULL'), nullable=True),
		sa.Column('total_files', sa.Integer, default=0, nullable=False),
		sa.Column('processed_files', sa.Integer, default=0, nullable=False),
		sa.Column('failed_files', sa.Integer, default=0, nullable=False),
		sa.Column('status', sa.String(50), default='pending', nullable=False),
		sa.Column('started_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
		sa.Column('completed_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
		sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
	)
	op.create_index('idx_ingestion_batches_tenant', 'ingestion_batches', ['tenant_id', 'status'])

	# Create ingestion_validation_rules table
	op.create_table(
		'ingestion_validation_rules',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True),
		sa.Column('name', sa.String(255), nullable=False),
		sa.Column('rule_type', sa.String(50), nullable=False),
		sa.Column('config', postgresql.JSONB, nullable=False),
		sa.Column('is_active', sa.Boolean, default=True, nullable=False),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
	)

	# Add columns to ingestion_jobs
	op.add_column('ingestion_jobs', sa.Column('batch_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('ingestion_batches.id', ondelete='SET NULL'), nullable=True))
	op.add_column('ingestion_jobs', sa.Column('retry_count', sa.Integer, default=0, server_default='0', nullable=False))
	op.create_index('idx_ingestion_jobs_batch', 'ingestion_jobs', ['batch_id'])


def downgrade() -> None:
	op.drop_index('idx_ingestion_jobs_batch', 'ingestion_jobs')
	op.drop_column('ingestion_jobs', 'retry_count')
	op.drop_column('ingestion_jobs', 'batch_id')
	op.drop_table('ingestion_validation_rules')
	op.drop_index('idx_ingestion_batches_tenant', 'ingestion_batches')
	op.drop_table('ingestion_batches')
	op.drop_table('ingestion_templates')

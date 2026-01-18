# (c) Copyright Datacraft, 2026
"""Storage lifecycle, pgvector, and scanning project management tables.

Revision ID: d4rc_0002
Revises: d4rc_0001
Create Date: 2026-01-18

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'd4rc_0002'
down_revision: Union[str, None] = 'd4rc_0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
	# Enable pgvector extension
	op.execute('CREATE EXTENSION IF NOT EXISTS vector')
	op.execute('CREATE EXTENSION IF NOT EXISTS pg_trgm')

	# Storage Tiers
	op.create_table(
		'storage_tiers',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
		sa.Column('name', sa.String(50), nullable=False),
		sa.Column('tier_type', sa.String(20), nullable=False),  # hot, cold, archive
		sa.Column('storage_class', sa.String(50)),  # STANDARD, GLACIER, etc.
		sa.Column('provider', sa.String(50), nullable=False),  # linode, s3, r2
		sa.Column('bucket_name', sa.String(255)),
		sa.Column('endpoint_url', sa.String(500)),
		sa.Column('region', sa.String(50)),
		sa.Column('cost_per_gb_month', sa.Numeric(10, 4)),
		sa.Column('retrieval_time_hours', sa.Integer),
		sa.Column('is_default', sa.Boolean, server_default='false'),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.UniqueConstraint('tenant_id', 'name', name='uq_storage_tier_name'),
	)
	op.create_index('idx_storage_tiers_tenant', 'storage_tiers', ['tenant_id'])

	# Storage Policies (lifecycle rules)
	op.create_table(
		'storage_policies',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
		sa.Column('name', sa.String(255), nullable=False),
		sa.Column('description', sa.Text),
		sa.Column('document_type_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('document_types.id', ondelete='SET NULL')),
		sa.Column('from_tier_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('storage_tiers.id', ondelete='CASCADE'), nullable=False),
		sa.Column('to_tier_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('storage_tiers.id', ondelete='CASCADE'), nullable=False),
		sa.Column('transition_after_days', sa.Integer, nullable=False),
		sa.Column('delete_after_days', sa.Integer),
		sa.Column('condition_expression', sa.Text),  # Additional conditions (tags, custom fields)
		sa.Column('is_active', sa.Boolean, server_default='true'),
		sa.Column('priority', sa.Integer, server_default='100'),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL')),
	)
	op.create_index('idx_storage_policies_tenant', 'storage_policies', ['tenant_id', 'is_active'])

	# Document storage location tracking
	op.create_table(
		'document_storage_locations',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('document_version_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('document_versions.id', ondelete='CASCADE'), nullable=False),
		sa.Column('tier_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('storage_tiers.id', ondelete='RESTRICT'), nullable=False),
		sa.Column('object_key', sa.String(1000), nullable=False),
		sa.Column('size_bytes', sa.BigInteger, nullable=False),
		sa.Column('checksum_sha256', sa.String(64)),
		sa.Column('uploaded_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.Column('last_accessed_at', postgresql.TIMESTAMP(timezone=True)),
		sa.Column('access_count', sa.Integer, server_default='0'),
		sa.Column('transitioned_at', postgresql.TIMESTAMP(timezone=True)),
		sa.Column('previous_tier_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('storage_tiers.id', ondelete='SET NULL')),
		sa.UniqueConstraint('document_version_id', 'tier_id', name='uq_docver_tier'),
	)
	op.create_index('idx_doc_storage_tier', 'document_storage_locations', ['tier_id'])
	op.create_index('idx_doc_storage_access', 'document_storage_locations', ['last_accessed_at'])

	# Document embeddings for semantic search
	op.create_table(
		'document_embeddings',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('document_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('nodes.id', ondelete='CASCADE'), nullable=False),
		sa.Column('document_version_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('document_versions.id', ondelete='CASCADE')),
		sa.Column('page_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('pages.id', ondelete='CASCADE')),
		sa.Column('chunk_index', sa.Integer, server_default='0'),
		sa.Column('chunk_text', sa.Text),
		sa.Column('embedding', postgresql.ARRAY(sa.Float), comment='Vector embedding array'),
		sa.Column('model_name', sa.String(100), nullable=False),
		sa.Column('model_version', sa.String(50)),
		sa.Column('embedding_dimension', sa.Integer, nullable=False),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
	)
	op.create_index('idx_doc_embeddings_document', 'document_embeddings', ['document_id'])
	op.create_index('idx_doc_embeddings_page', 'document_embeddings', ['page_id'])
	# Note: IVFFlat index for vector similarity will be created after data is loaded
	# op.execute('CREATE INDEX ON document_embeddings USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)')

	# Scanning Projects (enhanced)
	op.create_table(
		'scanning_projects',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
		sa.Column('code', sa.String(50), nullable=False),
		sa.Column('name', sa.String(255), nullable=False),
		sa.Column('description', sa.Text),
		sa.Column('status', sa.String(30), server_default='planning'),
		sa.Column('priority', sa.String(20), server_default='normal'),
		sa.Column('project_type', sa.String(50)),  # archival, operational, hybrid
		sa.Column('client_name', sa.String(255)),
		sa.Column('client_reference', sa.String(100)),
		sa.Column('start_date', sa.Date),
		sa.Column('target_end_date', sa.Date),
		sa.Column('actual_end_date', sa.Date),
		sa.Column('estimated_pages', sa.Integer),
		sa.Column('estimated_documents', sa.Integer),
		sa.Column('daily_page_target', sa.Integer),
		sa.Column('target_dpi', sa.Integer, server_default='300'),
		sa.Column('color_mode', sa.String(20), server_default='color'),
		sa.Column('duplex_mode', sa.String(20), server_default='duplex'),
		sa.Column('file_format', sa.String(20), server_default='pdf'),
		sa.Column('ocr_enabled', sa.Boolean, server_default='true'),
		sa.Column('quality_sampling_rate', sa.Float, server_default='0.1'),
		sa.Column('destination_folder_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('nodes.id', ondelete='SET NULL')),
		sa.Column('metadata', postgresql.JSONB),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.Column('deleted_at', postgresql.TIMESTAMP(timezone=True)),
		sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='RESTRICT', deferrable=True, initially='DEFERRED'), nullable=False),
		sa.Column('updated_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='RESTRICT', deferrable=True, initially='DEFERRED'), nullable=False),
		sa.UniqueConstraint('tenant_id', 'code', name='uq_scanning_project_code'),
	)
	op.create_index('idx_scanning_projects_tenant', 'scanning_projects', ['tenant_id'])
	op.create_index('idx_scanning_projects_status', 'scanning_projects', ['status'])

	# Project Phases
	op.create_table(
		'project_phases',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('project_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('scanning_projects.id', ondelete='CASCADE'), nullable=False),
		sa.Column('name', sa.String(100), nullable=False),
		sa.Column('description', sa.Text),
		sa.Column('sequence_order', sa.Integer, nullable=False),
		sa.Column('status', sa.String(30), server_default='pending'),
		sa.Column('start_date', sa.Date),
		sa.Column('target_end_date', sa.Date),
		sa.Column('actual_end_date', sa.Date),
		sa.Column('estimated_pages', sa.Integer),
		sa.Column('actual_pages', sa.Integer, server_default='0'),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.UniqueConstraint('project_id', 'sequence_order', name='uq_phase_sequence'),
	)
	op.create_index('idx_project_phases_project', 'project_phases', ['project_id'])

	# Source Locations (physical origins of documents)
	op.create_table(
		'source_locations',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
		sa.Column('name', sa.String(255), nullable=False),
		sa.Column('location_type', sa.String(50), nullable=False),  # warehouse, office, archive_room, filing_cabinet
		sa.Column('code', sa.String(50)),
		sa.Column('address', sa.Text),
		sa.Column('building', sa.String(100)),
		sa.Column('floor', sa.String(20)),
		sa.Column('room', sa.String(50)),
		sa.Column('shelf', sa.String(50)),
		sa.Column('box', sa.String(50)),
		sa.Column('parent_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('source_locations.id', ondelete='SET NULL')),
		sa.Column('metadata', postgresql.JSONB),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
	)
	op.create_index('idx_source_locations_tenant', 'source_locations', ['tenant_id'])
	op.create_index('idx_source_locations_parent', 'source_locations', ['parent_id'])

	# Scanning Batches
	op.create_table(
		'scan_batches',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('project_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('scanning_projects.id', ondelete='CASCADE'), nullable=False),
		sa.Column('phase_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('project_phases.id', ondelete='SET NULL')),
		sa.Column('batch_number', sa.String(50), nullable=False),
		sa.Column('source_location_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('source_locations.id', ondelete='SET NULL')),
		sa.Column('box_label', sa.String(100)),
		sa.Column('folder_label', sa.String(100)),
		sa.Column('status', sa.String(30), server_default='pending'),
		sa.Column('priority', sa.Integer, server_default='0'),
		sa.Column('estimated_pages', sa.Integer),
		sa.Column('actual_pages', sa.Integer, server_default='0'),
		sa.Column('documents_count', sa.Integer, server_default='0'),
		sa.Column('assigned_operator_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL')),
		sa.Column('assigned_scanner_id', postgresql.UUID(as_uuid=True)),  # FK to scanners table
		sa.Column('started_at', postgresql.TIMESTAMP(timezone=True)),
		sa.Column('completed_at', postgresql.TIMESTAMP(timezone=True)),
		sa.Column('notes', sa.Text),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL')),
		sa.UniqueConstraint('project_id', 'batch_number', name='uq_batch_number'),
	)
	op.create_index('idx_scan_batches_project', 'scan_batches', ['project_id'])
	op.create_index('idx_scan_batches_status', 'scan_batches', ['status'])
	op.create_index('idx_scan_batches_operator', 'scan_batches', ['assigned_operator_id'])

	# Document Provenance
	op.create_table(
		'document_provenance',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('document_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('nodes.id', ondelete='CASCADE'), nullable=False),
		sa.Column('batch_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('scan_batches.id', ondelete='SET NULL')),
		sa.Column('source_location_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('source_locations.id', ondelete='SET NULL')),
		sa.Column('original_file_hash', sa.String(64)),  # SHA-256 of original scan
		sa.Column('original_filename', sa.String(500)),
		sa.Column('original_format', sa.String(50)),
		sa.Column('source_location_detail', sa.Text),  # Additional location info
		sa.Column('physical_condition', sa.String(50)),  # good, fair, poor, damaged
		sa.Column('scan_date', postgresql.TIMESTAMP(timezone=True)),
		sa.Column('scanned_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL')),
		sa.Column('scanner_model', sa.String(100)),
		sa.Column('scan_settings', postgresql.JSONB),  # DPI, color mode, etc.
		sa.Column('qr_code', sa.String(255)),  # Data Matrix / QR code value
		sa.Column('barcode', sa.String(255)),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.UniqueConstraint('document_id', name='uq_document_provenance'),
	)
	op.create_index('idx_doc_provenance_batch', 'document_provenance', ['batch_id'])
	op.create_index('idx_doc_provenance_qr', 'document_provenance', ['qr_code'])

	# Provenance Events (audit trail)
	op.create_table(
		'provenance_events',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('document_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('nodes.id', ondelete='CASCADE'), nullable=False),
		sa.Column('event_type', sa.String(50), nullable=False),  # scanned, ocr_processed, classified, verified, etc.
		sa.Column('actor_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL')),
		sa.Column('actor_type', sa.String(20), server_default='user'),  # user, system, api
		sa.Column('details', postgresql.JSONB),
		sa.Column('ip_address', sa.String(45)),
		sa.Column('user_agent', sa.String(500)),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
	)
	op.create_index('idx_provenance_events_document', 'provenance_events', ['document_id'])
	op.create_index('idx_provenance_events_type', 'provenance_events', ['event_type'])
	op.create_index('idx_provenance_events_created', 'provenance_events', ['created_at'])

	# Scanning Sessions
	op.create_table(
		'scanning_sessions',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('project_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('scanning_projects.id', ondelete='CASCADE'), nullable=False),
		sa.Column('batch_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('scan_batches.id', ondelete='SET NULL')),
		sa.Column('operator_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=False),
		sa.Column('scanner_id', postgresql.UUID(as_uuid=True)),  # FK to scanners table
		sa.Column('workstation_id', sa.String(100)),
		sa.Column('started_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.Column('ended_at', postgresql.TIMESTAMP(timezone=True)),
		sa.Column('documents_scanned', sa.Integer, server_default='0'),
		sa.Column('pages_scanned', sa.Integer, server_default='0'),
		sa.Column('errors_count', sa.Integer, server_default='0'),
		sa.Column('rescans_count', sa.Integer, server_default='0'),
		sa.Column('break_time_minutes', sa.Integer, server_default='0'),
		sa.Column('notes', sa.Text),
	)
	op.create_index('idx_scanning_sessions_project', 'scanning_sessions', ['project_id'])
	op.create_index('idx_scanning_sessions_operator', 'scanning_sessions', ['operator_id'])
	op.create_index('idx_scanning_sessions_date', 'scanning_sessions', ['started_at'])

	# Progress Snapshots (for reporting)
	op.create_table(
		'progress_snapshots',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('project_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('scanning_projects.id', ondelete='CASCADE'), nullable=False),
		sa.Column('snapshot_time', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.Column('total_pages_scanned', sa.Integer, server_default='0'),
		sa.Column('total_documents_scanned', sa.Integer, server_default='0'),
		sa.Column('pages_per_hour', sa.Float),
		sa.Column('documents_per_hour', sa.Float),
		sa.Column('operators_active', sa.Integer),
		sa.Column('scanners_active', sa.Integer),
		sa.Column('error_rate', sa.Float),
		sa.Column('quality_score', sa.Float),
		sa.Column('estimated_completion_date', sa.Date),
		sa.Column('notes', sa.Text),
	)
	op.create_index('idx_progress_snapshots_project', 'progress_snapshots', ['project_id', 'snapshot_time'])

	# Daily Project Metrics
	op.create_table(
		'daily_project_metrics',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('project_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('scanning_projects.id', ondelete='CASCADE'), nullable=False),
		sa.Column('metric_date', sa.Date, nullable=False),
		sa.Column('pages_scanned', sa.Integer, server_default='0'),
		sa.Column('documents_scanned', sa.Integer, server_default='0'),
		sa.Column('pages_verified', sa.Integer, server_default='0'),
		sa.Column('pages_rejected', sa.Integer, server_default='0'),
		sa.Column('operator_count', sa.Integer),
		sa.Column('scanner_count', sa.Integer),
		sa.Column('active_hours', sa.Float),
		sa.Column('avg_pages_per_hour', sa.Float),
		sa.Column('quality_score', sa.Float),
		sa.Column('ocr_accuracy', sa.Float),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.UniqueConstraint('project_id', 'metric_date', name='uq_daily_project_metrics'),
	)
	op.create_index('idx_daily_metrics_project', 'daily_project_metrics', ['project_id', 'metric_date'])

	# Operator Daily Metrics
	op.create_table(
		'operator_daily_metrics',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('project_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('scanning_projects.id', ondelete='CASCADE'), nullable=False),
		sa.Column('operator_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
		sa.Column('metric_date', sa.Date, nullable=False),
		sa.Column('pages_scanned', sa.Integer, server_default='0'),
		sa.Column('documents_scanned', sa.Integer, server_default='0'),
		sa.Column('active_hours', sa.Float),
		sa.Column('avg_pages_per_hour', sa.Float),
		sa.Column('quality_score', sa.Float),
		sa.Column('error_count', sa.Integer, server_default='0'),
		sa.Column('rescan_count', sa.Integer, server_default='0'),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.UniqueConstraint('project_id', 'operator_id', 'metric_date', name='uq_operator_daily_metrics'),
	)
	op.create_index('idx_operator_metrics_project', 'operator_daily_metrics', ['project_id', 'metric_date'])
	op.create_index('idx_operator_metrics_operator', 'operator_daily_metrics', ['operator_id', 'metric_date'])

	# Project Issues
	op.create_table(
		'project_issues',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('project_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('scanning_projects.id', ondelete='CASCADE'), nullable=False),
		sa.Column('batch_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('scan_batches.id', ondelete='SET NULL')),
		sa.Column('document_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('nodes.id', ondelete='SET NULL')),
		sa.Column('title', sa.String(255), nullable=False),
		sa.Column('description', sa.Text),
		sa.Column('issue_type', sa.String(50), nullable=False),  # quality, equipment, process, staffing
		sa.Column('severity', sa.String(20), server_default='medium'),  # low, medium, high, critical
		sa.Column('status', sa.String(30), server_default='open'),  # open, in_progress, resolved, closed
		sa.Column('reported_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL')),
		sa.Column('assigned_to', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL')),
		sa.Column('resolution', sa.Text),
		sa.Column('resolved_at', postgresql.TIMESTAMP(timezone=True)),
		sa.Column('resolved_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL')),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
	)
	op.create_index('idx_project_issues_project', 'project_issues', ['project_id'])
	op.create_index('idx_project_issues_status', 'project_issues', ['status'])

	# Quality Control Samples
	op.create_table(
		'quality_control_samples',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('project_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('scanning_projects.id', ondelete='CASCADE'), nullable=False),
		sa.Column('batch_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('scan_batches.id', ondelete='SET NULL')),
		sa.Column('document_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('nodes.id', ondelete='CASCADE'), nullable=False),
		sa.Column('sample_type', sa.String(50), server_default='random'),  # random, targeted, recheck
		sa.Column('status', sa.String(30), server_default='pending'),  # pending, passed, failed, needs_rescan
		sa.Column('reviewed_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL')),
		sa.Column('reviewed_at', postgresql.TIMESTAMP(timezone=True)),
		sa.Column('image_quality_score', sa.Float),
		sa.Column('ocr_accuracy_score', sa.Float),
		sa.Column('metadata_accuracy_score', sa.Float),
		sa.Column('overall_score', sa.Float),
		sa.Column('issues_found', postgresql.ARRAY(sa.String)),
		sa.Column('notes', sa.Text),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
	)
	op.create_index('idx_qc_samples_project', 'quality_control_samples', ['project_id'])
	op.create_index('idx_qc_samples_status', 'quality_control_samples', ['status'])

	# Scanning Resources (scanners, operators, workstations)
	op.create_table(
		'scanning_resources',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
		sa.Column('resource_type', sa.String(30), nullable=False),  # scanner, operator, workstation
		sa.Column('name', sa.String(255), nullable=False),
		sa.Column('code', sa.String(50)),
		sa.Column('status', sa.String(20), server_default='available'),  # available, in_use, maintenance, offline
		sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL')),  # For operators
		sa.Column('model', sa.String(100)),  # For scanners
		sa.Column('serial_number', sa.String(100)),
		sa.Column('max_dpi', sa.Integer),
		sa.Column('supports_duplex', sa.Boolean),
		sa.Column('supports_color', sa.Boolean),
		sa.Column('capabilities', postgresql.JSONB),
		sa.Column('location', sa.String(255)),
		sa.Column('last_maintenance_at', postgresql.TIMESTAMP(timezone=True)),
		sa.Column('next_maintenance_at', postgresql.TIMESTAMP(timezone=True)),
		sa.Column('current_project_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('scanning_projects.id', ondelete='SET NULL')),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
	)
	op.create_index('idx_scanning_resources_tenant', 'scanning_resources', ['tenant_id', 'resource_type'])
	op.create_index('idx_scanning_resources_status', 'scanning_resources', ['status'])


def downgrade() -> None:
	op.drop_table('scanning_resources')
	op.drop_table('quality_control_samples')
	op.drop_table('project_issues')
	op.drop_table('operator_daily_metrics')
	op.drop_table('daily_project_metrics')
	op.drop_table('progress_snapshots')
	op.drop_table('scanning_sessions')
	op.drop_table('provenance_events')
	op.drop_table('document_provenance')
	op.drop_table('scan_batches')
	op.drop_table('source_locations')
	op.drop_table('project_phases')
	op.drop_table('scanning_projects')
	op.drop_table('document_embeddings')
	op.drop_table('document_storage_locations')
	op.drop_table('storage_policies')
	op.drop_table('storage_tiers')
	op.execute('DROP EXTENSION IF EXISTS pg_trgm')
	op.execute('DROP EXTENSION IF EXISTS vector')

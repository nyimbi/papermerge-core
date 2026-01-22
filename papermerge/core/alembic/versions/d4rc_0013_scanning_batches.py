# (c) Copyright Datacraft, 2026
"""Add scanning batches, milestones, and QC samples tables.

Revision ID: d4rc_0013
Revises: d4rc_0012
Create Date: 2026-01-23

These tables support the scanning project workflow:
- scanning_batches: Physical batches of documents to be scanned
- scanning_milestones: Project milestones for tracking progress
- qc_samples: Quality control samples for batch verification
- project_phases: Project phases for tracking scanning stages
- progress_snapshots: Point-in-time progress snapshots
- daily_project_metrics: Daily aggregated metrics
- operator_daily_metrics: Per-operator daily metrics
- project_issues: Issue tracking for projects
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'd4rc_0013'
down_revision: Union[str, None] = 'd4rc_0012'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
	# Create enum types with lowercase values (matching Python str Enum values)
	op.execute("""
		CREATE TYPE scanningbatchstatus AS ENUM (
			'pending', 'unbundling', 'scanning', 'repacking', 'returned',
			'ocr_processing', 'qc_pending', 'qc_passed', 'qc_failed', 'completed'
		)
	""")

	op.execute("""
		CREATE TYPE scanningbatchtype AS ENUM ('box', 'folder', 'volume')
	""")

	op.execute("""
		CREATE TYPE milestonestatus AS ENUM ('pending', 'in_progress', 'completed', 'overdue')
	""")

	op.execute("""
		CREATE TYPE qcreviewstatus AS ENUM ('pending', 'passed', 'failed', 'needs_rescan')
	""")

	op.execute("""
		CREATE TYPE issueseverity AS ENUM ('minor', 'major', 'critical')
	""")

	op.execute("""
		CREATE TYPE issuetype AS ENUM (
			'skew', 'blur', 'cutoff', 'dark', 'light', 'missing', 'duplicate', 'other'
		)
	""")

	op.execute("""
		CREATE TYPE projectissuestatus AS ENUM ('open', 'in_progress', 'resolved', 'closed')
	""")

	op.execute("""
		CREATE TYPE projectissueseverity AS ENUM ('low', 'medium', 'high', 'critical')
	""")

	op.execute("""
		CREATE TYPE projectissuetype AS ENUM (
			'equipment', 'quality', 'staffing', 'scheduling', 'document', 'other'
		)
	""")

	# scanning_batches table
	op.create_table(
		'scanning_batches',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('project_id', postgresql.UUID(as_uuid=True),
			sa.ForeignKey('scanning_projects.id', ondelete='CASCADE'), nullable=False, index=True),
		sa.Column('batch_number', sa.String(100), nullable=False),
		sa.Column('type', postgresql.ENUM('box', 'folder', 'volume', name='scanningbatchtype', create_type=False),
			server_default='box'),
		sa.Column('physical_location', sa.String(255)),
		sa.Column('barcode', sa.String(100)),
		sa.Column('estimated_pages', sa.Integer, server_default='0'),
		sa.Column('actual_pages', sa.Integer, server_default='0'),
		sa.Column('scanned_pages', sa.Integer, server_default='0'),
		sa.Column('status', postgresql.ENUM(
			'pending', 'unbundling', 'scanning', 'repacking', 'returned',
			'ocr_processing', 'qc_pending', 'qc_passed', 'qc_failed', 'completed',
			name='scanningbatchstatus', create_type=False), server_default='pending'),
		sa.Column('assigned_operator_id', postgresql.UUID(as_uuid=True)),
		sa.Column('assigned_operator_name', sa.String(255)),
		sa.Column('assigned_scanner_id', postgresql.UUID(as_uuid=True)),
		sa.Column('assigned_scanner_name', sa.String(255)),
		sa.Column('notes', sa.String(1000)),
		sa.Column('started_at', postgresql.TIMESTAMP(timezone=True)),
		sa.Column('completed_at', postgresql.TIMESTAMP(timezone=True)),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
	)
	op.create_index('idx_scanning_batches_status', 'scanning_batches', ['project_id', 'status'])

	# scanning_milestones table
	op.create_table(
		'scanning_milestones',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('project_id', postgresql.UUID(as_uuid=True),
			sa.ForeignKey('scanning_projects.id', ondelete='CASCADE'), nullable=False, index=True),
		sa.Column('name', sa.String(255), nullable=False),
		sa.Column('description', sa.String(1000)),
		sa.Column('target_date', postgresql.TIMESTAMP(timezone=True)),
		sa.Column('target_pages', sa.Integer, server_default='0'),
		sa.Column('actual_pages', sa.Integer, server_default='0'),
		sa.Column('status', postgresql.ENUM('pending', 'in_progress', 'completed', 'overdue',
			name='milestonestatus', create_type=False), server_default='pending'),
		sa.Column('completed_at', postgresql.TIMESTAMP(timezone=True)),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
	)

	# qc_samples table
	op.create_table(
		'qc_samples',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('batch_id', postgresql.UUID(as_uuid=True),
			sa.ForeignKey('scanning_batches.id', ondelete='CASCADE'), nullable=False, index=True),
		sa.Column('page_id', sa.String(36)),
		sa.Column('page_number', sa.Integer),
		sa.Column('review_status', postgresql.ENUM('pending', 'passed', 'failed', 'needs_rescan',
			name='qcreviewstatus', create_type=False), server_default='pending'),
		sa.Column('image_quality', sa.Integer, server_default='0'),
		sa.Column('ocr_accuracy', sa.Integer),
		sa.Column('issues', postgresql.JSONB, server_default='[]'),
		sa.Column('reviewer_id', sa.String(36)),
		sa.Column('reviewer_name', sa.String(255)),
		sa.Column('reviewed_at', postgresql.TIMESTAMP(timezone=True)),
		sa.Column('notes', sa.String(1000)),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
	)

	# project_phases table
	op.create_table(
		'project_phases',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('project_id', postgresql.UUID(as_uuid=True),
			sa.ForeignKey('scanning_projects.id', ondelete='CASCADE'), nullable=False, index=True),
		sa.Column('name', sa.String(255), nullable=False),
		sa.Column('description', sa.String(1000)),
		sa.Column('sequence_order', sa.Integer, server_default='0'),
		sa.Column('status', sa.String(50), server_default='pending'),
		sa.Column('estimated_pages', sa.Integer, server_default='0'),
		sa.Column('scanned_pages', sa.Integer, server_default='0'),
		sa.Column('start_date', postgresql.TIMESTAMP(timezone=True)),
		sa.Column('end_date', postgresql.TIMESTAMP(timezone=True)),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
	)

	# progress_snapshots table
	op.create_table(
		'progress_snapshots',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('project_id', postgresql.UUID(as_uuid=True),
			sa.ForeignKey('scanning_projects.id', ondelete='CASCADE'), nullable=False, index=True),
		sa.Column('snapshot_date', sa.Date, nullable=False),
		sa.Column('total_batches', sa.Integer, server_default='0'),
		sa.Column('completed_batches', sa.Integer, server_default='0'),
		sa.Column('total_pages', sa.Integer, server_default='0'),
		sa.Column('scanned_pages', sa.Integer, server_default='0'),
		sa.Column('verified_pages', sa.Integer, server_default='0'),
		sa.Column('rejected_pages', sa.Integer, server_default='0'),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
	)
	op.create_index('idx_progress_snapshots_date', 'progress_snapshots', ['project_id', 'snapshot_date'])

	# daily_project_metrics table
	op.create_table(
		'daily_project_metrics',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('project_id', postgresql.UUID(as_uuid=True),
			sa.ForeignKey('scanning_projects.id', ondelete='CASCADE'), nullable=False, index=True),
		sa.Column('metric_date', sa.Date, nullable=False),
		sa.Column('pages_scanned', sa.Integer, server_default='0'),
		sa.Column('pages_verified', sa.Integer, server_default='0'),
		sa.Column('pages_rejected', sa.Integer, server_default='0'),
		sa.Column('batches_started', sa.Integer, server_default='0'),
		sa.Column('batches_completed', sa.Integer, server_default='0'),
		sa.Column('avg_pages_per_hour', sa.Float),
		sa.Column('quality_score', sa.Float),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
	)
	op.create_index('idx_daily_metrics_date', 'daily_project_metrics', ['project_id', 'metric_date'])
	op.create_unique_constraint('uq_daily_metrics', 'daily_project_metrics', ['project_id', 'metric_date'])

	# operator_daily_metrics table
	op.create_table(
		'operator_daily_metrics',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('project_id', postgresql.UUID(as_uuid=True),
			sa.ForeignKey('scanning_projects.id', ondelete='CASCADE'), nullable=False, index=True),
		sa.Column('operator_id', postgresql.UUID(as_uuid=True), nullable=False, index=True),
		sa.Column('metric_date', sa.Date, nullable=False),
		sa.Column('scanner_id', postgresql.UUID(as_uuid=True)),
		sa.Column('pages_scanned', sa.Integer, server_default='0'),
		sa.Column('batches_completed', sa.Integer, server_default='0'),
		sa.Column('errors_count', sa.Integer, server_default='0'),
		sa.Column('hours_worked', sa.Float),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
	)
	op.create_index('idx_operator_metrics_date', 'operator_daily_metrics', ['operator_id', 'metric_date'])
	op.create_unique_constraint('uq_operator_daily_metrics', 'operator_daily_metrics',
		['project_id', 'operator_id', 'metric_date'])

	# project_issues table
	op.create_table(
		'project_issues',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('project_id', postgresql.UUID(as_uuid=True),
			sa.ForeignKey('scanning_projects.id', ondelete='CASCADE'), nullable=False, index=True),
		sa.Column('title', sa.String(255), nullable=False),
		sa.Column('description', sa.Text),
		sa.Column('batch_id', postgresql.UUID(as_uuid=True),
			sa.ForeignKey('scanning_batches.id', ondelete='SET NULL')),
		sa.Column('issue_type', postgresql.ENUM(
			'equipment', 'quality', 'staffing', 'scheduling', 'document', 'other',
			name='projectissuetype', create_type=False), server_default='other'),
		sa.Column('severity', postgresql.ENUM('low', 'medium', 'high', 'critical',
			name='projectissueseverity', create_type=False), server_default='medium'),
		sa.Column('status', postgresql.ENUM('open', 'in_progress', 'resolved', 'closed',
			name='projectissuestatus', create_type=False), server_default='open'),
		sa.Column('reported_by_id', postgresql.UUID(as_uuid=True)),
		sa.Column('reported_by_name', sa.String(255)),
		sa.Column('assigned_to_id', postgresql.UUID(as_uuid=True)),
		sa.Column('assigned_to_name', sa.String(255)),
		sa.Column('resolution', sa.Text),
		sa.Column('resolved_at', postgresql.TIMESTAMP(timezone=True)),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
	)
	op.create_index('idx_project_issues_status', 'project_issues', ['project_id', 'status'])


def downgrade() -> None:
	op.drop_table('project_issues')
	op.drop_table('operator_daily_metrics')
	op.drop_table('daily_project_metrics')
	op.drop_table('progress_snapshots')
	op.drop_table('project_phases')
	op.drop_table('qc_samples')
	op.drop_table('scanning_milestones')
	op.drop_table('scanning_batches')

	op.execute('DROP TYPE IF EXISTS projectissuetype')
	op.execute('DROP TYPE IF EXISTS projectissueseverity')
	op.execute('DROP TYPE IF EXISTS projectissuestatus')
	op.execute('DROP TYPE IF EXISTS issuetype')
	op.execute('DROP TYPE IF EXISTS issueseverity')
	op.execute('DROP TYPE IF EXISTS qcreviewstatus')
	op.execute('DROP TYPE IF EXISTS milestonestatus')
	op.execute('DROP TYPE IF EXISTS scanningbatchtype')
	op.execute('DROP TYPE IF EXISTS scanningbatchstatus')

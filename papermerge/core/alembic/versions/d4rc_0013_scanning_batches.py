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

	# project_phases, progress_snapshots, daily_project_metrics, operator_daily_metrics,
	# and project_issues were already created in d4rc_0002. Add scanning_batch_id to
	# project_issues so issues can reference the new scanning_batches table.
	op.add_column('project_issues', sa.Column(
		'scanning_batch_id',
		postgresql.UUID(as_uuid=True),
		sa.ForeignKey('scanning_batches.id', ondelete='SET NULL'),
		nullable=True,
	))


def downgrade() -> None:
	op.drop_column('project_issues', 'scanning_batch_id')
	op.drop_table('qc_samples')
	op.drop_table('scanning_milestones')
	op.drop_table('scanning_batches')

	op.execute('DROP TYPE IF EXISTS qcreviewstatus')
	op.execute('DROP TYPE IF EXISTS milestonestatus')
	op.execute('DROP TYPE IF EXISTS scanningbatchtype')
	op.execute('DROP TYPE IF EXISTS scanningbatchstatus')

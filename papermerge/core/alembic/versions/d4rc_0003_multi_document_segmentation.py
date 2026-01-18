# (c) Copyright Datacraft, 2026
"""Multi-document segmentation tables for splitting combined scans.

Revision ID: d4rc_0003
Revises: d4rc_0002
Create Date: 2026-01-18

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'd4rc_0003'
down_revision: Union[str, None] = 'd4rc_0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
	# Segmentation Jobs - tracks async segmentation requests
	op.create_table(
		'segmentation_jobs',
		sa.Column('id', sa.String(36), primary_key=True),
		sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
		sa.Column('source_document_id', sa.String(36), nullable=False),
		sa.Column('source_page_number', sa.Integer),
		sa.Column('method', sa.String(30), nullable=False, server_default='hybrid'),
		sa.Column('auto_create_documents', sa.Boolean, server_default='false'),
		sa.Column('min_confidence_threshold', sa.Float, server_default='0.6'),
		sa.Column('status', sa.String(30), nullable=False, server_default='pending'),
		sa.Column('error_message', sa.Text),
		sa.Column('documents_detected', sa.Integer, server_default='0'),
		sa.Column('segments_created', sa.Integer, server_default='0'),
		sa.Column('processing_time_ms', sa.Float),
		sa.Column('celery_task_id', sa.String(255)),
		sa.Column('initiated_by_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL')),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.Column('started_at', postgresql.TIMESTAMP(timezone=True)),
		sa.Column('completed_at', postgresql.TIMESTAMP(timezone=True)),
	)
	op.create_index('idx_segmentation_jobs_tenant', 'segmentation_jobs', ['tenant_id'])
	op.create_index('idx_segmentation_jobs_status', 'segmentation_jobs', ['status'])
	op.create_index('idx_segmentation_jobs_source', 'segmentation_jobs', ['source_document_id'])

	# Scan Segments - individual documents detected within a scan
	op.create_table(
		'scan_segments',
		sa.Column('id', sa.String(36), primary_key=True),
		sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
		sa.Column('original_scan_id', sa.String(36), nullable=False),  # The original scanned document
		sa.Column('original_page_number', sa.Integer, nullable=False),
		sa.Column('document_id', sa.String(36)),  # Created document (if any)
		sa.Column('segment_number', sa.Integer, nullable=False),  # 1-based position within the scan
		sa.Column('total_segments', sa.Integer, nullable=False),  # Total segments detected in scan

		# Boundary coordinates (pixels)
		sa.Column('boundary_x', sa.Integer),
		sa.Column('boundary_y', sa.Integer),
		sa.Column('boundary_width', sa.Integer),
		sa.Column('boundary_height', sa.Integer),

		# Rotation and deskewing
		sa.Column('rotation_angle', sa.Float, server_default='0.0'),
		sa.Column('was_deskewed', sa.Boolean, server_default='false'),

		# Segmentation metadata
		sa.Column('segmentation_confidence', sa.Float, nullable=False),
		sa.Column('segmentation_method', sa.String(30), nullable=False),  # vlm, edge_detection, contour, hybrid
		sa.Column('status', sa.String(20), nullable=False, server_default='pending'),  # pending, approved, rejected, merged, split

		# Review workflow
		sa.Column('manually_verified', sa.Boolean, server_default='false'),
		sa.Column('verified_by_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL')),
		sa.Column('verified_at', postgresql.TIMESTAMP(timezone=True)),

		# Additional metadata
		sa.Column('document_type_hint', sa.String(100)),  # VLM detected type hint
		sa.Column('segment_width', sa.Integer),
		sa.Column('segment_height', sa.Integer),
		sa.Column('segment_file_path', sa.String(1000)),  # Path to extracted segment image
		sa.Column('notes', sa.Text),
		sa.Column('processing_time_ms', sa.Float),

		# Timestamps
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
	)
	op.create_index('idx_scan_segments_tenant', 'scan_segments', ['tenant_id'])
	op.create_index('idx_scan_segments_original', 'scan_segments', ['original_scan_id'])
	op.create_index('idx_scan_segments_status', 'scan_segments', ['status'])
	op.create_index('idx_scan_segments_document', 'scan_segments', ['document_id'])
	op.create_index('idx_scan_segments_review', 'scan_segments', ['manually_verified', 'segmentation_confidence'])


def downgrade() -> None:
	op.drop_table('scan_segments')
	op.drop_table('segmentation_jobs')

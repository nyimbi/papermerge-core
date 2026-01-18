# (c) Copyright Datacraft, 2026
"""
ORM models for multi-document segmentation.

Tracks relationships between original scans and extracted document segments.
"""
import enum
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
	String,
	Integer,
	Float,
	Text,
	ForeignKey,
	DateTime,
	Enum,
	Boolean,
	Index,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from uuid_extensions import uuid7str

from papermerge.core.db.base import Base

if TYPE_CHECKING:
	from papermerge.core.features.users.db.orm import User
	from papermerge.core.features.document.db.orm import Document


class SegmentationMethod(str, enum.Enum):
	"""Methods used for document boundary detection."""
	VLM = "vlm"  # Vision-Language Model
	EDGE_DETECTION = "edge_detection"
	CONTOUR = "contour"
	HYBRID = "hybrid"
	TEMPLATE = "template"
	MANUAL = "manual"


class SegmentStatus(str, enum.Enum):
	"""Status of a segmented document."""
	PENDING = "pending"  # Extracted but not reviewed
	APPROVED = "approved"  # Verified correct
	REJECTED = "rejected"  # Incorrect segmentation
	MERGED = "merged"  # Merged with another segment
	SPLIT = "split"  # Further split into more segments


class ScanSegment(Base):
	"""
	Represents a document segment extracted from a multi-document scan.

	When a scan contains multiple documents (e.g., two invoices side-by-side),
	this table tracks the relationship between the original scan file and
	each extracted document segment.
	"""
	__tablename__ = "scan_segments"

	id: Mapped[str] = mapped_column(
		String(36),
		primary_key=True,
		default=uuid7str,
	)

	# Reference to the original scanned image/PDF
	original_scan_id: Mapped[str] = mapped_column(
		String(36),
		nullable=False,
	)
	# The original page number within a multi-page scan
	original_page_number: Mapped[int] = mapped_column(Integer, default=1)

	# Reference to the extracted document (if created)
	document_id: Mapped[str | None] = mapped_column(
		String(36),
	)

	# Segment ordering within the original scan
	segment_number: Mapped[int] = mapped_column(Integer, nullable=False)
	total_segments: Mapped[int] = mapped_column(Integer, nullable=False)

	# Boundary coordinates in original image (pixels)
	boundary_x: Mapped[int | None] = mapped_column(Integer)
	boundary_y: Mapped[int | None] = mapped_column(Integer)
	boundary_width: Mapped[int | None] = mapped_column(Integer)
	boundary_height: Mapped[int | None] = mapped_column(Integer)

	# Rotation/skew correction applied
	rotation_angle: Mapped[float] = mapped_column(Float, default=0.0)
	was_deskewed: Mapped[bool] = mapped_column(Boolean, default=False)

	# Confidence score for segmentation (0.0 to 1.0)
	segmentation_confidence: Mapped[float] = mapped_column(Float, default=1.0)

	# Detection method used
	segmentation_method: Mapped[SegmentationMethod] = mapped_column(
		Enum(SegmentationMethod),
		default=SegmentationMethod.HYBRID,
	)

	# Status and review
	status: Mapped[SegmentStatus] = mapped_column(
		Enum(SegmentStatus),
		default=SegmentStatus.PENDING,
	)
	manually_verified: Mapped[bool] = mapped_column(Boolean, default=False)
	verified_by_id: Mapped[UUID | None] = mapped_column(
		ForeignKey("users.id", ondelete="SET NULL"),
	)
	verified_at: Mapped[datetime | None] = mapped_column(DateTime)

	# Document type detected during segmentation
	document_type_hint: Mapped[str | None] = mapped_column(String(50))

	# Extracted segment dimensions
	segment_width: Mapped[int | None] = mapped_column(Integer)
	segment_height: Mapped[int | None] = mapped_column(Integer)

	# Path to extracted segment image (before document creation)
	segment_file_path: Mapped[str | None] = mapped_column(String(512))

	# Processing metadata
	processing_time_ms: Mapped[float | None] = mapped_column(Float)
	vlm_response: Mapped[str | None] = mapped_column(Text)
	raw_detection_data: Mapped[dict | None] = mapped_column(JSONB)

	# Review notes
	notes: Mapped[str | None] = mapped_column(Text)

	# Timestamps
	created_at: Mapped[datetime] = mapped_column(
		DateTime,
		default=datetime.utcnow,
	)
	updated_at: Mapped[datetime] = mapped_column(
		DateTime,
		default=datetime.utcnow,
		onupdate=datetime.utcnow,
	)

	# Tenant isolation
	tenant_id: Mapped[UUID | None] = mapped_column(
		ForeignKey("tenants.id", ondelete="CASCADE"),
	)

	# Relationships
	verified_by: Mapped["User | None"] = relationship(
		"User",
		foreign_keys=[verified_by_id],
	)

	__table_args__ = (
		Index("ix_scan_segments_original", "original_scan_id"),
		Index("ix_scan_segments_document", "document_id"),
		Index("ix_scan_segments_status", "status"),
		Index("ix_scan_segments_tenant", "tenant_id"),
		Index("ix_scan_segments_confidence", "segmentation_confidence"),
		# Unique constraint: one segment number per original scan page
		Index(
			"uq_scan_segments_page_segment",
			"original_scan_id",
			"original_page_number",
			"segment_number",
			unique=True,
		),
	)

	@property
	def needs_review(self) -> bool:
		"""Check if this segment needs manual review."""
		return (
			not self.manually_verified and
			(self.segmentation_confidence < 0.7 or self.status == SegmentStatus.PENDING)
		)

	@property
	def boundary_area(self) -> int | None:
		"""Calculate boundary area in pixels."""
		if self.boundary_width and self.boundary_height:
			return self.boundary_width * self.boundary_height
		return None

	def to_dict(self) -> dict:
		"""Convert to dictionary for API responses."""
		return {
			"id": self.id,
			"original_scan_id": self.original_scan_id,
			"original_page_number": self.original_page_number,
			"document_id": self.document_id,
			"segment_number": self.segment_number,
			"total_segments": self.total_segments,
			"boundary": {
				"x": self.boundary_x,
				"y": self.boundary_y,
				"width": self.boundary_width,
				"height": self.boundary_height,
			} if self.boundary_x is not None else None,
			"rotation_angle": self.rotation_angle,
			"was_deskewed": self.was_deskewed,
			"segmentation_confidence": self.segmentation_confidence,
			"segmentation_method": self.segmentation_method.value,
			"status": self.status.value,
			"manually_verified": self.manually_verified,
			"document_type_hint": self.document_type_hint,
			"needs_review": self.needs_review,
			"created_at": self.created_at.isoformat() if self.created_at else None,
		}


class SegmentationJob(Base):
	"""
	Tracks segmentation processing jobs.

	Used to monitor async segmentation operations and their results.
	"""
	__tablename__ = "segmentation_jobs"

	id: Mapped[str] = mapped_column(
		String(36),
		primary_key=True,
		default=uuid7str,
	)

	# Source document/scan
	source_document_id: Mapped[str] = mapped_column(
		String(36),
		nullable=False,
	)
	source_page_number: Mapped[int | None] = mapped_column(Integer)

	# Job configuration
	method: Mapped[SegmentationMethod] = mapped_column(
		Enum(SegmentationMethod),
		default=SegmentationMethod.HYBRID,
	)
	auto_create_documents: Mapped[bool] = mapped_column(Boolean, default=False)
	min_confidence_threshold: Mapped[float] = mapped_column(Float, default=0.6)

	# Job status
	status: Mapped[str] = mapped_column(
		String(20),
		default="pending",
	)  # pending, processing, completed, failed
	error_message: Mapped[str | None] = mapped_column(Text)

	# Results
	documents_detected: Mapped[int] = mapped_column(Integer, default=0)
	segments_created: Mapped[int] = mapped_column(Integer, default=0)
	processing_time_ms: Mapped[float | None] = mapped_column(Float)

	# Celery task tracking
	celery_task_id: Mapped[str | None] = mapped_column(String(50))

	# User who initiated
	initiated_by_id: Mapped[UUID | None] = mapped_column(
		ForeignKey("users.id", ondelete="SET NULL"),
	)

	# Timestamps
	created_at: Mapped[datetime] = mapped_column(
		DateTime,
		default=datetime.utcnow,
	)
	started_at: Mapped[datetime | None] = mapped_column(DateTime)
	completed_at: Mapped[datetime | None] = mapped_column(DateTime)

	# Tenant isolation
	tenant_id: Mapped[UUID | None] = mapped_column(
		ForeignKey("tenants.id", ondelete="CASCADE"),
	)

	__table_args__ = (
		Index("ix_segmentation_jobs_source", "source_document_id"),
		Index("ix_segmentation_jobs_status", "status"),
		Index("ix_segmentation_jobs_tenant", "tenant_id"),
		Index("ix_segmentation_jobs_celery", "celery_task_id"),
	)

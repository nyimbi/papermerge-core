# (c) Copyright Datacraft, 2026
"""
ORM models for batch tracking and source locations.
"""
import enum
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
	String,
	Integer,
	Text,
	ForeignKey,
	DateTime,
	Enum,
	UniqueConstraint,
	Index,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from uuid_extensions import uuid7str

from papermerge.core.db.base import Base

if TYPE_CHECKING:
	from papermerge.core.features.users.db.orm import User
	from papermerge.core.features.scanners.db.orm import Scanner


class LocationType(str, enum.Enum):
	"""Types of physical source locations."""
	ARCHIVE_BOX = "archive_box"
	FILING_CABINET = "filing_cabinet"
	DRAWER = "drawer"
	SHELF = "shelf"
	ROOM = "room"
	BUILDING = "building"
	OFFSITE_STORAGE = "offsite_storage"
	DEPARTMENT = "department"
	FOLDER = "folder"
	OTHER = "other"


class BatchStatus(str, enum.Enum):
	"""Status of a scan batch."""
	CREATED = "created"
	IN_PROGRESS = "in_progress"
	PAUSED = "paused"
	COMPLETED = "completed"
	FAILED = "failed"
	CANCELLED = "cancelled"
	UNDER_REVIEW = "under_review"
	APPROVED = "approved"


class SourceLocation(Base):
	"""
	Represents a physical location where documents originate.
	Supports hierarchical structure (e.g., Building > Room > Cabinet > Drawer).
	"""
	__tablename__ = "source_locations"

	id: Mapped[str] = mapped_column(
		String(32),
		primary_key=True,
		default=uuid7str,
	)
	name: Mapped[str] = mapped_column(String(255), nullable=False)
	code: Mapped[str | None] = mapped_column(String(50), unique=True)
	location_type: Mapped[LocationType] = mapped_column(
		Enum(LocationType),
		default=LocationType.OTHER,
	)
	description: Mapped[str | None] = mapped_column(Text)
	parent_id: Mapped[str | None] = mapped_column(
		String(32),
		ForeignKey("source_locations.id", ondelete="SET NULL"),
	)
	# Physical address or coordinates
	address: Mapped[str | None] = mapped_column(Text)
	# Additional metadata (barcode, capacity, etc.)
	metadata: Mapped[dict | None] = mapped_column(JSONB)
	# QR/barcode for physical tracking
	barcode: Mapped[str | None] = mapped_column(String(100), unique=True)
	# Status
	is_active: Mapped[bool] = mapped_column(default=True)
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
	parent: Mapped["SourceLocation | None"] = relationship(
		"SourceLocation",
		remote_side=[id],
		back_populates="children",
	)
	children: Mapped[list["SourceLocation"]] = relationship(
		"SourceLocation",
		back_populates="parent",
	)
	batches: Mapped[list["ScanBatch"]] = relationship(
		"ScanBatch",
		back_populates="source_location",
	)

	__table_args__ = (
		Index("ix_source_locations_tenant", "tenant_id"),
		Index("ix_source_locations_parent", "parent_id"),
		Index("ix_source_locations_type", "location_type"),
	)


class ScanBatch(Base):
	"""
	Represents a batch of documents scanned together.
	Tracks scanning sessions and provides grouping for provenance.
	"""
	__tablename__ = "scan_batches"

	id: Mapped[str] = mapped_column(
		String(32),
		primary_key=True,
		default=uuid7str,
	)
	# Human-readable batch number (e.g., BATCH-2026-001234)
	batch_number: Mapped[str] = mapped_column(String(50), unique=True)
	name: Mapped[str | None] = mapped_column(String(255))
	description: Mapped[str | None] = mapped_column(Text)

	# Source tracking
	source_location_id: Mapped[str | None] = mapped_column(
		String(32),
		ForeignKey("source_locations.id", ondelete="SET NULL"),
	)
	# Scanner used
	scanner_id: Mapped[str | None] = mapped_column(
		String(32),
		ForeignKey("scanners.id", ondelete="SET NULL"),
	)
	# Operator who performed the scanning
	operator_id: Mapped[UUID | None] = mapped_column(
		ForeignKey("core_user.id", ondelete="SET NULL"),
	)
	# Scanning project association
	project_id: Mapped[str | None] = mapped_column(
		String(32),
		ForeignKey("scanning_projects.id", ondelete="SET NULL"),
	)

	# Status tracking
	status: Mapped[BatchStatus] = mapped_column(
		Enum(BatchStatus),
		default=BatchStatus.CREATED,
	)

	# Statistics
	total_documents: Mapped[int] = mapped_column(Integer, default=0)
	total_pages: Mapped[int] = mapped_column(Integer, default=0)
	processed_documents: Mapped[int] = mapped_column(Integer, default=0)
	processed_pages: Mapped[int] = mapped_column(Integer, default=0)
	failed_documents: Mapped[int] = mapped_column(Integer, default=0)

	# Quality metrics
	average_quality_score: Mapped[float | None] = mapped_column()
	documents_requiring_rescan: Mapped[int] = mapped_column(Integer, default=0)

	# Timing
	started_at: Mapped[datetime | None] = mapped_column(DateTime)
	completed_at: Mapped[datetime | None] = mapped_column(DateTime)

	# Physical batch identifiers
	box_label: Mapped[str | None] = mapped_column(String(100))
	folder_label: Mapped[str | None] = mapped_column(String(100))

	# Scan settings used
	scan_settings: Mapped[dict | None] = mapped_column(JSONB)
	# Additional metadata
	metadata: Mapped[dict | None] = mapped_column(JSONB)

	# Notes and comments
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
	source_location: Mapped["SourceLocation | None"] = relationship(
		"SourceLocation",
		back_populates="batches",
	)
	documents: Mapped[list["DocumentProvenance"]] = relationship(
		"DocumentProvenance",
		back_populates="batch",
	)

	__table_args__ = (
		Index("ix_scan_batches_tenant", "tenant_id"),
		Index("ix_scan_batches_status", "status"),
		Index("ix_scan_batches_operator", "operator_id"),
		Index("ix_scan_batches_project", "project_id"),
		Index("ix_scan_batches_created", "created_at"),
	)


# Forward reference for DocumentProvenance
from papermerge.core.features.provenance.db.orm import DocumentProvenance

# (c) Copyright Datacraft, 2026
"""
ORM models for document provenance and event tracking.
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
	Index,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from uuid_extensions import uuid7str

from papermerge.core.db.base import Base

if TYPE_CHECKING:
	from papermerge.core.features.batches.db.orm import ScanBatch
	from papermerge.core.features.users.db.orm import User
	from papermerge.core.features.inventory.db.orm import PhysicalManifest


class VerificationStatus(str, enum.Enum):
	"""Status of document verification."""
	UNVERIFIED = "unverified"
	PENDING = "pending"
	VERIFIED = "verified"
	REJECTED = "rejected"
	EXPIRED = "expired"


class EventType(str, enum.Enum):
	"""Types of provenance events."""
	# Origin events
	CREATED = "created"
	SCANNED = "scanned"
	IMPORTED = "imported"
	UPLOADED = "uploaded"
	EMAIL_RECEIVED = "email_received"

	# Processing events
	OCR_STARTED = "ocr_started"
	OCR_COMPLETED = "ocr_completed"
	OCR_FAILED = "ocr_failed"
	CLASSIFIED = "classified"
	METADATA_EXTRACTED = "metadata_extracted"
	QUALITY_ASSESSED = "quality_assessed"

	# Modification events
	EDITED = "edited"
	ANNOTATED = "annotated"
	REDACTED = "redacted"
	MERGED = "merged"
	SPLIT = "split"
	ROTATED = "rotated"
	CROPPED = "cropped"
	PAGE_ADDED = "page_added"
	PAGE_REMOVED = "page_removed"
	PAGE_REORDERED = "page_reordered"

	# Version events
	VERSION_CREATED = "version_created"
	VERSION_RESTORED = "version_restored"

	# Location events
	MOVED = "moved"
	COPIED = "copied"
	ARCHIVED = "archived"
	RESTORED = "restored"
	DELETED = "deleted"
	PERMANENTLY_DELETED = "permanently_deleted"

	# Access events
	VIEWED = "viewed"
	DOWNLOADED = "downloaded"
	PRINTED = "printed"
	SHARED = "shared"
	SHARED_REVOKED = "shared_revoked"

	# Verification events
	VERIFIED = "verified"
	SIGNATURE_ADDED = "signature_added"
	SIGNATURE_VERIFIED = "signature_verified"
	CHECKSUM_VERIFIED = "checksum_verified"

	# Workflow events
	WORKFLOW_STARTED = "workflow_started"
	WORKFLOW_STEP_COMPLETED = "workflow_step_completed"
	WORKFLOW_COMPLETED = "workflow_completed"
	APPROVAL_REQUESTED = "approval_requested"
	APPROVED = "approved"
	REJECTED = "rejected"

	# Export events
	EXPORTED = "exported"
	SYNCED = "synced"


class DocumentProvenance(Base):
	"""
	Core provenance record linking a document to its origin.
	Captures the complete chain of custody from physical source to digital storage.
	"""
	__tablename__ = "document_provenance"

	id: Mapped[str] = mapped_column(
		String(32),
		primary_key=True,
		default=uuid7str,
	)
	# Link to the document
	document_id: Mapped[UUID] = mapped_column(
		ForeignKey("core_document.id", ondelete="CASCADE"),
		unique=True,
	)
	# Batch this document was scanned in
	batch_id: Mapped[str | None] = mapped_column(
		String(32),
		ForeignKey("scan_batches.id", ondelete="SET NULL"),
	)
	# Link to physical manifest
	physical_manifest_id: Mapped[UUID | None] = mapped_column(
		PG_UUID(as_uuid=True),
		ForeignKey("physical_manifests.id", ondelete="SET NULL"),
	)

	# Original file information
	original_filename: Mapped[str | None] = mapped_column(String(500))
	original_file_hash: Mapped[str | None] = mapped_column(String(128))  # SHA-512
	original_file_size: Mapped[int | None] = mapped_column(Integer)
	original_mime_type: Mapped[str | None] = mapped_column(String(100))

	# Current file hash (for integrity verification)
	current_file_hash: Mapped[str | None] = mapped_column(String(128))
	blake3_hash: Mapped[str | None] = mapped_column(String(64))
	last_hash_verified_at: Mapped[datetime | None] = mapped_column(DateTime)

	# Physical source details
	source_location_detail: Mapped[str | None] = mapped_column(Text)
	# e.g., "Box 42, Folder 3, Document 17"
	physical_reference: Mapped[str | None] = mapped_column(String(255))

	# Ingestion details
	ingestion_source: Mapped[str | None] = mapped_column(String(50))
	# scanner, email, upload, api, import
	ingestion_timestamp: Mapped[datetime | None] = mapped_column(DateTime)
	ingestion_user_id: Mapped[UUID | None] = mapped_column(
		ForeignKey("core_user.id", ondelete="SET NULL"),
	)

	# Scan-specific metadata
	scanner_model: Mapped[str | None] = mapped_column(String(200))
	scan_resolution_dpi: Mapped[int | None] = mapped_column(Integer)
	scan_color_mode: Mapped[str | None] = mapped_column(String(50))
	scan_settings: Mapped[dict | None] = mapped_column(JSONB)

	# Page count tracking
	original_page_count: Mapped[int | None] = mapped_column(Integer)
	current_page_count: Mapped[int | None] = mapped_column(Integer)

	# Verification status
	verification_status: Mapped[VerificationStatus] = mapped_column(
		Enum(VerificationStatus),
		default=VerificationStatus.UNVERIFIED,
	)
	verified_at: Mapped[datetime | None] = mapped_column(DateTime)
	verified_by_id: Mapped[UUID | None] = mapped_column(
		ForeignKey("core_user.id", ondelete="SET NULL"),
	)
	verification_notes: Mapped[str | None] = mapped_column(Text)

	# Digital signature/certificate (for long-term archival)
	digital_signature: Mapped[str | None] = mapped_column(Text)
	signature_algorithm: Mapped[str | None] = mapped_column(String(50))
	signature_timestamp: Mapped[datetime | None] = mapped_column(DateTime)
	certificate_chain: Mapped[dict | None] = mapped_column(JSONB)

	# Duplicate detection
	is_duplicate: Mapped[bool] = mapped_column(default=False)
	duplicate_of_id: Mapped[str | None] = mapped_column(
		String(32),
		ForeignKey("document_provenance.id", ondelete="SET NULL"),
	)
	similarity_hash: Mapped[str | None] = mapped_column(String(64))
	# Perceptual hash

	# Additional metadata
	extra_data: Mapped[dict | None] = mapped_column(JSONB)

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
	batch: Mapped["ScanBatch | None"] = relationship(
		"ScanBatch",
		back_populates="documents",
	)
	physical_manifest: Mapped["PhysicalManifest | None"] = relationship(
		"PhysicalManifest",
	)
	events: Mapped[list["ProvenanceEvent"]] = relationship(
		"ProvenanceEvent",
		back_populates="provenance",
		order_by="ProvenanceEvent.timestamp",
	)
	duplicate_of: Mapped["DocumentProvenance | None"] = relationship(
		"DocumentProvenance",
		remote_side=[id],
		foreign_keys=[duplicate_of_id],
	)

	__table_args__ = (
		Index("ix_document_provenance_document", "document_id"),
		Index("ix_document_provenance_batch", "batch_id"),
		Index("ix_document_provenance_tenant", "tenant_id"),
		Index("ix_document_provenance_hash", "original_file_hash"),
		Index("ix_document_provenance_similarity", "similarity_hash"),
		Index("ix_document_provenance_verification", "verification_status"),
	)


class ProvenanceEvent(Base):
	"""
	Individual event in a document's provenance chain.
	Provides immutable audit trail of all document operations.
	"""
	__tablename__ = "provenance_events"

	id: Mapped[str] = mapped_column(
		String(32),
		primary_key=True,
		default=uuid7str,
	)
	# Link to provenance record
	provenance_id: Mapped[str] = mapped_column(
		String(32),
		ForeignKey("document_provenance.id", ondelete="CASCADE"),
	)

	# Event details
	event_type: Mapped[EventType] = mapped_column(Enum(EventType))
	timestamp: Mapped[datetime] = mapped_column(
		DateTime,
		default=datetime.utcnow,
	)

	# Actor
	actor_id: Mapped[UUID | None] = mapped_column(
		ForeignKey("core_user.id", ondelete="SET NULL"),
	)
	actor_type: Mapped[str | None] = mapped_column(String(50))
	# user, system, api, automation

	# Description
	description: Mapped[str | None] = mapped_column(Text)

	# Before/after state (for modifications)
	previous_state: Mapped[dict | None] = mapped_column(JSONB)
	new_state: Mapped[dict | None] = mapped_column(JSONB)

	# Related document (for merge/split operations)
	related_document_id: Mapped[UUID | None] = mapped_column(
		ForeignKey("core_document.id", ondelete="SET NULL"),
	)

	# IP address and user agent (for access tracking)
	ip_address: Mapped[str | None] = mapped_column(String(45))
	# IPv6
	user_agent: Mapped[str | None] = mapped_column(Text)

	# Workflow reference
	workflow_id: Mapped[str | None] = mapped_column(String(32))
	workflow_step_id: Mapped[str | None] = mapped_column(String(32))

	# Additional event data
	details: Mapped[dict | None] = mapped_column(JSONB)

	# Integrity
	event_hash: Mapped[str | None] = mapped_column(String(64))
	# SHA-256 of event data
	previous_event_hash: Mapped[str | None] = mapped_column(String(64))
	# Chain link

	# Relationships
	provenance: Mapped["DocumentProvenance"] = relationship(
		"DocumentProvenance",
		back_populates="events",
	)

	__table_args__ = (
		Index("ix_provenance_events_provenance", "provenance_id"),
		Index("ix_provenance_events_type", "event_type"),
		Index("ix_provenance_events_timestamp", "timestamp"),
		Index("ix_provenance_events_actor", "actor_id"),
		Index("ix_provenance_events_workflow", "workflow_id"),
	)

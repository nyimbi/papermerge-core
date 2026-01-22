# (c) Copyright Datacraft, 2026
"""Ingestion ORM models."""
import uuid
from datetime import datetime
from uuid import UUID
from enum import Enum

from sqlalchemy import String, ForeignKey, Integer, Boolean, Text, func, Index
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import TIMESTAMP, JSONB

from papermerge.core.db.base import Base
from papermerge.core.utils.tz import utc_now


class SourceType(str, Enum):
	WATCHED_FOLDER = "watched_folder"
	EMAIL = "email"
	API = "api"
	SCANNER = "scanner"


class IngestionMode(str, Enum):
	OPERATIONAL = "operational"
	ARCHIVAL = "archival"


class JobStatus(str, Enum):
	PENDING = "pending"
	PROCESSING = "processing"
	COMPLETED = "completed"
	FAILED = "failed"


class IngestionSource(Base):
	"""Document ingestion source configuration."""
	__tablename__ = "ingestion_sources"

	id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
	tenant_id: Mapped[UUID] = mapped_column(
		ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
	)

	name: Mapped[str] = mapped_column(String(255), nullable=False)
	source_type: Mapped[str] = mapped_column(String(50), nullable=False)

	# Configuration (JSON)
	# watched_folder: {"path": "/mnt/scans", "patterns": ["*.pdf"]}
	# email: {"address": "archive@corp.net", "imap_host": "..."}
	config: Mapped[dict] = mapped_column(JSONB, nullable=False)

	# Processing options
	mode: Mapped[str] = mapped_column(
		String(20), default=IngestionMode.OPERATIONAL.value, nullable=False
	)
	default_document_type_id: Mapped[UUID | None] = mapped_column(
		ForeignKey("document_types.id", ondelete="SET NULL")
	)
	apply_ocr: Mapped[bool] = mapped_column(Boolean, default=True)
	auto_route: Mapped[bool] = mapped_column(Boolean, default=True)

	is_active: Mapped[bool] = mapped_column(Boolean, default=True)
	last_checked_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

	# Timestamps
	created_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), default=utc_now, nullable=False
	)
	updated_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), default=utc_now, onupdate=func.now(), nullable=False
	)
	created_by: Mapped[UUID | None] = mapped_column(
		ForeignKey("users.id", ondelete="SET NULL")
	)

	__table_args__ = (
		Index("idx_ingestion_sources_tenant", "tenant_id", "is_active"),
	)


class IngestionJob(Base):
	"""Individual ingestion job."""
	__tablename__ = "ingestion_jobs"

	id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
	source_id: Mapped[UUID] = mapped_column(
		ForeignKey("ingestion_sources.id", ondelete="CASCADE"), nullable=False, index=True
	)
	batch_id: Mapped[UUID | None] = mapped_column(
		ForeignKey("ingestion_batches.id", ondelete="SET NULL"), index=True
	)

	# Source info
	source_path: Mapped[str | None] = mapped_column(String(1000))
	source_metadata: Mapped[dict | None] = mapped_column(JSONB)

	# Status
	status: Mapped[str] = mapped_column(
		String(50), default=JobStatus.PENDING.value, nullable=False
	)
	error_message: Mapped[str | None] = mapped_column(Text)
	retry_count: Mapped[int] = mapped_column(Integer, default=0)

	# Result
	document_id: Mapped[UUID | None] = mapped_column(
		ForeignKey("nodes.id", ondelete="SET NULL")
	)

	# Timing
	started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
	completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

	# Timestamps
	created_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), default=utc_now, nullable=False
	)

	__table_args__ = (
		Index("idx_ingestion_jobs_source", "source_id"),
		Index("idx_ingestion_jobs_status", "status"),
		Index("idx_ingestion_jobs_batch", "batch_id"),
	)


class IngestionBatch(Base):
	"""Group of ingestion jobs for batch processing."""
	__tablename__ = "ingestion_batches"

	id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
	tenant_id: Mapped[UUID] = mapped_column(
		ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
	)
	name: Mapped[str | None] = mapped_column(String(255))
	template_id: Mapped[UUID | None] = mapped_column(
		ForeignKey("ingestion_templates.id", ondelete="SET NULL")
	)

	# Progress
	total_files: Mapped[int] = mapped_column(Integer, default=0)
	processed_files: Mapped[int] = mapped_column(Integer, default=0)
	failed_files: Mapped[int] = mapped_column(Integer, default=0)
	status: Mapped[str] = mapped_column(String(50), default="pending")

	# Timing
	started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
	completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
	created_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), default=utc_now, nullable=False
	)
	created_by: Mapped[UUID | None] = mapped_column(
		ForeignKey("users.id", ondelete="SET NULL")
	)

	__table_args__ = (
		Index("idx_ingestion_batches_tenant", "tenant_id", "status"),
	)


class IngestionTemplate(Base):
	"""Reusable ingestion configuration templates."""
	__tablename__ = "ingestion_templates"

	id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
	tenant_id: Mapped[UUID] = mapped_column(
		ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
	)
	name: Mapped[str] = mapped_column(String(255), nullable=False)
	description: Mapped[str | None] = mapped_column(Text)

	# Configuration
	target_folder_id: Mapped[UUID | None] = mapped_column(
		ForeignKey("nodes.id", ondelete="SET NULL")
	)
	document_type_id: Mapped[UUID | None] = mapped_column(
		ForeignKey("document_types.id", ondelete="SET NULL")
	)
	apply_ocr: Mapped[bool] = mapped_column(Boolean, default=True)
	auto_classify: Mapped[bool] = mapped_column(Boolean, default=False)
	duplicate_check: Mapped[bool] = mapped_column(Boolean, default=True)

	# Validation rules (JSON)
	validation_rules: Mapped[dict | None] = mapped_column(JSONB)

	is_active: Mapped[bool] = mapped_column(Boolean, default=True)
	created_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), default=utc_now, nullable=False
	)


class IngestionValidationRule(Base):
	"""Validation rules for ingestion."""
	__tablename__ = "ingestion_validation_rules"

	id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
	tenant_id: Mapped[UUID] = mapped_column(
		ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
	)
	name: Mapped[str] = mapped_column(String(255), nullable=False)
	rule_type: Mapped[str] = mapped_column(String(50), nullable=False)  # file_size, file_type, naming

	# Rule configuration
	config: Mapped[dict] = mapped_column(JSONB, nullable=False)
	# file_size: {"max_mb": 50, "min_mb": 0}
	# file_type: {"allowed": ["pdf", "tiff", "jpg"], "blocked": []}
	# naming: {"pattern": "^[A-Z]{3}-\\d{6}.*", "required": true}

	is_active: Mapped[bool] = mapped_column(Boolean, default=True)
	created_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), default=utc_now, nullable=False
	)

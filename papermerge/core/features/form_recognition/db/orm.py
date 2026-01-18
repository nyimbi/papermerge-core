# (c) Copyright Datacraft, 2026
"""Form recognition ORM models."""
import uuid
from datetime import datetime, date
from uuid import UUID
from decimal import Decimal
from enum import Enum

from sqlalchemy import String, ForeignKey, Integer, Boolean, Text, Float, Numeric, Date, func, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import TIMESTAMP, JSONB, ARRAY

from papermerge.core.db.base import Base
from papermerge.core.utils.tz import utc_now


class FieldType(str, Enum):
	TEXT = "text"
	CHECKBOX = "checkbox"
	RADIO = "radio"
	SIGNATURE = "signature"
	DATE = "date"
	NUMBER = "number"
	INITIALS = "initials"
	HANDWRITING = "handwriting"


class ExtractionStatus(str, Enum):
	PENDING = "pending"
	PROCESSING = "processing"
	COMPLETED = "completed"
	FAILED = "failed"
	REVIEW_REQUIRED = "review_required"


class LinkType(str, Enum):
	SAME_VALUE = "same_value"
	SIGNATURE_FOR = "signature_for"
	INITIAL_FOR = "initial_for"


class FormTemplate(Base):
	"""Form template definition."""
	__tablename__ = "form_templates"

	id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
	tenant_id: Mapped[UUID] = mapped_column(
		ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
	)

	name: Mapped[str] = mapped_column(String(255), nullable=False)
	description: Mapped[str | None] = mapped_column(Text)
	category: Mapped[str | None] = mapped_column(String(100))

	# Template configuration
	page_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
	template_image_urls: Mapped[list[str] | None] = mapped_column(ARRAY(String))

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

	# Relationships
	fields: Mapped[list["FormField"]] = relationship(
		"FormField", back_populates="template", cascade="all, delete-orphan"
	)

	__table_args__ = (
		Index("idx_form_templates_tenant", "tenant_id"),
	)


class FormField(Base):
	"""Field definition within a form template."""
	__tablename__ = "form_fields"

	id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
	template_id: Mapped[UUID] = mapped_column(
		ForeignKey("form_templates.id", ondelete="CASCADE"), nullable=False, index=True
	)

	name: Mapped[str] = mapped_column(String(100), nullable=False)
	label: Mapped[str | None] = mapped_column(String(255))
	field_type: Mapped[str] = mapped_column(String(50), nullable=False)
	page_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

	# Bounding box (normalized 0-1 coordinates)
	x: Mapped[float] = mapped_column(Float, nullable=False)
	y: Mapped[float] = mapped_column(Float, nullable=False)
	width: Mapped[float] = mapped_column(Float, nullable=False)
	height: Mapped[float] = mapped_column(Float, nullable=False)

	# Validation
	required: Mapped[bool] = mapped_column(Boolean, default=False)
	validation_regex: Mapped[str | None] = mapped_column(String(255))
	expected_format: Mapped[str | None] = mapped_column(String(100))

	# Cross-page linking
	linked_field_id: Mapped[UUID | None] = mapped_column(
		ForeignKey("form_fields.id", ondelete="SET NULL")
	)
	link_type: Mapped[str | None] = mapped_column(String(50))

	# Timestamps
	created_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), default=utc_now, nullable=False
	)

	# Relationships
	template: Mapped["FormTemplate"] = relationship("FormTemplate", back_populates="fields")


class FormExtraction(Base):
	"""Form extraction job."""
	__tablename__ = "form_extractions"

	id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
	document_id: Mapped[UUID] = mapped_column(
		ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False, index=True
	)
	template_id: Mapped[UUID | None] = mapped_column(
		ForeignKey("form_templates.id", ondelete="SET NULL")
	)

	# Status
	status: Mapped[str] = mapped_column(
		String(50), default=ExtractionStatus.PENDING.value, nullable=False
	)
	confidence_score: Mapped[float | None] = mapped_column(Float)

	# Metadata
	extracted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
	reviewed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
	reviewed_by: Mapped[UUID | None] = mapped_column(
		ForeignKey("users.id", ondelete="SET NULL")
	)

	# Timestamps
	created_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), default=utc_now, nullable=False
	)

	# Relationships
	field_values: Mapped[list["ExtractedFieldValue"]] = relationship(
		"ExtractedFieldValue", back_populates="extraction", cascade="all, delete-orphan"
	)

	__table_args__ = (
		Index("idx_form_extractions_document", "document_id"),
		Index("idx_form_extractions_status", "status"),
	)


class ExtractedFieldValue(Base):
	"""Extracted field value."""
	__tablename__ = "extracted_field_values"

	id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
	extraction_id: Mapped[UUID] = mapped_column(
		ForeignKey("form_extractions.id", ondelete="CASCADE"), nullable=False, index=True
	)
	field_id: Mapped[UUID | None] = mapped_column(
		ForeignKey("form_fields.id", ondelete="SET NULL")
	)

	page_number: Mapped[int] = mapped_column(Integer, nullable=False)
	field_name: Mapped[str] = mapped_column(String(100), nullable=False)
	field_type: Mapped[str] = mapped_column(String(50), nullable=False)

	# Extracted values (one will be populated based on type)
	text_value: Mapped[str | None] = mapped_column(Text)
	boolean_value: Mapped[bool | None] = mapped_column(Boolean)
	date_value: Mapped[date | None] = mapped_column(Date)
	number_value: Mapped[Decimal | None] = mapped_column(Numeric)

	# For signatures/images
	image_url: Mapped[str | None] = mapped_column(String(500))

	# Confidence
	confidence: Mapped[float | None] = mapped_column(Float)
	needs_review: Mapped[bool] = mapped_column(Boolean, default=False)

	# Bounding box where found
	x: Mapped[float | None] = mapped_column(Float)
	y: Mapped[float | None] = mapped_column(Float)
	width: Mapped[float | None] = mapped_column(Float)
	height: Mapped[float | None] = mapped_column(Float)

	# Relationships
	extraction: Mapped["FormExtraction"] = relationship(
		"FormExtraction", back_populates="field_values"
	)


class Signature(Base):
	"""Signature library."""
	__tablename__ = "signatures"

	id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
	tenant_id: Mapped[UUID] = mapped_column(
		ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
	)

	# Owner
	user_id: Mapped[UUID | None] = mapped_column(
		ForeignKey("users.id", ondelete="SET NULL")
	)
	person_name: Mapped[str | None] = mapped_column(String(255))

	# Signature image
	image_url: Mapped[str] = mapped_column(String(500), nullable=False)
	thumbnail_url: Mapped[str | None] = mapped_column(String(500))

	# Source
	captured_from_document_id: Mapped[UUID | None] = mapped_column(
		ForeignKey("nodes.id", ondelete="SET NULL")
	)
	captured_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), default=utc_now, nullable=False
	)

	# Verification
	is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
	verified_by: Mapped[UUID | None] = mapped_column(
		ForeignKey("users.id", ondelete="SET NULL")
	)
	verified_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

	# Timestamps
	created_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), default=utc_now, nullable=False
	)

	__table_args__ = (
		Index("idx_signatures_tenant", "tenant_id"),
		Index("idx_signatures_user", "user_id"),
	)

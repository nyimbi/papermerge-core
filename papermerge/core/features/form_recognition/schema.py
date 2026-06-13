# (c) Copyright Datacraft, 2026
"""Form recognition Pydantic schemas."""
from uuid import UUID
from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, field_validator


class FieldCreate(BaseModel):
	"""Schema for creating a form field."""
	name: str
	type: str = "text"
	label: str | None = None
	page_number: int = 1
	bounding_box: dict | None = None
	# anchor_text is stored in ORM as expected_format
	anchor_text: str | None = None
	# regex_pattern is stored in ORM as validation_regex
	regex_pattern: str | None = None
	is_required: bool = False


class TemplateCreate(BaseModel):
	"""Schema for creating a form template."""
	name: str
	category: str
	fields: list[FieldCreate]
	is_multipage: bool = False
	page_count: int = 1


class TemplateUpdate(BaseModel):
	"""Schema for updating a form template."""
	name: str | None = None
	category: str | None = None
	description: str | None = None
	is_active: bool | None = None  # accepted but no-op (no ORM column)


class TemplateInfo(BaseModel):
	"""Basic template information.

	ORM FormTemplate has no is_multipage or is_active columns.
	is_multipage is derived from page_count > 1.
	is_active defaults to True (all stored templates are considered active).
	"""
	id: UUID
	name: str
	category: str | None = None
	page_count: int = 1
	created_at: datetime | None = None

	# Derived / virtual fields — not ORM columns
	is_multipage: bool = False
	is_active: bool = True

	model_config = ConfigDict(from_attributes=True)

	@field_validator("is_multipage", mode="before")
	@classmethod
	def derive_is_multipage(cls, v: Any) -> bool:
		# When constructed from ORM object, is_multipage is not an attribute.
		# The validator will be called with the default False — that's fine.
		# Callers that want the derived value should use from_orm_template().
		return bool(v)

	@classmethod
	def from_orm_template(cls, t: Any) -> "TemplateInfo":
		"""Construct from an ORM FormTemplate, deriving virtual fields."""
		return cls(
			id=t.id,
			name=t.name,
			category=t.category,
			page_count=t.page_count,
			created_at=t.created_at,
			is_multipage=t.page_count > 1,
			is_active=True,
		)


class FieldInfo(BaseModel):
	"""Form field information."""
	id: UUID
	name: str
	field_type: str
	label: str | None = None
	page_number: int | None = None
	# ORM column is `required`, not is_required
	is_required: bool = False

	model_config = ConfigDict(from_attributes=True, populate_by_name=True)

	@field_validator("is_required", mode="before")
	@classmethod
	def coerce_required(cls, v: Any) -> bool:
		return bool(v)


class TemplateDetail(BaseModel):
	"""Detailed template information."""
	id: UUID
	name: str
	category: str | None = None
	is_multipage: bool = False
	page_count: int = 1
	is_active: bool = True
	fields: list[FieldInfo] = []


class TemplateListResponse(BaseModel):
	"""Paginated template list."""
	items: list[TemplateInfo]
	total: int
	page: int
	page_size: int


class ExtractionRequest(BaseModel):
	"""Request to extract form data."""
	document_id: UUID
	template_id: UUID | None = None


class ExtractionResponse(BaseModel):
	"""Response from extraction request."""
	success: bool
	message: str | None = None
	document_id: UUID


class ExtractedFieldValue(BaseModel):
	"""Extracted field value.

	ORM uses typed columns (text_value, boolean_value, etc.) and needs_review.
	`value` is synthesised from the first non-None typed column.
	`was_corrected` is derived as not needs_review (i.e. a correction was applied).
	"""
	field_name: str
	value: Any | None = None
	confidence: float = 0.0
	# was_corrected maps to (not needs_review) — populated via from_orm_value()
	was_corrected: bool = False

	model_config = ConfigDict(from_attributes=True)

	@classmethod
	def from_orm_value(cls, v: Any) -> "ExtractedFieldValue":
		"""Construct from an ORM ExtractedFieldValue, picking the populated typed column."""
		value: Any = None
		for col in ("text_value", "number_value", "date_value", "boolean_value"):
			candidate = getattr(v, col, None)
			if candidate is not None:
				value = candidate
				break
		return cls(
			field_name=v.field_name,
			value=value,
			confidence=v.confidence or 0.0,
			was_corrected=not v.needs_review,
		)


class ExtractionResult(BaseModel):
	"""Form extraction result.

	ORM FormExtraction uses confidence_score (not confidence) and has no
	boolean `reviewed` — it has reviewed_at / reviewed_by timestamps.
	"""
	id: UUID
	document_id: UUID
	template_id: UUID | None = None
	# Populated from ORM confidence_score
	confidence: float = 0.0
	status: str
	# Derived: True when reviewed_at is set
	reviewed: bool = False
	field_values: list[ExtractedFieldValue] = []
	created_at: datetime | None = None

	model_config = ConfigDict(from_attributes=True)

	@field_validator("confidence", mode="before")
	@classmethod
	def coerce_confidence(cls, v: Any) -> float:
		return float(v) if v is not None else 0.0

	@field_validator("reviewed", mode="before")
	@classmethod
	def coerce_reviewed(cls, v: Any) -> bool:
		# ORM may pass reviewed_at (datetime) or None here; coerce to bool.
		if isinstance(v, bool):
			return v
		return v is not None

	@classmethod
	def from_orm_extraction(cls, e: Any, field_values: list) -> "ExtractionResult":
		"""Construct from ORM FormExtraction + pre-loaded field_values list."""
		return cls(
			id=e.id,
			document_id=e.document_id,
			template_id=e.template_id,
			confidence=e.confidence_score or 0.0,
			status=e.status,
			reviewed=e.reviewed_at is not None,
			field_values=[ExtractedFieldValue.from_orm_value(v) for v in field_values],
			created_at=e.created_at,
		)


class CorrectionRequest(BaseModel):
	"""Request to submit corrections."""
	corrections: dict[str, Any]


class SignatureInfo(BaseModel):
	"""Signature information.

	ORM Signature has: is_verified, person_name, image_url, user_id,
	captured_from_document_id, tenant_id.
	It does NOT have: page_number, bounding_box, signature_type, verified, signer_name.
	Virtual fields are provided with safe defaults for API compatibility.
	"""
	id: UUID
	# Derived from ORM is_verified
	verified: bool = False
	# ORM person_name
	signer_name: str | None = None
	# Not on ORM — default value for API compatibility
	signature_type: str = "unknown"
	# Not on ORM — None for API compatibility
	page_number: int | None = None
	bounding_box: dict | None = None

	model_config = ConfigDict(from_attributes=True)

	@field_validator("verified", mode="before")
	@classmethod
	def coerce_verified(cls, v: Any) -> bool:
		return bool(v)

	@classmethod
	def from_orm_signature(cls, s: Any) -> "SignatureInfo":
		"""Construct from ORM Signature, mapping is_verified -> verified, person_name -> signer_name."""
		return cls(
			id=s.id,
			verified=s.is_verified,
			signer_name=s.person_name,
			signature_type="unknown",
			page_number=None,
			bounding_box=None,
		)


class SignatureListResponse(BaseModel):
	"""Response with signatures."""
	signatures: list[SignatureInfo]

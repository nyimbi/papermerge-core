# (c) Copyright Datacraft, 2026
"""Form recognition Pydantic schemas."""
from uuid import UUID
from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict


class FieldCreate(BaseModel):
	"""Schema for creating a form field."""
	name: str
	type: str = "text"
	label: str | None = None
	page_number: int = 1
	bounding_box: dict | None = None
	anchor_text: str | None = None
	regex_pattern: str | None = None
	is_required: bool = False


class TemplateCreate(BaseModel):
	"""Schema for creating a form template."""
	name: str
	category: str
	fields: list[FieldCreate]
	is_multipage: bool = False
	page_count: int = 1


class TemplateInfo(BaseModel):
	"""Basic template information."""
	id: UUID
	name: str
	category: str
	is_multipage: bool
	page_count: int
	is_active: bool
	created_at: datetime | None = None

	model_config = ConfigDict(from_attributes=True)


class FieldInfo(BaseModel):
	"""Form field information."""
	id: UUID
	name: str
	field_type: str
	label: str | None = None
	page_number: int | None = None
	is_required: bool

	model_config = ConfigDict(from_attributes=True)


class TemplateDetail(BaseModel):
	"""Detailed template information."""
	id: UUID
	name: str
	category: str
	is_multipage: bool
	page_count: int
	is_active: bool
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
	"""Extracted field value."""
	field_name: str
	value: Any | None = None
	confidence: float
	was_corrected: bool = False

	model_config = ConfigDict(from_attributes=True)


class ExtractionResult(BaseModel):
	"""Form extraction result."""
	id: UUID
	document_id: UUID
	template_id: UUID | None = None
	confidence: float
	status: str
	reviewed: bool
	field_values: list[ExtractedFieldValue] = []
	created_at: datetime | None = None

	model_config = ConfigDict(from_attributes=True)


class CorrectionRequest(BaseModel):
	"""Request to submit corrections."""
	corrections: dict[str, Any]


class SignatureInfo(BaseModel):
	"""Signature information."""
	id: UUID
	page_number: int
	bounding_box: dict | None = None
	signature_type: str
	verified: bool
	signer_name: str | None = None

	model_config = ConfigDict(from_attributes=True)


class SignatureListResponse(BaseModel):
	"""Response with signatures."""
	signatures: list[SignatureInfo]

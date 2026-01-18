# Document Serial Number Views (Pydantic Schemas)
# GitHub Issue #132: Automatically assign document serial numbers after upload
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict, field_validator

from .models import ResetFrequency


class SerialNumberSequenceCreate(BaseModel):
	"""Create serial number sequence request."""
	model_config = ConfigDict(extra="forbid")

	name: str = Field(..., min_length=1, max_length=100)
	description: str | None = None
	pattern: str = Field(
		default="{PREFIX}-{YEAR}{MONTH}-{SEQ:5}",
		description="Pattern with placeholders: {YEAR}, {MONTH}, {DAY}, {SEQ}, {SEQ:N}, {PREFIX}, {DOCTYPE}"
	)
	prefix: str = Field(default="DOC", max_length=20)
	reset_frequency: str = Field(default=ResetFrequency.YEARLY.value)
	document_type_id: str | None = None
	auto_assign: bool = True
	allow_manual: bool = True

	@field_validator("reset_frequency")
	@classmethod
	def validate_reset_frequency(cls, v: str) -> str:
		valid = [f.value for f in ResetFrequency]
		if v not in valid:
			raise ValueError(f"Must be one of: {', '.join(valid)}")
		return v

	@field_validator("pattern")
	@classmethod
	def validate_pattern(cls, v: str) -> str:
		# Must contain {SEQ} somewhere
		if "{SEQ" not in v:
			raise ValueError("Pattern must contain {SEQ} or {SEQ:N} placeholder")
		return v


class SerialNumberSequenceUpdate(BaseModel):
	"""Update serial number sequence request."""
	model_config = ConfigDict(extra="forbid")

	name: str | None = None
	description: str | None = None
	pattern: str | None = None
	prefix: str | None = None
	reset_frequency: str | None = None
	is_active: bool | None = None
	auto_assign: bool | None = None
	allow_manual: bool | None = None


class SerialNumberSequenceOut(BaseModel):
	"""Serial number sequence response."""
	model_config = ConfigDict(from_attributes=True)

	id: str
	name: str
	description: str | None
	pattern: str
	prefix: str
	current_value: int
	reset_frequency: str
	last_reset_at: datetime | None
	document_type_id: str | None
	is_active: bool
	auto_assign: bool
	allow_manual: bool
	created_at: datetime
	updated_at: datetime | None

	# Preview of next serial number
	next_preview: str | None = None


class DocumentSerialNumberOut(BaseModel):
	"""Document serial number response."""
	model_config = ConfigDict(from_attributes=True)

	id: str
	document_id: str
	serial_number: str
	sequence_id: str | None
	sequence_value: int | None
	is_manual: bool
	assigned_at: datetime
	assigned_by_id: str | None


class ManualSerialAssignment(BaseModel):
	"""Manual serial number assignment request."""
	model_config = ConfigDict(extra="forbid")

	document_id: str
	serial_number: str = Field(..., min_length=1, max_length=100)


class SerialNumberSearch(BaseModel):
	"""Serial number search request."""
	query: str = Field(..., min_length=1)
	limit: int = Field(default=20, ge=1, le=100)


class SerialNumberBulkGenerate(BaseModel):
	"""Bulk generate serial numbers for documents."""
	document_ids: list[str] = Field(..., min_length=1, max_length=100)


class SerialPatternPreview(BaseModel):
	"""Preview what a pattern would generate."""
	pattern: str
	prefix: str = "DOC"
	document_type_name: str | None = None


class SerialPatternPreviewResult(BaseModel):
	"""Pattern preview result."""
	pattern: str
	preview: str
	placeholders_used: list[str]

# (c) Copyright Datacraft, 2026
"""Bundle Pydantic schemas."""
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator
from typing import Any


class BundleCreate(BaseModel):
	"""Schema for creating a bundle."""
	name: str
	description: str | None = None
	case_id: UUID | None = None
	bundle_type: str = "standard"


class BundleInfo(BaseModel):
	"""Basic bundle information."""
	id: UUID
	name: str = Field(validation_alias="title")
	description: str | None = None
	bundle_type: str = "standard"
	status: str
	case_id: UUID | None = None
	created_at: datetime | None = None

	model_config = ConfigDict(from_attributes=True, populate_by_name=True)

	@classmethod
	def model_validate(cls, obj: Any, **kwargs):
		"""Override to extract bundle_type from bundle_metadata."""
		# If obj has bundle_metadata attribute, extract bundle_type
		if hasattr(obj, "bundle_metadata") and obj.bundle_metadata:
			bundle_type = obj.bundle_metadata.get("bundle_type", "standard")
		else:
			bundle_type = "standard"
		# Create instance with extracted bundle_type
		return super().model_validate(obj, **kwargs).model_copy(update={"bundle_type": bundle_type})


class BundleDocumentInfo(BaseModel):
	"""Bundle document information."""
	id: UUID
	bundle_id: UUID
	document_id: UUID
	section_id: UUID | None = None
	position: int
	bundle_page_start: int | None = None
	bundle_page_end: int | None = None

	model_config = ConfigDict(from_attributes=True)


class BundleSectionInfo(BaseModel):
	"""Bundle section information."""
	id: UUID
	bundle_id: UUID
	name: str
	position: int

	model_config = ConfigDict(from_attributes=True)


class BundleDetail(BaseModel):
	"""Detailed bundle information."""
	id: UUID
	name: str
	description: str | None = None
	bundle_type: str
	status: str
	case_id: UUID | None = None
	documents: list[BundleDocumentInfo] = []
	sections: list[BundleSectionInfo] = []


class BundleListResponse(BaseModel):
	"""Paginated bundle list."""
	items: list[BundleInfo]
	total: int
	page: int
	page_size: int


class AddDocumentRequest(BaseModel):
	"""Request to add document to bundle."""
	document_id: UUID
	section_id: UUID | None = None
	include_in_pagination: bool = True


class BundleSectionCreate(BaseModel):
	"""Schema for creating a bundle section."""
	name: str


class PaginationResult(BaseModel):
	"""Result of bundle pagination."""
	total_pages: int
	document_count: int

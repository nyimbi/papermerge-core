# (c) Copyright Datacraft, 2026
"""Bundle Pydantic schemas."""
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class BundleCreate(BaseModel):
	"""Schema for creating a bundle."""
	name: str
	description: str | None = None
	case_id: UUID | None = None
	bundle_type: str = "standard"


class BundleInfo(BaseModel):
	"""Basic bundle information."""
	id: UUID
	name: str
	description: str | None = None
	bundle_type: str
	status: str
	case_id: UUID | None = None
	created_at: datetime | None = None

	model_config = ConfigDict(from_attributes=True)


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

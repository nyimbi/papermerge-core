# (c) Copyright Datacraft, 2026
"""Case Pydantic schemas."""
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class CaseCreate(BaseModel):
	"""Schema for creating a case."""
	case_number: str
	title: str
	description: str | None = None
	portfolio_id: UUID | None = None
	metadata: dict | None = None


class CaseUpdate(BaseModel):
	"""Schema for updating a case."""
	title: str | None = None
	description: str | None = None
	status: str | None = None
	metadata: dict | None = None


class CaseInfo(BaseModel):
	"""Basic case information."""
	id: UUID
	case_number: str
	title: str
	description: str | None = None
	status: str
	portfolio_id: UUID | None = None
	created_at: datetime | None = None

	model_config = ConfigDict(from_attributes=True)


class CaseDocumentInfo(BaseModel):
	"""Case document information."""
	id: UUID
	case_id: UUID
	document_id: UUID
	document_type: str | None = None
	added_at: datetime | None = None

	model_config = ConfigDict(from_attributes=True)


class CaseDetail(BaseModel):
	"""Detailed case information."""
	id: UUID
	case_number: str
	title: str
	description: str | None = None
	status: str
	portfolio_id: UUID | None = None
	metadata: dict | None = None
	documents: list[CaseDocumentInfo] = []
	created_at: datetime | None = None


class CaseListResponse(BaseModel):
	"""Paginated case list."""
	items: list[CaseInfo]
	total: int
	page: int
	page_size: int


class AddDocumentToCaseRequest(BaseModel):
	"""Request to add document to case."""
	document_id: UUID
	document_type: str | None = None


class GrantAccessRequest(BaseModel):
	"""Request to grant case access."""
	subject_type: str  # user, group, role
	subject_id: UUID
	allow_view: bool = True
	allow_download: bool = False
	allow_print: bool = False
	allow_edit: bool = False
	allow_share: bool = False
	valid_from: datetime | None = None
	valid_until: datetime | None = None


class CaseAccessInfo(BaseModel):
	"""Case access information."""
	id: UUID
	case_id: UUID
	subject_type: str
	subject_id: UUID
	allow_view: bool
	allow_download: bool
	allow_print: bool
	allow_edit: bool
	allow_share: bool
	valid_from: datetime | None = None
	valid_until: datetime | None = None

	model_config = ConfigDict(from_attributes=True)


class CaseAccessListResponse(BaseModel):
	"""Response with case access list."""
	items: list[CaseAccessInfo]

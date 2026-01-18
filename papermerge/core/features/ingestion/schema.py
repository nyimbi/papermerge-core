# (c) Copyright Datacraft, 2026
"""Ingestion Pydantic schemas."""
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class SourceCreate(BaseModel):
	"""Schema for creating an ingestion source."""
	name: str
	source_type: str  # watched_folder, email, api
	config: dict
	mode: str = "operational"  # operational, archival
	target_folder_id: UUID | None = None


class SourceInfo(BaseModel):
	"""Basic source information."""
	id: UUID
	name: str
	source_type: str
	mode: str
	is_active: bool
	created_at: datetime | None = None

	model_config = ConfigDict(from_attributes=True)


class SourceDetail(BaseModel):
	"""Detailed source information."""
	id: UUID
	name: str
	source_type: str
	config: dict
	mode: str
	target_folder_id: UUID | None = None
	is_active: bool
	last_check_at: datetime | None = None
	created_at: datetime | None = None

	model_config = ConfigDict(from_attributes=True)


class SourceListResponse(BaseModel):
	"""Paginated source list."""
	items: list[SourceInfo]
	total: int
	page: int
	page_size: int


class JobInfo(BaseModel):
	"""Basic job information."""
	id: UUID
	source_id: UUID | None = None
	source_type: str
	source_path: str
	status: str
	mode: str
	document_id: UUID | None = None
	error_message: str | None = None
	created_at: datetime | None = None

	model_config = ConfigDict(from_attributes=True)


class JobDetail(BaseModel):
	"""Detailed job information."""
	id: UUID
	source_id: UUID | None = None
	source_type: str
	source_path: str
	status: str
	mode: str
	document_id: UUID | None = None
	documents_processed: int | None = None
	error_message: str | None = None
	created_at: datetime | None = None
	completed_at: datetime | None = None

	model_config = ConfigDict(from_attributes=True)


class JobListResponse(BaseModel):
	"""Paginated job list."""
	items: list[JobInfo]
	total: int
	page: int
	page_size: int


class EmailAttachment(BaseModel):
	"""Email attachment information."""
	filename: str
	content_type: str
	content_base64: str  # Base64-encoded content


class EmailIngestionRequest(BaseModel):
	"""Request to ingest from email."""
	from_address: str
	to_address: str
	subject: str
	message_id: str | None = None
	date: str | None = None
	attachments: list[EmailAttachment]


class IngestionResponse(BaseModel):
	"""Response from ingestion request."""
	success: bool
	message: str | None = None
	job_id: UUID | None = None
	document_ids: list[UUID] | None = None

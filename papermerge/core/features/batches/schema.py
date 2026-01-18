# (c) Copyright Datacraft, 2026
"""
Pydantic schemas for batch tracking.
"""
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
from uuid import UUID

from .db.orm import BatchStatus, LocationType


# Source Location schemas
class SourceLocationBase(BaseModel):
	name: str = Field(..., min_length=1, max_length=255)
	code: str | None = Field(None, max_length=50)
	location_type: LocationType = LocationType.OTHER
	description: str | None = None
	parent_id: str | None = None
	address: str | None = None
	metadata: dict | None = None
	barcode: str | None = Field(None, max_length=100)
	is_active: bool = True


class SourceLocationCreate(SourceLocationBase):
	pass


class SourceLocationUpdate(BaseModel):
	name: str | None = Field(None, min_length=1, max_length=255)
	code: str | None = Field(None, max_length=50)
	location_type: LocationType | None = None
	description: str | None = None
	parent_id: str | None = None
	address: str | None = None
	metadata: dict | None = None
	barcode: str | None = Field(None, max_length=100)
	is_active: bool | None = None


class SourceLocation(SourceLocationBase):
	model_config = ConfigDict(from_attributes=True)

	id: str
	tenant_id: UUID | None = None
	created_at: datetime
	updated_at: datetime


class SourceLocationTree(SourceLocation):
	children: list["SourceLocationTree"] = []


# Scan Batch schemas
class ScanBatchBase(BaseModel):
	name: str | None = Field(None, max_length=255)
	description: str | None = None
	source_location_id: str | None = None
	scanner_id: str | None = None
	project_id: str | None = None
	box_label: str | None = Field(None, max_length=100)
	folder_label: str | None = Field(None, max_length=100)
	scan_settings: dict | None = None
	metadata: dict | None = None
	notes: str | None = None


class ScanBatchCreate(ScanBatchBase):
	batch_number: str | None = Field(None, max_length=50)


class ScanBatchUpdate(BaseModel):
	name: str | None = Field(None, max_length=255)
	description: str | None = None
	source_location_id: str | None = None
	scanner_id: str | None = None
	project_id: str | None = None
	status: BatchStatus | None = None
	box_label: str | None = Field(None, max_length=100)
	folder_label: str | None = Field(None, max_length=100)
	scan_settings: dict | None = None
	metadata: dict | None = None
	notes: str | None = None


class ScanBatchStats(BaseModel):
	total_documents: int = 0
	total_pages: int = 0
	processed_documents: int = 0
	processed_pages: int = 0
	failed_documents: int = 0
	average_quality_score: float | None = None
	documents_requiring_rescan: int = 0


class ScanBatch(ScanBatchBase):
	model_config = ConfigDict(from_attributes=True)

	id: str
	batch_number: str
	status: BatchStatus
	operator_id: UUID | None = None
	total_documents: int
	total_pages: int
	processed_documents: int
	processed_pages: int
	failed_documents: int
	average_quality_score: float | None
	documents_requiring_rescan: int
	started_at: datetime | None
	completed_at: datetime | None
	tenant_id: UUID | None = None
	created_at: datetime
	updated_at: datetime


class ScanBatchSummary(BaseModel):
	model_config = ConfigDict(from_attributes=True)

	id: str
	batch_number: str
	name: str | None
	status: BatchStatus
	total_documents: int
	total_pages: int
	processed_documents: int
	average_quality_score: float | None
	created_at: datetime


class ScanBatchWithLocation(ScanBatch):
	source_location: SourceLocation | None = None


# Batch statistics
class BatchDashboardStats(BaseModel):
	total_batches: int
	active_batches: int
	completed_batches: int
	total_documents_scanned: int
	total_pages_scanned: int
	documents_requiring_rescan: int
	average_quality_score: float | None
	batches_by_status: dict[str, int]
	recent_batches: list[ScanBatchSummary]

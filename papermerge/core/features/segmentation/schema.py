# (c) Copyright Datacraft, 2026
"""Pydantic schemas for document segmentation API."""
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict
from uuid import UUID


class SegmentationMethodEnum(str, Enum):
	"""Methods used for document boundary detection."""
	VLM = "vlm"
	EDGE_DETECTION = "edge_detection"
	CONTOUR = "contour"
	HYBRID = "hybrid"
	TEMPLATE = "template"
	MANUAL = "manual"


class SegmentStatusEnum(str, Enum):
	"""Status of a segmented document."""
	PENDING = "pending"
	APPROVED = "approved"
	REJECTED = "rejected"
	MERGED = "merged"
	SPLIT = "split"


class BoundarySchema(BaseModel):
	"""Document boundary coordinates."""
	x: int = Field(..., ge=0, description="Left edge in pixels")
	y: int = Field(..., ge=0, description="Top edge in pixels")
	width: int = Field(..., gt=0, description="Width in pixels")
	height: int = Field(..., gt=0, description="Height in pixels")

	model_config = ConfigDict(extra='forbid')


class SegmentationRequest(BaseModel):
	"""Request to segment a document scan."""
	document_id: str = Field(..., description="ID of document to segment")
	page_number: int | None = Field(
		None,
		ge=1,
		description="Specific page to segment (default: all pages)",
	)
	method: SegmentationMethodEnum = Field(
		SegmentationMethodEnum.HYBRID,
		description="Segmentation method to use",
	)
	auto_create_documents: bool = Field(
		False,
		description="Automatically create documents from segments",
	)
	min_confidence: float = Field(
		0.6,
		ge=0.0,
		le=1.0,
		description="Minimum confidence threshold for segment detection",
	)
	deskew: bool = Field(
		True,
		description="Auto-deskew extracted segments",
	)

	model_config = ConfigDict(extra='forbid')


class SegmentSchema(BaseModel):
	"""Schema for a document segment."""
	id: str
	original_scan_id: str
	original_page_number: int
	document_id: str | None
	segment_number: int
	total_segments: int
	boundary: BoundarySchema | None
	rotation_angle: float
	was_deskewed: bool
	segmentation_confidence: float
	segmentation_method: SegmentationMethodEnum
	status: SegmentStatusEnum
	manually_verified: bool
	verified_by_id: UUID | None
	verified_at: datetime | None
	document_type_hint: str | None
	segment_width: int | None
	segment_height: int | None
	needs_review: bool
	created_at: datetime
	updated_at: datetime

	model_config = ConfigDict(from_attributes=True)


class SegmentListResponse(BaseModel):
	"""Response containing list of segments."""
	items: list[SegmentSchema]
	total: int
	page: int = 1
	page_size: int = 50

	model_config = ConfigDict(extra='forbid')


class SegmentationJobSchema(BaseModel):
	"""Schema for a segmentation job."""
	id: str
	source_document_id: str
	source_page_number: int | None
	method: SegmentationMethodEnum
	auto_create_documents: bool
	min_confidence_threshold: float
	status: str
	error_message: str | None
	documents_detected: int
	segments_created: int
	processing_time_ms: float | None
	celery_task_id: str | None
	created_at: datetime
	started_at: datetime | None
	completed_at: datetime | None

	model_config = ConfigDict(from_attributes=True)


class SegmentationJobResponse(BaseModel):
	"""Response when starting a segmentation job."""
	job_id: str
	celery_task_id: str | None
	status: str
	message: str

	model_config = ConfigDict(extra='forbid')


class SegmentUpdateRequest(BaseModel):
	"""Request to update a segment."""
	status: SegmentStatusEnum | None = None
	boundary: BoundarySchema | None = None
	document_type_hint: str | None = None
	notes: str | None = None

	model_config = ConfigDict(extra='forbid')


class SegmentVerifyRequest(BaseModel):
	"""Request to verify/approve a segment."""
	approved: bool = Field(..., description="Whether the segment is approved")
	notes: str | None = Field(None, description="Review notes")

	model_config = ConfigDict(extra='forbid')


class SegmentCreateDocumentRequest(BaseModel):
	"""Request to create a document from a segment."""
	segment_id: str = Field(..., description="ID of segment to convert")
	folder_id: str = Field(..., description="Destination folder ID")
	title: str | None = Field(None, description="Document title (auto-generated if not provided)")
	document_type_id: str | None = Field(None, description="Document type to assign")
	tags: list[str] | None = Field(None, description="Tags to assign")

	model_config = ConfigDict(extra='forbid')


class SegmentMergeRequest(BaseModel):
	"""Request to merge multiple segments."""
	segment_ids: list[str] = Field(
		...,
		min_length=2,
		description="IDs of segments to merge",
	)
	primary_segment_id: str = Field(
		...,
		description="Segment to use as the base",
	)

	model_config = ConfigDict(extra='forbid')


class SegmentSplitRequest(BaseModel):
	"""Request to further split a segment."""
	segment_id: str = Field(..., description="ID of segment to split")
	split_boundaries: list[BoundarySchema] = Field(
		...,
		min_length=2,
		description="Boundaries for new segments",
	)

	model_config = ConfigDict(extra='forbid')


class SegmentationStatsSchema(BaseModel):
	"""Statistics about segmentation."""
	total_segments: int
	pending_review: int
	approved: int
	rejected: int
	avg_confidence: float
	documents_created: int
	multi_document_scans: int

	model_config = ConfigDict(extra='forbid')

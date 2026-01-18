# (c) Copyright Datacraft, 2026
"""Pydantic models for Scanning Projects feature."""
from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field, ConfigDict, AfterValidator
from uuid_extensions import uuid7str


def validate_positive(v: int) -> int:
	assert v >= 0, "Value must be non-negative"
	return v


PositiveInt = Annotated[int, AfterValidator(validate_positive)]


class ScanningProjectStatus(str, Enum):
	PLANNING = "planning"
	IN_PROGRESS = "in_progress"
	QUALITY_REVIEW = "quality_review"
	COMPLETED = "completed"
	ON_HOLD = "on_hold"


class ScanningBatchStatus(str, Enum):
	PENDING = "pending"
	SCANNING = "scanning"
	OCR_PROCESSING = "ocr_processing"
	QC_PENDING = "qc_pending"
	QC_PASSED = "qc_passed"
	QC_FAILED = "qc_failed"
	COMPLETED = "completed"


class ScanningBatchType(str, Enum):
	BOX = "box"
	FOLDER = "folder"
	VOLUME = "volume"


class ColorMode(str, Enum):
	BITONAL = "bitonal"
	GRAYSCALE = "grayscale"
	COLOR = "color"


class ResourceType(str, Enum):
	OPERATOR = "operator"
	SCANNER = "scanner"
	WORKSTATION = "workstation"


class ResourceStatus(str, Enum):
	AVAILABLE = "available"
	BUSY = "busy"
	MAINTENANCE = "maintenance"
	OFFLINE = "offline"


class QCReviewStatus(str, Enum):
	PENDING = "pending"
	PASSED = "passed"
	FAILED = "failed"
	NEEDS_RESCAN = "needs_rescan"


class MilestoneStatus(str, Enum):
	PENDING = "pending"
	IN_PROGRESS = "in_progress"
	COMPLETED = "completed"
	OVERDUE = "overdue"


class IssueSeverity(str, Enum):
	MINOR = "minor"
	MAJOR = "major"
	CRITICAL = "critical"


class IssueType(str, Enum):
	SKEW = "skew"
	BLUR = "blur"
	CUTOFF = "cutoff"
	DARK = "dark"
	LIGHT = "light"
	MISSING = "missing"
	DUPLICATE = "duplicate"
	OTHER = "other"


# =====================================================
# Scanning Project Models
# =====================================================


class ScanningProjectBase(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	name: str = Field(..., min_length=1, max_length=255)
	description: str | None = None
	total_estimated_pages: PositiveInt = 0
	target_dpi: int = Field(default=300, ge=100, le=1200)
	color_mode: ColorMode = ColorMode.GRAYSCALE
	quality_sample_rate: int = Field(default=5, ge=1, le=100)
	start_date: datetime | None = None
	target_end_date: datetime | None = None


class ScanningProjectCreate(ScanningProjectBase):
	pass


class ScanningProjectUpdate(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	name: str | None = None
	description: str | None = None
	status: ScanningProjectStatus | None = None
	total_estimated_pages: PositiveInt | None = None
	target_dpi: int | None = None
	color_mode: ColorMode | None = None
	quality_sample_rate: int | None = None
	start_date: datetime | None = None
	target_end_date: datetime | None = None


class ScanningProject(ScanningProjectBase):
	id: str = Field(default_factory=uuid7str)
	status: ScanningProjectStatus = ScanningProjectStatus.PLANNING
	scanned_pages: PositiveInt = 0
	verified_pages: PositiveInt = 0
	rejected_pages: PositiveInt = 0
	actual_end_date: datetime | None = None
	created_at: datetime = Field(default_factory=datetime.utcnow)
	updated_at: datetime = Field(default_factory=datetime.utcnow)


# =====================================================
# Batch Models
# =====================================================


class ScanningBatchBase(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	batch_number: str = Field(..., min_length=1, max_length=100)
	type: ScanningBatchType = ScanningBatchType.BOX
	physical_location: str = Field(..., min_length=1, max_length=255)
	barcode: str | None = None
	estimated_pages: PositiveInt = 0
	notes: str | None = None


class ScanningBatchCreate(ScanningBatchBase):
	pass


class ScanningBatchUpdate(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	batch_number: str | None = None
	type: ScanningBatchType | None = None
	physical_location: str | None = None
	barcode: str | None = None
	estimated_pages: PositiveInt | None = None
	actual_pages: PositiveInt | None = None
	status: ScanningBatchStatus | None = None
	assigned_operator_id: str | None = None
	assigned_scanner_id: str | None = None
	notes: str | None = None


class ScanningBatch(ScanningBatchBase):
	id: str = Field(default_factory=uuid7str)
	project_id: str
	actual_pages: PositiveInt = 0
	scanned_pages: PositiveInt = 0
	status: ScanningBatchStatus = ScanningBatchStatus.PENDING
	assigned_operator_id: str | None = None
	assigned_operator_name: str | None = None
	assigned_scanner_id: str | None = None
	assigned_scanner_name: str | None = None
	started_at: datetime | None = None
	completed_at: datetime | None = None
	created_at: datetime = Field(default_factory=datetime.utcnow)
	updated_at: datetime = Field(default_factory=datetime.utcnow)


# =====================================================
# Milestone Models
# =====================================================


class ScanningMilestoneBase(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	name: str = Field(..., min_length=1, max_length=255)
	description: str | None = None
	target_date: datetime
	target_pages: PositiveInt


class ScanningMilestoneCreate(ScanningMilestoneBase):
	pass


class ScanningMilestoneUpdate(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	name: str | None = None
	description: str | None = None
	target_date: datetime | None = None
	target_pages: PositiveInt | None = None
	status: MilestoneStatus | None = None


class ScanningMilestone(ScanningMilestoneBase):
	id: str = Field(default_factory=uuid7str)
	project_id: str
	actual_pages: PositiveInt = 0
	status: MilestoneStatus = MilestoneStatus.PENDING
	completed_at: datetime | None = None
	created_at: datetime = Field(default_factory=datetime.utcnow)


# =====================================================
# QC Models
# =====================================================


class QCIssue(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	id: str = Field(default_factory=uuid7str)
	type: IssueType
	description: str = ""
	severity: IssueSeverity = IssueSeverity.MINOR


class QualityControlSampleCreate(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	batch_id: str
	page_id: str
	page_number: PositiveInt


class QualityControlSampleUpdate(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	review_status: QCReviewStatus
	image_quality: int = Field(..., ge=0, le=100)
	ocr_accuracy: int | None = Field(default=None, ge=0, le=100)
	issues: list[QCIssue] = []
	notes: str | None = None


class QualityControlSample(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	id: str = Field(default_factory=uuid7str)
	batch_id: str
	page_id: str
	page_number: PositiveInt
	review_status: QCReviewStatus = QCReviewStatus.PENDING
	image_quality: int = Field(default=0, ge=0, le=100)
	ocr_accuracy: int | None = Field(default=None, ge=0, le=100)
	issues: list[QCIssue] = []
	reviewer_id: str | None = None
	reviewer_name: str | None = None
	reviewed_at: datetime | None = None
	notes: str | None = None
	created_at: datetime = Field(default_factory=datetime.utcnow)


# =====================================================
# Resource Models
# =====================================================


class ScanningResourceBase(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	type: ResourceType
	name: str = Field(..., min_length=1, max_length=255)
	description: str | None = None
	# Scanner-specific
	model: str | None = None
	max_dpi: int | None = None
	supports_color: bool | None = None
	supports_duplex: bool | None = None
	# Operator-specific
	user_id: str | None = None
	email: str | None = None
	# Workstation-specific
	location: str | None = None
	connected_scanner_id: str | None = None


class ScanningResourceCreate(ScanningResourceBase):
	pass


class ScanningResourceUpdate(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	name: str | None = None
	description: str | None = None
	status: ResourceStatus | None = None
	model: str | None = None
	max_dpi: int | None = None
	supports_color: bool | None = None
	supports_duplex: bool | None = None
	location: str | None = None
	connected_scanner_id: str | None = None


class ScanningResource(ScanningResourceBase):
	id: str = Field(default_factory=uuid7str)
	status: ResourceStatus = ResourceStatus.AVAILABLE
	created_at: datetime = Field(default_factory=datetime.utcnow)
	updated_at: datetime = Field(default_factory=datetime.utcnow)


# =====================================================
# Metrics Models
# =====================================================


class ScanningProjectMetrics(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	project_id: str
	total_batches: PositiveInt = 0
	completed_batches: PositiveInt = 0
	pending_batches: PositiveInt = 0
	in_progress_batches: PositiveInt = 0
	total_pages: PositiveInt = 0
	scanned_pages: PositiveInt = 0
	verified_pages: PositiveInt = 0
	rejected_pages: PositiveInt = 0
	average_pages_per_day: float = 0.0
	estimated_completion_date: datetime | None = None
	qc_pass_rate: float = 0.0
	avg_image_quality: float = 0.0
	avg_ocr_accuracy: float | None = None

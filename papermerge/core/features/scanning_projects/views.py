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


# =====================================================
# Phase Status
# =====================================================


class PhaseStatus(str, Enum):
	PENDING = "pending"
	IN_PROGRESS = "in_progress"
	COMPLETED = "completed"
	ON_HOLD = "on_hold"


class IssueStatus(str, Enum):
	OPEN = "open"
	IN_PROGRESS = "in_progress"
	RESOLVED = "resolved"
	CLOSED = "closed"


class ProjectIssueSeverity(str, Enum):
	LOW = "low"
	MEDIUM = "medium"
	HIGH = "high"
	CRITICAL = "critical"


class ProjectIssueType(str, Enum):
	EQUIPMENT = "equipment"
	QUALITY = "quality"
	STAFFING = "staffing"
	SCHEDULING = "scheduling"
	DOCUMENT = "document"
	OTHER = "other"


# =====================================================
# Project Phase Models
# =====================================================


class ProjectPhaseBase(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	name: str = Field(..., min_length=1, max_length=255)
	description: str | None = None
	sequence_order: int = 0
	estimated_pages: PositiveInt = 0
	start_date: datetime | None = None
	end_date: datetime | None = None


class ProjectPhaseCreate(ProjectPhaseBase):
	pass


class ProjectPhaseUpdate(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	name: str | None = None
	description: str | None = None
	sequence_order: int | None = None
	status: PhaseStatus | None = None
	estimated_pages: PositiveInt | None = None
	scanned_pages: PositiveInt | None = None
	start_date: datetime | None = None
	end_date: datetime | None = None


class ProjectPhase(ProjectPhaseBase):
	id: str = Field(default_factory=uuid7str)
	project_id: str
	status: PhaseStatus = PhaseStatus.PENDING
	scanned_pages: PositiveInt = 0
	created_at: datetime = Field(default_factory=datetime.utcnow)
	updated_at: datetime = Field(default_factory=datetime.utcnow)


# =====================================================
# Scanning Session Models
# =====================================================


class ScanningSessionBase(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	operator_id: str
	operator_name: str | None = None
	scanner_id: str | None = None
	scanner_name: str | None = None
	batch_id: str | None = None
	notes: str | None = None


class ScanningSessionCreate(ScanningSessionBase):
	pass


class ScanningSessionEnd(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	documents_scanned: PositiveInt = 0
	pages_scanned: PositiveInt = 0
	pages_rejected: PositiveInt = 0
	notes: str | None = None


class ScanningSession(ScanningSessionBase):
	id: str = Field(default_factory=uuid7str)
	project_id: str
	started_at: datetime = Field(default_factory=datetime.utcnow)
	ended_at: datetime | None = None
	documents_scanned: PositiveInt = 0
	pages_scanned: PositiveInt = 0
	pages_rejected: PositiveInt = 0
	average_pages_per_hour: float = 0.0


# =====================================================
# Progress Snapshot Models
# =====================================================


class ProgressSnapshot(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	id: str = Field(default_factory=uuid7str)
	project_id: str
	snapshot_time: datetime = Field(default_factory=datetime.utcnow)
	total_pages_scanned: PositiveInt = 0
	pages_verified: PositiveInt = 0
	pages_rejected: PositiveInt = 0
	pages_per_hour: float = 0.0
	active_operators: PositiveInt = 0
	active_scanners: PositiveInt = 0
	average_quality_score: float | None = None


# =====================================================
# Daily Metrics Models
# =====================================================


class DailyProjectMetrics(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	id: str = Field(default_factory=uuid7str)
	project_id: str
	metric_date: datetime
	pages_scanned: PositiveInt = 0
	pages_verified: PositiveInt = 0
	pages_rejected: PositiveInt = 0
	documents_completed: PositiveInt = 0
	batches_completed: PositiveInt = 0
	operator_count: PositiveInt = 0
	scanner_count: PositiveInt = 0
	total_session_hours: float = 0.0
	average_quality_score: float | None = None
	issues_found: PositiveInt = 0
	issues_resolved: PositiveInt = 0


class OperatorDailyMetrics(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	id: str = Field(default_factory=uuid7str)
	project_id: str
	operator_id: str
	operator_name: str | None = None
	metric_date: datetime
	pages_scanned: PositiveInt = 0
	pages_verified: PositiveInt = 0
	pages_rejected: PositiveInt = 0
	documents_completed: PositiveInt = 0
	session_hours: float = 0.0
	pages_per_hour: float = 0.0
	quality_score: float | None = None
	issues_caused: PositiveInt = 0


# =====================================================
# Project Issue Models
# =====================================================


class ProjectIssueBase(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	title: str = Field(..., min_length=1, max_length=255)
	description: str | None = None
	issue_type: ProjectIssueType
	severity: ProjectIssueSeverity = ProjectIssueSeverity.MEDIUM
	batch_id: str | None = None


class ProjectIssueCreate(ProjectIssueBase):
	pass


class ProjectIssueUpdate(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	title: str | None = None
	description: str | None = None
	issue_type: ProjectIssueType | None = None
	severity: ProjectIssueSeverity | None = None
	status: IssueStatus | None = None
	assigned_to_id: str | None = None
	assigned_to_name: str | None = None
	resolution: str | None = None


class ProjectIssue(ProjectIssueBase):
	id: str = Field(default_factory=uuid7str)
	project_id: str
	status: IssueStatus = IssueStatus.OPEN
	reported_by_id: str | None = None
	reported_by_name: str | None = None
	assigned_to_id: str | None = None
	assigned_to_name: str | None = None
	resolution: str | None = None
	created_at: datetime = Field(default_factory=datetime.utcnow)
	updated_at: datetime = Field(default_factory=datetime.utcnow)
	resolved_at: datetime | None = None


# =====================================================
# AI Advisor Models
# =====================================================


class RiskLevel(str, Enum):
	LOW = "low"
	MEDIUM = "medium"
	HIGH = "high"
	CRITICAL = "critical"


class RecommendationType(str, Enum):
	RESOURCE_ALLOCATION = "resource_allocation"
	SCHEDULING = "scheduling"
	QUALITY_IMPROVEMENT = "quality_improvement"
	RISK_MITIGATION = "risk_mitigation"
	EFFICIENCY = "efficiency"


class AIRecommendation(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	id: str = Field(default_factory=uuid7str)
	type: RecommendationType
	title: str
	description: str
	priority: int = Field(default=5, ge=1, le=10)
	risk_level: RiskLevel = RiskLevel.LOW
	estimated_impact: str | None = None
	action_items: list[str] = []
	created_at: datetime = Field(default_factory=datetime.utcnow)


class ProjectRiskAssessment(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	project_id: str
	overall_risk_level: RiskLevel
	schedule_risk: RiskLevel
	quality_risk: RiskLevel
	resource_risk: RiskLevel
	risk_factors: list[str] = []
	mitigation_suggestions: list[str] = []
	confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
	assessed_at: datetime = Field(default_factory=datetime.utcnow)


class ScheduleForecast(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	project_id: str
	target_date: datetime
	predicted_completion_date: datetime
	on_track: bool
	days_ahead_or_behind: int
	confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
	bottlenecks: list[str] = []
	recommendations: list[str] = []
	forecasted_at: datetime = Field(default_factory=datetime.utcnow)


class ResourceOptimization(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	project_id: str
	current_efficiency: float
	optimal_operator_count: int
	optimal_scanner_count: int
	suggested_schedule_changes: list[str] = []
	underutilized_resources: list[str] = []
	overloaded_resources: list[str] = []
	estimated_efficiency_gain: float
	analyzed_at: datetime = Field(default_factory=datetime.utcnow)


class AIAdvisorResponse(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	project_id: str
	risk_assessment: ProjectRiskAssessment
	schedule_forecast: ScheduleForecast
	resource_optimization: ResourceOptimization
	recommendations: list[AIRecommendation]
	summary: str
	generated_at: datetime = Field(default_factory=datetime.utcnow)


# =====================================================
# Enterprise-Scale Extensions for Million-Document Digitization
# =====================================================


class SubProjectStatus(str, Enum):
	PLANNING = "planning"
	READY = "ready"
	IN_PROGRESS = "in_progress"
	PAUSED = "paused"
	COMPLETED = "completed"
	CANCELLED = "cancelled"


class SLAStatus(str, Enum):
	ON_TRACK = "on_track"
	AT_RISK = "at_risk"
	BREACHED = "breached"


class SLAType(str, Enum):
	COMPLETION = "completion"
	QUALITY = "quality"
	TURNAROUND = "turnaround"
	THROUGHPUT = "throughput"


class MaintenanceType(str, Enum):
	PREVENTIVE = "preventive"
	CORRECTIVE = "corrective"
	CALIBRATION = "calibration"
	CLEANING = "cleaning"


class MaintenanceStatus(str, Enum):
	SCHEDULED = "scheduled"
	IN_PROGRESS = "in_progress"
	COMPLETED = "completed"
	CANCELLED = "cancelled"
	OVERDUE = "overdue"


class CertificationLevel(str, Enum):
	BASIC = "basic"
	INTERMEDIATE = "intermediate"
	ADVANCED = "advanced"
	EXPERT = "expert"


class ContractType(str, Enum):
	FIXED_PRICE = "fixed_price"
	PER_PAGE = "per_page"
	TIME_AND_MATERIALS = "time_and_materials"
	HYBRID = "hybrid"


class CostType(str, Enum):
	LABOR = "labor"
	EQUIPMENT = "equipment"
	MATERIALS = "materials"
	STORAGE = "storage"
	OTHER = "other"


class CheckpointType(str, Enum):
	PROGRESS = "progress"
	QUALITY = "quality"
	DELIVERY = "delivery"
	REVIEW = "review"


class CheckpointStatus(str, Enum):
	PENDING = "pending"
	PASSED = "passed"
	FAILED = "failed"
	WAIVED = "waived"


# =====================================================
# Sub-Project Schemas
# =====================================================


class SubProjectBase(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	code: str = Field(..., min_length=1, max_length=50)
	name: str = Field(..., min_length=1, max_length=255)
	description: str | None = None
	category: str | None = None
	priority: int = Field(default=5, ge=1, le=10)
	total_estimated_pages: PositiveInt = 0
	assigned_location_id: str | None = None
	start_date: datetime | None = None
	target_end_date: datetime | None = None


class SubProjectCreate(SubProjectBase):
	pass


class SubProjectUpdate(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	code: str | None = None
	name: str | None = None
	description: str | None = None
	category: str | None = None
	status: SubProjectStatus | None = None
	priority: int | None = None
	total_estimated_pages: PositiveInt | None = None
	assigned_location_id: str | None = None
	start_date: datetime | None = None
	target_end_date: datetime | None = None


class SubProject(SubProjectBase):
	id: str = Field(default_factory=uuid7str)
	parent_project_id: str
	status: SubProjectStatus = SubProjectStatus.PLANNING
	scanned_pages: PositiveInt = 0
	verified_pages: PositiveInt = 0
	rejected_pages: PositiveInt = 0
	actual_end_date: datetime | None = None
	created_at: datetime = Field(default_factory=datetime.utcnow)
	updated_at: datetime = Field(default_factory=datetime.utcnow)


# =====================================================
# Location Schemas
# =====================================================


class ScanningLocationBase(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	code: str = Field(..., min_length=1, max_length=50)
	name: str = Field(..., min_length=1, max_length=255)
	address: str | None = None
	city: str | None = None
	country: str | None = None
	timezone: str = "UTC"
	scanner_capacity: int = Field(default=1, ge=1)
	operator_capacity: int = Field(default=2, ge=1)
	daily_page_capacity: int = Field(default=5000, ge=100)
	contact_name: str | None = None
	contact_email: str | None = None
	contact_phone: str | None = None
	notes: str | None = None


class ScanningLocationCreate(ScanningLocationBase):
	pass


class ScanningLocationUpdate(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	code: str | None = None
	name: str | None = None
	address: str | None = None
	city: str | None = None
	country: str | None = None
	timezone: str | None = None
	is_active: bool | None = None
	scanner_capacity: int | None = None
	operator_capacity: int | None = None
	daily_page_capacity: int | None = None
	contact_name: str | None = None
	contact_email: str | None = None
	contact_phone: str | None = None
	notes: str | None = None


class ScanningLocation(ScanningLocationBase):
	id: str = Field(default_factory=uuid7str)
	is_active: bool = True
	created_at: datetime = Field(default_factory=datetime.utcnow)
	updated_at: datetime = Field(default_factory=datetime.utcnow)


# =====================================================
# Shift Schemas
# =====================================================


class ShiftBase(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	name: str = Field(..., min_length=1, max_length=100)
	location_id: str | None = None
	start_time: str = Field(..., pattern=r"^\d{2}:\d{2}$")  # HH:MM
	end_time: str = Field(..., pattern=r"^\d{2}:\d{2}$")
	days_of_week: str = "1,2,3,4,5"  # 1=Mon, 7=Sun
	target_pages_per_operator: int = Field(default=500, ge=1)
	break_minutes: int = Field(default=60, ge=0)


class ShiftCreate(ShiftBase):
	pass


class ShiftUpdate(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	name: str | None = None
	location_id: str | None = None
	start_time: str | None = None
	end_time: str | None = None
	days_of_week: str | None = None
	target_pages_per_operator: int | None = None
	break_minutes: int | None = None
	is_active: bool | None = None


class Shift(ShiftBase):
	id: str = Field(default_factory=uuid7str)
	is_active: bool = True
	created_at: datetime = Field(default_factory=datetime.utcnow)


class ShiftAssignmentBase(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	shift_id: str
	operator_id: str
	operator_name: str | None = None
	project_id: str | None = None
	assignment_date: datetime


class ShiftAssignmentCreate(ShiftAssignmentBase):
	pass


class ShiftAssignment(ShiftAssignmentBase):
	id: str = Field(default_factory=uuid7str)
	status: str = "scheduled"
	actual_start: datetime | None = None
	actual_end: datetime | None = None
	pages_scanned: PositiveInt = 0
	notes: str | None = None


# =====================================================
# Cost Tracking Schemas
# =====================================================


class ProjectCostBase(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	cost_date: datetime
	cost_type: CostType
	category: str | None = None
	description: str | None = None
	quantity: float = 1.0
	unit_cost: float = Field(default=0.0, ge=0.0)
	currency: str = "USD"
	operator_id: str | None = None
	location_id: str | None = None
	batch_id: str | None = None
	notes: str | None = None


class ProjectCostCreate(ProjectCostBase):
	pass


class ProjectCost(ProjectCostBase):
	id: str = Field(default_factory=uuid7str)
	project_id: str
	total_cost: float = 0.0
	created_at: datetime = Field(default_factory=datetime.utcnow)


class ProjectBudgetBase(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	budget_name: str = Field(..., min_length=1, max_length=255)
	total_budget: float = Field(default=0.0, ge=0.0)
	labor_budget: float = Field(default=0.0, ge=0.0)
	equipment_budget: float = Field(default=0.0, ge=0.0)
	materials_budget: float = Field(default=0.0, ge=0.0)
	storage_budget: float = Field(default=0.0, ge=0.0)
	other_budget: float = Field(default=0.0, ge=0.0)
	contingency_budget: float = Field(default=0.0, ge=0.0)
	currency: str = "USD"
	target_cost_per_page: float | None = None


class ProjectBudgetCreate(ProjectBudgetBase):
	pass


class ProjectBudgetUpdate(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	budget_name: str | None = None
	total_budget: float | None = None
	labor_budget: float | None = None
	equipment_budget: float | None = None
	materials_budget: float | None = None
	storage_budget: float | None = None
	other_budget: float | None = None
	contingency_budget: float | None = None
	currency: str | None = None
	target_cost_per_page: float | None = None
	is_approved: bool | None = None


class ProjectBudget(ProjectBudgetBase):
	id: str = Field(default_factory=uuid7str)
	project_id: str
	spent_to_date: float = 0.0
	cost_per_page: float | None = None
	is_approved: bool = False
	approved_by_id: str | None = None
	approved_at: datetime | None = None
	created_at: datetime = Field(default_factory=datetime.utcnow)
	updated_at: datetime = Field(default_factory=datetime.utcnow)


class CostSummary(BaseModel):
	"""Summary of project costs."""
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	project_id: str
	total_spent: float = 0.0
	labor_spent: float = 0.0
	equipment_spent: float = 0.0
	materials_spent: float = 0.0
	storage_spent: float = 0.0
	other_spent: float = 0.0
	budget_remaining: float = 0.0
	budget_utilization_percent: float = 0.0
	cost_per_page: float = 0.0
	projected_total_cost: float = 0.0
	currency: str = "USD"


# =====================================================
# SLA Schemas
# =====================================================


class SLABase(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	name: str = Field(..., min_length=1, max_length=255)
	description: str | None = None
	sla_type: SLAType
	target_value: float
	target_unit: str  # percent, days, hours, pages
	threshold_warning: float | None = None
	threshold_critical: float | None = None
	penalty_amount: float | None = None
	penalty_currency: str = "USD"
	start_date: datetime
	end_date: datetime


class SLACreate(SLABase):
	pass


class SLAUpdate(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	name: str | None = None
	description: str | None = None
	target_value: float | None = None
	threshold_warning: float | None = None
	threshold_critical: float | None = None
	penalty_amount: float | None = None
	end_date: datetime | None = None


class SLA(SLABase):
	id: str = Field(default_factory=uuid7str)
	project_id: str
	current_value: float = 0.0
	status: SLAStatus = SLAStatus.ON_TRACK
	last_checked_at: datetime | None = None
	breached_at: datetime | None = None
	created_at: datetime = Field(default_factory=datetime.utcnow)


class SLAAlert(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	id: str = Field(default_factory=uuid7str)
	sla_id: str
	alert_type: str  # warning, critical, breach
	alert_time: datetime = Field(default_factory=datetime.utcnow)
	message: str
	current_value: float
	target_value: float
	acknowledged_by_id: str | None = None
	acknowledged_at: datetime | None = None
	resolution_notes: str | None = None


# =====================================================
# Equipment Maintenance Schemas
# =====================================================


class EquipmentMaintenanceBase(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	resource_id: str
	maintenance_type: MaintenanceType
	title: str = Field(..., min_length=1, max_length=255)
	description: str | None = None
	scheduled_date: datetime
	priority: int = Field(default=5, ge=1, le=10)
	estimated_downtime_hours: float = Field(default=1.0, ge=0.0)
	technician_name: str | None = None
	notes: str | None = None


class EquipmentMaintenanceCreate(EquipmentMaintenanceBase):
	pass


class EquipmentMaintenanceUpdate(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	maintenance_type: MaintenanceType | None = None
	title: str | None = None
	description: str | None = None
	scheduled_date: datetime | None = None
	status: MaintenanceStatus | None = None
	priority: int | None = None
	estimated_downtime_hours: float | None = None
	actual_downtime_hours: float | None = None
	technician_name: str | None = None
	cost: float | None = None
	parts_replaced: str | None = None
	notes: str | None = None
	next_maintenance_date: datetime | None = None


class EquipmentMaintenance(EquipmentMaintenanceBase):
	id: str = Field(default_factory=uuid7str)
	status: MaintenanceStatus = MaintenanceStatus.SCHEDULED
	completed_date: datetime | None = None
	actual_downtime_hours: float | None = None
	cost: float = 0.0
	parts_replaced: str | None = None
	next_maintenance_date: datetime | None = None
	created_at: datetime = Field(default_factory=datetime.utcnow)


# =====================================================
# Operator Certification Schemas
# =====================================================


class OperatorCertificationBase(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	operator_id: str
	operator_name: str | None = None
	certification_type: str  # scanner_model, document_type, qc_reviewer
	certification_name: str = Field(..., min_length=1, max_length=255)
	level: CertificationLevel = CertificationLevel.BASIC
	issued_date: datetime
	expiry_date: datetime | None = None
	issued_by: str | None = None
	score: float | None = None
	notes: str | None = None


class OperatorCertificationCreate(OperatorCertificationBase):
	pass


class OperatorCertificationUpdate(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	level: CertificationLevel | None = None
	expiry_date: datetime | None = None
	is_active: bool | None = None
	notes: str | None = None


class OperatorCertification(OperatorCertificationBase):
	id: str = Field(default_factory=uuid7str)
	is_active: bool = True
	created_at: datetime = Field(default_factory=datetime.utcnow)


# =====================================================
# Capacity Planning Schemas
# =====================================================


class CapacityPlanBase(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	plan_name: str = Field(..., min_length=1, max_length=255)
	target_completion_date: datetime
	assumptions: str | None = None


class CapacityPlanCreate(CapacityPlanBase):
	pass


class CapacityPlan(CapacityPlanBase):
	id: str = Field(default_factory=uuid7str)
	project_id: str
	plan_date: datetime = Field(default_factory=datetime.utcnow)
	total_pages_remaining: PositiveInt = 0
	working_days_remaining: PositiveInt = 0
	required_pages_per_day: PositiveInt = 0
	current_daily_capacity: PositiveInt = 0
	capacity_gap: int = 0  # Negative = over capacity
	recommended_operators: PositiveInt = 0
	recommended_scanners: PositiveInt = 0
	recommended_shifts_per_day: int = 1
	confidence_score: float = 0.7
	recommendations: str | None = None
	created_by_id: str | None = None
	is_approved: bool = False
	created_at: datetime = Field(default_factory=datetime.utcnow)


# =====================================================
# Document Type Distribution Schemas
# =====================================================


class DocumentTypeDistributionBase(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	document_type: str = Field(..., min_length=1, max_length=100)
	document_type_name: str = Field(..., min_length=1, max_length=255)
	estimated_count: PositiveInt = 0
	estimated_pages: PositiveInt = 0
	avg_pages_per_document: float = 1.0
	requires_special_handling: bool = False
	special_handling_notes: str | None = None
	priority: int = Field(default=5, ge=1, le=10)


class DocumentTypeDistributionCreate(DocumentTypeDistributionBase):
	pass


class DocumentTypeDistributionUpdate(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	document_type_name: str | None = None
	estimated_count: PositiveInt | None = None
	actual_count: PositiveInt | None = None
	estimated_pages: PositiveInt | None = None
	actual_pages: PositiveInt | None = None
	avg_pages_per_document: float | None = None
	requires_special_handling: bool | None = None
	special_handling_notes: str | None = None
	priority: int | None = None


class DocumentTypeDistribution(DocumentTypeDistributionBase):
	id: str = Field(default_factory=uuid7str)
	project_id: str
	actual_count: PositiveInt = 0
	actual_pages: PositiveInt = 0
	assigned_operator_ids: str | None = None
	created_at: datetime = Field(default_factory=datetime.utcnow)
	updated_at: datetime = Field(default_factory=datetime.utcnow)


# =====================================================
# Priority Queue Schemas
# =====================================================


class BatchPriorityBase(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	batch_id: str
	priority: int = Field(default=5, ge=1, le=10)
	priority_reason: str | None = None
	due_date: datetime | None = None
	is_rush: bool = False


class BatchPriorityCreate(BatchPriorityBase):
	rush_approved_by_id: str | None = None


class BatchPriorityUpdate(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	priority: int | None = None
	priority_reason: str | None = None
	due_date: datetime | None = None
	is_rush: bool | None = None
	rush_approved_by_id: str | None = None


class BatchPriority(BatchPriorityBase):
	id: str = Field(default_factory=uuid7str)
	rush_approved_by_id: str | None = None
	rush_approved_at: datetime | None = None
	estimated_completion: datetime | None = None
	actual_completion: datetime | None = None
	queue_position: int | None = None
	created_at: datetime = Field(default_factory=datetime.utcnow)
	updated_at: datetime = Field(default_factory=datetime.utcnow)


# =====================================================
# Contract Schemas
# =====================================================


class ProjectContractBase(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	contract_number: str = Field(..., min_length=1, max_length=100)
	client_name: str = Field(..., min_length=1, max_length=255)
	client_contact_name: str | None = None
	client_contact_email: str | None = None
	contract_type: ContractType
	contract_value: float = Field(default=0.0, ge=0.0)
	currency: str = "USD"
	price_per_page: float | None = None
	minimum_pages: int | None = None
	maximum_pages: int | None = None
	payment_terms: str | None = None
	start_date: datetime
	end_date: datetime
	deliverables: str | None = None
	special_requirements: str | None = None


class ProjectContractCreate(ProjectContractBase):
	pass


class ProjectContractUpdate(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	contract_number: str | None = None
	client_name: str | None = None
	client_contact_name: str | None = None
	client_contact_email: str | None = None
	contract_value: float | None = None
	price_per_page: float | None = None
	payment_terms: str | None = None
	end_date: datetime | None = None
	deliverables: str | None = None
	special_requirements: str | None = None
	status: str | None = None


class ProjectContract(ProjectContractBase):
	id: str = Field(default_factory=uuid7str)
	project_id: str
	status: str = "active"
	created_at: datetime = Field(default_factory=datetime.utcnow)
	updated_at: datetime = Field(default_factory=datetime.utcnow)


# =====================================================
# Workload Forecast Schemas
# =====================================================


class WorkloadForecast(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	id: str = Field(default_factory=uuid7str)
	project_id: str
	forecast_date: datetime = Field(default_factory=datetime.utcnow)
	forecast_period_start: datetime
	forecast_period_end: datetime
	predicted_pages: PositiveInt = 0
	predicted_operators_needed: PositiveInt = 0
	predicted_scanners_needed: PositiveInt = 0
	confidence_score: float = 0.7
	model_used: str | None = None
	actual_pages: int | None = None
	accuracy: float | None = None
	created_at: datetime = Field(default_factory=datetime.utcnow)


# =====================================================
# Checkpoint Schemas
# =====================================================


class ProjectCheckpointBase(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	checkpoint_number: int = Field(..., ge=1)
	name: str = Field(..., min_length=1, max_length=255)
	description: str | None = None
	checkpoint_type: CheckpointType
	target_date: datetime
	target_percentage: float = Field(..., ge=0.0, le=100.0)
	pass_criteria: str | None = None


class ProjectCheckpointCreate(ProjectCheckpointBase):
	pass


class ProjectCheckpointUpdate(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	name: str | None = None
	description: str | None = None
	target_date: datetime | None = None
	target_percentage: float | None = None
	status: CheckpointStatus | None = None
	pass_criteria: str | None = None
	review_notes: str | None = None


class ProjectCheckpoint(ProjectCheckpointBase):
	id: str = Field(default_factory=uuid7str)
	project_id: str
	actual_date: datetime | None = None
	actual_percentage: float | None = None
	status: CheckpointStatus = CheckpointStatus.PENDING
	review_notes: str | None = None
	reviewed_by_id: str | None = None
	reviewed_by_name: str | None = None
	reviewed_at: datetime | None = None
	created_at: datetime = Field(default_factory=datetime.utcnow)


# =====================================================
# Bulk Operations Schemas
# =====================================================


class BulkBatchImport(BaseModel):
	"""Schema for bulk importing batches."""
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	batches: list[ScanningBatchCreate]
	auto_generate_numbers: bool = False
	number_prefix: str | None = None
	starting_number: int = 1


class BulkBatchUpdate(BaseModel):
	"""Schema for bulk updating batches."""
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	batch_ids: list[str]
	status: ScanningBatchStatus | None = None
	assigned_operator_id: str | None = None
	assigned_scanner_id: str | None = None
	priority: int | None = None


class BulkOperationResult(BaseModel):
	"""Result of a bulk operation."""
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	success_count: int = 0
	failure_count: int = 0
	total_count: int = 0
	failed_ids: list[str] = []
	errors: list[str] = []


# =====================================================
# Dashboard and Analytics Schemas
# =====================================================


class ProjectDashboard(BaseModel):
	"""Comprehensive project dashboard data."""
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	project_id: str
	project_name: str
	status: ScanningProjectStatus

	# Overall progress
	total_estimated_pages: int = 0
	scanned_pages: int = 0
	verified_pages: int = 0
	rejected_pages: int = 0
	completion_percentage: float = 0.0

	# Today's progress
	pages_scanned_today: int = 0
	pages_target_today: int = 0
	target_variance: int = 0  # Positive = ahead, negative = behind

	# Active resources
	active_operators: int = 0
	active_scanners: int = 0
	current_shift: str | None = None

	# Batch status
	batches_pending: int = 0
	batches_in_progress: int = 0
	batches_completed: int = 0
	batches_in_qc: int = 0

	# Quality
	qc_pass_rate: float = 0.0
	avg_quality_score: float = 0.0
	pending_qc_reviews: int = 0

	# SLA status
	sla_on_track: int = 0
	sla_at_risk: int = 0
	sla_breached: int = 0

	# Open issues
	critical_issues: int = 0
	high_issues: int = 0
	open_issues_total: int = 0

	# Schedule
	days_remaining: int | None = None
	projected_completion_date: datetime | None = None
	on_schedule: bool = True

	# Cost
	budget_spent: float = 0.0
	budget_remaining: float = 0.0
	cost_per_page: float = 0.0

	generated_at: datetime = Field(default_factory=datetime.utcnow)


class BurndownDataPoint(BaseModel):
	"""Data point for burndown chart."""
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	date: datetime
	pages_remaining: int
	ideal_remaining: int
	velocity: float  # Pages per day


class BurndownChart(BaseModel):
	"""Burndown chart data for project."""
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	project_id: str
	start_date: datetime
	target_end_date: datetime
	total_pages: int
	data_points: list[BurndownDataPoint]
	projected_completion_date: datetime | None = None
	is_on_track: bool = True


class VelocityDataPoint(BaseModel):
	"""Data point for velocity chart."""
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	date: datetime
	pages_scanned: int
	operators_active: int
	pages_per_operator: float


class VelocityChart(BaseModel):
	"""Velocity chart data."""
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	project_id: str
	period_start: datetime
	period_end: datetime
	data_points: list[VelocityDataPoint]
	average_velocity: float
	velocity_trend: float  # Positive = improving


class LocationMetrics(BaseModel):
	"""Metrics for a scanning location."""
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	location_id: str
	location_name: str
	total_pages_scanned: int = 0
	pages_today: int = 0
	active_operators: int = 0
	active_scanners: int = 0
	capacity_utilization: float = 0.0
	avg_quality_score: float = 0.0
	avg_pages_per_hour: float = 0.0


class MultiLocationDashboard(BaseModel):
	"""Dashboard for multi-location operations."""
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	project_id: str
	locations: list[LocationMetrics]
	total_active_locations: int = 0
	total_capacity: int = 0
	utilized_capacity: int = 0
	overall_utilization: float = 0.0
	generated_at: datetime = Field(default_factory=datetime.utcnow)

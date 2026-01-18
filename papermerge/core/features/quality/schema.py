# (c) Copyright Datacraft, 2026
"""Quality Pydantic schemas."""
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class QualityRuleCreate(BaseModel):
	"""Schema for creating a quality rule."""
	name: str
	description: str | None = None
	metric: str
	operator: str  # eq, neq, gt, gte, lt, lte, between, not_between
	threshold: float
	threshold_upper: float | None = None
	severity: str = "warning"  # info, warning, error, critical
	action: str = "flag"  # log, flag, quarantine, reject, notify, auto_fix
	message_template: str | None = None
	priority: int = 100
	document_type_id: UUID | None = None
	applies_to_all: bool = True


class QualityRuleUpdate(BaseModel):
	"""Schema for updating a quality rule."""
	name: str | None = None
	description: str | None = None
	metric: str | None = None
	operator: str | None = None
	threshold: float | None = None
	threshold_upper: float | None = None
	severity: str | None = None
	action: str | None = None
	message_template: str | None = None
	priority: int | None = None
	is_active: bool | None = None


class QualityRuleInfo(BaseModel):
	"""Quality rule information."""
	id: UUID
	name: str
	description: str | None = None
	metric: str
	operator: str
	threshold: float
	threshold_upper: float | None = None
	severity: str
	action: str
	priority: int
	is_active: bool
	document_type_id: UUID | None = None
	applies_to_all: bool
	created_at: datetime | None = None

	model_config = ConfigDict(from_attributes=True)


class QualityRuleListResponse(BaseModel):
	"""Paginated rule list."""
	items: list[QualityRuleInfo]
	total: int


class QualityIssueInfo(BaseModel):
	"""Quality issue information."""
	metric: str
	actual_value: float
	expected_value: float | None = None
	severity: str
	message: str
	page_number: int | None = None
	auto_fixable: bool = False


class QualityMetricsInfo(BaseModel):
	"""Quality metrics for display."""
	resolution_dpi: int | None = None
	skew_angle: float | None = None
	brightness: float | None = None
	contrast: float | None = None
	sharpness: float | None = None
	noise_level: float | None = None
	blur_score: float | None = None
	ocr_confidence: float | None = None
	is_blank: bool | None = None
	orientation: int | None = None
	width_px: int | None = None
	height_px: int | None = None
	file_size_bytes: int | None = None


class QualityAssessmentInfo(BaseModel):
	"""Quality assessment result."""
	id: UUID
	document_id: UUID
	page_number: int | None = None
	quality_score: float
	passed: bool
	grade: str  # excellent, good, acceptable, poor, unacceptable
	metrics: QualityMetricsInfo
	issues: list[QualityIssueInfo]
	issue_count: int
	critical_issues: int
	assessed_at: datetime
	assessed_by: str | None = None

	model_config = ConfigDict(from_attributes=True)


class QualityAssessmentListResponse(BaseModel):
	"""Paginated assessment list."""
	items: list[QualityAssessmentInfo]
	total: int
	page: int
	page_size: int


class AssessDocumentRequest(BaseModel):
	"""Request to assess document quality."""
	document_id: UUID
	force_reassess: bool = False


class AssessDocumentResponse(BaseModel):
	"""Response from document assessment."""
	document_id: UUID
	overall_score: float
	overall_passed: bool
	page_count: int
	assessments: list[QualityAssessmentInfo]


class QualityIssueUpdateRequest(BaseModel):
	"""Request to update a quality issue."""
	status: str  # open, acknowledged, resolved, ignored, auto_fixed
	resolution_notes: str | None = None


class QualityIssueDetail(BaseModel):
	"""Detailed quality issue information."""
	id: UUID
	assessment_id: UUID
	document_id: UUID
	page_number: int | None = None
	rule_id: UUID | None = None
	metric: str
	actual_value: float
	expected_value: float | None = None
	severity: str
	message: str
	status: str
	resolved_at: datetime | None = None
	resolved_by: UUID | None = None
	resolution_notes: str | None = None
	auto_fix_applied: bool
	auto_fix_result: str | None = None
	created_at: datetime

	model_config = ConfigDict(from_attributes=True)


class QualityStatsInfo(BaseModel):
	"""Quality statistics for dashboard."""
	total_assessments: int
	passed_count: int
	failed_count: int
	pass_rate: float
	avg_quality_score: float
	issues_by_severity: dict[str, int]
	issues_by_metric: dict[str, int]
	trend_7d: list[dict]  # Daily stats for last 7 days


# VLM-based quality assessment schemas
class VLMAssessmentRequest(BaseModel):
	"""Request for VLM-powered quality assessment."""
	model_config = ConfigDict(extra="forbid")

	image_path: str | None = None
	image_base64: str | None = None
	mime_type: str | None = None
	include_traditional: bool = True
	ollama_base_url: str | None = None
	model: str | None = None  # e.g., "qwen2.5-vl:7b" or "qwen3-vl"


class VLMIssue(BaseModel):
	"""VLM-detected quality issue."""
	type: str  # skew, blur, dark, bright, noise, cutoff, artifact, smudge, other
	severity: str  # info, warning, error, critical
	description: str
	location: str  # top, bottom, left, right, center, all
	auto_fixable: bool = False


class VLMAssessmentResponse(BaseModel):
	"""Response from VLM-powered quality assessment."""
	model_config = ConfigDict(extra="ignore")

	# Document analysis
	document_type: str | None = None
	overall_quality_score: float | None = None
	quality_grade: str | None = None

	# Detailed scores
	readability_score: int | None = None
	scan_quality_score: int | None = None
	alignment_score: int | None = None
	content_integrity_score: int | None = None

	# Detections
	is_blank: bool = False
	has_handwriting: bool = False
	has_stamps_or_signatures: bool = False
	language_detected: str | None = None

	# Issues and recommendations
	issues: list[dict] = []
	recommendations: list[str] = []
	summary: str = ""

	# Traditional metrics (if include_traditional=True)
	traditional_metrics: dict | None = None
	blended_score: float | None = None

	# Metadata
	assessment_method: str = "vlm"
	model: str | None = None

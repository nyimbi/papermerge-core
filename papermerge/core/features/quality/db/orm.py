# (c) Copyright Datacraft, 2026
"""Quality ORM models."""
import uuid
from datetime import datetime
from uuid import UUID
from enum import Enum

from sqlalchemy import String, ForeignKey, Integer, Boolean, Text, Float, func, Index
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import TIMESTAMP, JSONB, ARRAY

from papermerge.core.db.base import Base
from papermerge.core.utils.tz import utc_now


class QualityMetricType(str, Enum):
	"""Types of quality metrics."""
	RESOLUTION_DPI = "resolution_dpi"
	SKEW_ANGLE = "skew_angle"
	BRIGHTNESS = "brightness"
	CONTRAST = "contrast"
	SHARPNESS = "sharpness"
	NOISE_LEVEL = "noise_level"
	BLUR_SCORE = "blur_score"
	OCR_CONFIDENCE = "ocr_confidence"
	PAGE_ORIENTATION = "page_orientation"
	BORDER_DETECTION = "border_detection"
	BLANK_PAGE = "blank_page"
	FILE_SIZE_KB = "file_size_kb"


class RuleOperator(str, Enum):
	"""Comparison operators for rules."""
	EQUALS = "eq"
	NOT_EQUALS = "neq"
	GREATER_THAN = "gt"
	GREATER_EQUAL = "gte"
	LESS_THAN = "lt"
	LESS_EQUAL = "lte"
	BETWEEN = "between"
	NOT_BETWEEN = "not_between"


class RuleSeverity(str, Enum):
	"""Severity levels for quality issues."""
	INFO = "info"
	WARNING = "warning"
	ERROR = "error"
	CRITICAL = "critical"


class RuleAction(str, Enum):
	"""Actions to take when rule is triggered."""
	LOG = "log"
	FLAG = "flag"
	QUARANTINE = "quarantine"
	REJECT = "reject"
	NOTIFY = "notify"
	AUTO_FIX = "auto_fix"


class IssueStatus(str, Enum):
	"""Status of a quality issue."""
	OPEN = "open"
	ACKNOWLEDGED = "acknowledged"
	RESOLVED = "resolved"
	IGNORED = "ignored"
	AUTO_FIXED = "auto_fixed"


class QualityRule(Base):
	"""Quality rule definition."""
	__tablename__ = "quality_rules"

	id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
	tenant_id: Mapped[UUID] = mapped_column(
		ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
	)

	# Rule identity
	name: Mapped[str] = mapped_column(String(255), nullable=False)
	description: Mapped[str | None] = mapped_column(Text)
	is_active: Mapped[bool] = mapped_column(Boolean, default=True)

	# Scope
	document_type_id: Mapped[UUID | None] = mapped_column(
		ForeignKey("document_types.id", ondelete="SET NULL")
	)
	applies_to_all: Mapped[bool] = mapped_column(Boolean, default=True)

	# Rule definition
	metric: Mapped[str] = mapped_column(String(50), nullable=False)  # QualityMetricType
	operator: Mapped[str] = mapped_column(String(20), nullable=False)  # RuleOperator
	threshold: Mapped[float] = mapped_column(Float, nullable=False)
	threshold_upper: Mapped[float | None] = mapped_column(Float)  # For BETWEEN

	# Response
	severity: Mapped[str] = mapped_column(String(20), default=RuleSeverity.WARNING.value)
	action: Mapped[str] = mapped_column(String(20), default=RuleAction.FLAG.value)
	message_template: Mapped[str | None] = mapped_column(Text)

	# Priority (lower = higher priority)
	priority: Mapped[int] = mapped_column(Integer, default=100)

	# Timestamps
	created_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), default=utc_now, nullable=False
	)
	updated_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), default=utc_now, onupdate=func.now(), nullable=False
	)

	__table_args__ = (
		Index("idx_quality_rules_tenant_active", "tenant_id", "is_active"),
		Index("idx_quality_rules_metric", "metric"),
	)


class QualityAssessment(Base):
	"""Quality assessment for a document or page."""
	__tablename__ = "quality_assessments"

	id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
	document_id: Mapped[UUID] = mapped_column(
		ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False, index=True
	)
	page_number: Mapped[int | None] = mapped_column(Integer)  # NULL for whole document

	# Overall score
	quality_score: Mapped[float] = mapped_column(Float, nullable=False)  # 0-100
	passed: Mapped[bool] = mapped_column(Boolean, default=True)

	# Individual metrics
	resolution_dpi: Mapped[int | None] = mapped_column(Integer)
	skew_angle: Mapped[float | None] = mapped_column(Float)  # Degrees
	brightness: Mapped[float | None] = mapped_column(Float)  # 0-255
	contrast: Mapped[float | None] = mapped_column(Float)  # 0-1
	sharpness: Mapped[float | None] = mapped_column(Float)  # 0-1
	noise_level: Mapped[float | None] = mapped_column(Float)  # 0-1
	blur_score: Mapped[float | None] = mapped_column(Float)  # 0-1 (higher = more blur)
	ocr_confidence: Mapped[float | None] = mapped_column(Float)  # 0-1
	is_blank: Mapped[bool | None] = mapped_column(Boolean)
	orientation: Mapped[int | None] = mapped_column(Integer)  # 0, 90, 180, 270

	# File metrics
	file_size_bytes: Mapped[int | None] = mapped_column(Integer)
	width_px: Mapped[int | None] = mapped_column(Integer)
	height_px: Mapped[int | None] = mapped_column(Integer)

	# Issues summary
	issue_count: Mapped[int] = mapped_column(Integer, default=0)
	critical_issues: Mapped[int] = mapped_column(Integer, default=0)

	# Processing info
	assessed_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), default=utc_now, nullable=False
	)
	assessed_by: Mapped[str | None] = mapped_column(String(100))  # User or "system"
	assessment_version: Mapped[str] = mapped_column(String(20), default="1.0")

	# Raw metrics (for debugging/analysis)
	raw_metrics: Mapped[dict | None] = mapped_column(JSONB)

	__table_args__ = (
		Index("idx_assessment_document", "document_id"),
		Index("idx_assessment_score", "quality_score"),
		Index("idx_assessment_passed", "passed"),
	)


class QualityIssueRecord(Base):
	"""Individual quality issue found during assessment."""
	__tablename__ = "quality_issues"

	id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
	assessment_id: Mapped[UUID] = mapped_column(
		ForeignKey("quality_assessments.id", ondelete="CASCADE"), nullable=False, index=True
	)
	document_id: Mapped[UUID] = mapped_column(
		ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False, index=True
	)
	page_number: Mapped[int | None] = mapped_column(Integer)

	# Issue details
	rule_id: Mapped[UUID | None] = mapped_column(
		ForeignKey("quality_rules.id", ondelete="SET NULL")
	)
	metric: Mapped[str] = mapped_column(String(50), nullable=False)
	actual_value: Mapped[float] = mapped_column(Float, nullable=False)
	expected_value: Mapped[float | None] = mapped_column(Float)
	severity: Mapped[str] = mapped_column(String(20), nullable=False)
	message: Mapped[str] = mapped_column(Text, nullable=False)

	# Status
	status: Mapped[str] = mapped_column(String(20), default=IssueStatus.OPEN.value)
	resolved_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
	resolved_by: Mapped[UUID | None] = mapped_column(
		ForeignKey("users.id", ondelete="SET NULL")
	)
	resolution_notes: Mapped[str | None] = mapped_column(Text)

	# Auto-fix
	auto_fix_applied: Mapped[bool] = mapped_column(Boolean, default=False)
	auto_fix_result: Mapped[str | None] = mapped_column(Text)

	# Timestamps
	created_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), default=utc_now, nullable=False
	)

	__table_args__ = (
		Index("idx_issue_assessment", "assessment_id"),
		Index("idx_issue_document", "document_id"),
		Index("idx_issue_status", "status"),
		Index("idx_issue_severity", "severity"),
	)

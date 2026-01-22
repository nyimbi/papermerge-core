# (c) Copyright Datacraft, 2026
"""SQLAlchemy models for Scanning Projects feature."""
from datetime import datetime
from uuid import UUID

from sqlalchemy import String, Integer, Float, Boolean, DateTime, ForeignKey, Enum, JSON
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from papermerge.core.db.base import Base
from .views import (
	ScanningProjectStatus,
	ScanningBatchStatus,
	ScanningBatchType,
	ColorMode,
	ResourceType,
	ResourceStatus,
	MilestoneStatus,
	QCReviewStatus,
)


class ScanningProjectModel(Base):
	"""Model matching the actual database schema from d4rc migrations."""
	__tablename__ = "scanning_projects"

	id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
	tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
	code: Mapped[str] = mapped_column(String(50))
	name: Mapped[str] = mapped_column(String(255))
	description: Mapped[str | None] = mapped_column(String(2000))
	status: Mapped[str] = mapped_column(String(30), default="planning")
	priority: Mapped[str | None] = mapped_column(String(20), default="normal")
	project_type: Mapped[str | None] = mapped_column(String(50))
	client_name: Mapped[str | None] = mapped_column(String(255))
	client_reference: Mapped[str | None] = mapped_column(String(100))
	start_date: Mapped[datetime | None] = mapped_column(DateTime)
	target_end_date: Mapped[datetime | None] = mapped_column(DateTime)
	actual_end_date: Mapped[datetime | None] = mapped_column(DateTime)
	estimated_pages: Mapped[int | None] = mapped_column(Integer)
	estimated_documents: Mapped[int | None] = mapped_column(Integer)
	daily_page_target: Mapped[int | None] = mapped_column(Integer)
	target_dpi: Mapped[int] = mapped_column(Integer, default=300)
	color_mode: Mapped[str | None] = mapped_column(String(20), default="color")
	duplex_mode: Mapped[str | None] = mapped_column(String(20), default="duplex")
	file_format: Mapped[str | None] = mapped_column(String(20), default="pdf")
	ocr_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
	quality_sampling_rate: Mapped[float | None] = mapped_column(Float, default=0.1)
	destination_folder_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("nodes.id", ondelete="SET NULL"))
	project_metadata: Mapped[dict | None] = mapped_column("metadata", JSON)
	created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
	updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
	deleted_at: Mapped[datetime | None] = mapped_column(DateTime)
	created_by: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"))
	updated_by: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"))


class ScanningBatchModel(Base):
	__tablename__ = "scanning_batches"

	id: Mapped[str] = mapped_column(String(36), primary_key=True)
	project_id: Mapped[str] = mapped_column(
		String(36),
		ForeignKey("scanning_projects.id", ondelete="CASCADE"),
		index=True,
	)
	batch_number: Mapped[str] = mapped_column(String(100))
	type: Mapped[ScanningBatchType] = mapped_column(
		Enum(ScanningBatchType),
		default=ScanningBatchType.BOX,
	)
	physical_location: Mapped[str] = mapped_column(String(255))
	barcode: Mapped[str | None] = mapped_column(String(100))
	estimated_pages: Mapped[int] = mapped_column(Integer, default=0)
	actual_pages: Mapped[int] = mapped_column(Integer, default=0)
	scanned_pages: Mapped[int] = mapped_column(Integer, default=0)
	status: Mapped[ScanningBatchStatus] = mapped_column(
		Enum(ScanningBatchStatus),
		default=ScanningBatchStatus.PENDING,
	)
	assigned_operator_id: Mapped[str | None] = mapped_column(String(36))
	assigned_operator_name: Mapped[str | None] = mapped_column(String(255))
	assigned_scanner_id: Mapped[str | None] = mapped_column(String(36))
	assigned_scanner_name: Mapped[str | None] = mapped_column(String(255))
	notes: Mapped[str | None] = mapped_column(String(1000))
	started_at: Mapped[datetime | None] = mapped_column(DateTime)
	completed_at: Mapped[datetime | None] = mapped_column(DateTime)
	created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
	updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

	# project: Mapped["ScanningProjectModel"] = relationship(back_populates="batches")
	qc_samples: Mapped[list["QualityControlSampleModel"]] = relationship(
		back_populates="batch",
		cascade="all, delete-orphan",
	)


class ScanningMilestoneModel(Base):
	__tablename__ = "scanning_milestones"

	id: Mapped[str] = mapped_column(String(36), primary_key=True)
	project_id: Mapped[str] = mapped_column(
		String(36),
		ForeignKey("scanning_projects.id", ondelete="CASCADE"),
		index=True,
	)
	name: Mapped[str] = mapped_column(String(255))
	description: Mapped[str | None] = mapped_column(String(1000))
	target_date: Mapped[datetime] = mapped_column(DateTime)
	target_pages: Mapped[int] = mapped_column(Integer, default=0)
	actual_pages: Mapped[int] = mapped_column(Integer, default=0)
	status: Mapped[MilestoneStatus] = mapped_column(
		Enum(MilestoneStatus),
		default=MilestoneStatus.PENDING,
	)
	completed_at: Mapped[datetime | None] = mapped_column(DateTime)
	created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

	# project: Mapped["ScanningProjectModel"] = relationship(back_populates="milestones")


class QualityControlSampleModel(Base):
	__tablename__ = "qc_samples"

	id: Mapped[str] = mapped_column(String(36), primary_key=True)
	batch_id: Mapped[str] = mapped_column(
		String(36),
		ForeignKey("scanning_batches.id", ondelete="CASCADE"),
		index=True,
	)
	page_id: Mapped[str] = mapped_column(String(36))
	page_number: Mapped[int] = mapped_column(Integer)
	review_status: Mapped[QCReviewStatus] = mapped_column(
		Enum(QCReviewStatus),
		default=QCReviewStatus.PENDING,
	)
	image_quality: Mapped[int] = mapped_column(Integer, default=0)
	ocr_accuracy: Mapped[int | None] = mapped_column(Integer)
	issues: Mapped[list] = mapped_column(JSON, default=list)
	reviewer_id: Mapped[str | None] = mapped_column(String(36))
	reviewer_name: Mapped[str | None] = mapped_column(String(255))
	reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
	notes: Mapped[str | None] = mapped_column(String(1000))
	created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

	batch: Mapped["ScanningBatchModel"] = relationship(back_populates="qc_samples")


class ScanningResourceModel(Base):
	__tablename__ = "scanning_resources"

	id: Mapped[str] = mapped_column(String(36), primary_key=True)
	tenant_id: Mapped[str] = mapped_column(String(36), index=True)
	type: Mapped[ResourceType] = mapped_column(Enum(ResourceType))
	name: Mapped[str] = mapped_column(String(255))
	description: Mapped[str | None] = mapped_column(String(1000))
	status: Mapped[ResourceStatus] = mapped_column(
		Enum(ResourceStatus),
		default=ResourceStatus.AVAILABLE,
	)
	# Scanner-specific
	model: Mapped[str | None] = mapped_column(String(255))
	max_dpi: Mapped[int | None] = mapped_column(Integer)
	supports_color: Mapped[bool | None] = mapped_column(Boolean)
	supports_duplex: Mapped[bool | None] = mapped_column(Boolean)
	# Operator-specific
	user_id: Mapped[str | None] = mapped_column(String(36))
	email: Mapped[str | None] = mapped_column(String(255))
	# Workstation-specific
	location: Mapped[str | None] = mapped_column(String(255))
	connected_scanner_id: Mapped[str | None] = mapped_column(String(36))
	created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
	updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ProjectPhaseModel(Base):
	"""Project phases for tracking scanning stages."""
	__tablename__ = "project_phases"

	id: Mapped[str] = mapped_column(String(36), primary_key=True)
	project_id: Mapped[str] = mapped_column(
		String(36),
		ForeignKey("scanning_projects.id", ondelete="CASCADE"),
		index=True,
	)
	name: Mapped[str] = mapped_column(String(255))
	description: Mapped[str | None] = mapped_column(String(1000))
	sequence_order: Mapped[int] = mapped_column(Integer, default=0)
	status: Mapped[str] = mapped_column(String(50), default="pending")
	estimated_pages: Mapped[int] = mapped_column(Integer, default=0)
	scanned_pages: Mapped[int] = mapped_column(Integer, default=0)
	start_date: Mapped[datetime | None] = mapped_column(DateTime)
	end_date: Mapped[datetime | None] = mapped_column(DateTime)
	created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
	updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ScanningSesssionModel(Base):
	"""Individual scanning session tracking."""
	__tablename__ = "scanning_sessions"

	id: Mapped[str] = mapped_column(String(36), primary_key=True)
	project_id: Mapped[str] = mapped_column(
		String(36),
		ForeignKey("scanning_projects.id", ondelete="CASCADE"),
		index=True,
	)
	batch_id: Mapped[str | None] = mapped_column(
		String(36),
		ForeignKey("scanning_batches.id", ondelete="SET NULL"),
	)
	operator_id: Mapped[str] = mapped_column(String(36), index=True)
	operator_name: Mapped[str | None] = mapped_column(String(255))
	scanner_id: Mapped[str | None] = mapped_column(String(36))
	scanner_name: Mapped[str | None] = mapped_column(String(255))
	started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
	ended_at: Mapped[datetime | None] = mapped_column(DateTime)
	documents_scanned: Mapped[int] = mapped_column(Integer, default=0)
	pages_scanned: Mapped[int] = mapped_column(Integer, default=0)
	pages_rejected: Mapped[int] = mapped_column(Integer, default=0)
	average_pages_per_hour: Mapped[float] = mapped_column(Float, default=0.0)
	notes: Mapped[str | None] = mapped_column(String(1000))


class ProgressSnapshotModel(Base):
	"""Progress snapshots for trend analysis."""
	__tablename__ = "progress_snapshots"

	id: Mapped[str] = mapped_column(String(36), primary_key=True)
	project_id: Mapped[str] = mapped_column(
		String(36),
		ForeignKey("scanning_projects.id", ondelete="CASCADE"),
		index=True,
	)
	snapshot_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
	total_pages_scanned: Mapped[int] = mapped_column(Integer, default=0)
	pages_verified: Mapped[int] = mapped_column(Integer, default=0)
	pages_rejected: Mapped[int] = mapped_column(Integer, default=0)
	pages_per_hour: Mapped[float] = mapped_column(Float, default=0.0)
	active_operators: Mapped[int] = mapped_column(Integer, default=0)
	active_scanners: Mapped[int] = mapped_column(Integer, default=0)
	average_quality_score: Mapped[float | None] = mapped_column(Float)


class DailyProjectMetricsModel(Base):
	"""Daily aggregated project metrics."""
	__tablename__ = "daily_project_metrics"

	id: Mapped[str] = mapped_column(String(36), primary_key=True)
	project_id: Mapped[str] = mapped_column(
		String(36),
		ForeignKey("scanning_projects.id", ondelete="CASCADE"),
		index=True,
	)
	metric_date: Mapped[datetime] = mapped_column(DateTime, index=True)
	pages_scanned: Mapped[int] = mapped_column(Integer, default=0)
	pages_verified: Mapped[int] = mapped_column(Integer, default=0)
	pages_rejected: Mapped[int] = mapped_column(Integer, default=0)
	documents_completed: Mapped[int] = mapped_column(Integer, default=0)
	batches_completed: Mapped[int] = mapped_column(Integer, default=0)
	operator_count: Mapped[int] = mapped_column(Integer, default=0)
	scanner_count: Mapped[int] = mapped_column(Integer, default=0)
	total_session_hours: Mapped[float] = mapped_column(Float, default=0.0)
	average_quality_score: Mapped[float | None] = mapped_column(Float)
	issues_found: Mapped[int] = mapped_column(Integer, default=0)
	issues_resolved: Mapped[int] = mapped_column(Integer, default=0)


class OperatorDailyMetricsModel(Base):
	"""Daily metrics per operator."""
	__tablename__ = "operator_daily_metrics"

	id: Mapped[str] = mapped_column(String(36), primary_key=True)
	project_id: Mapped[str] = mapped_column(
		String(36),
		ForeignKey("scanning_projects.id", ondelete="CASCADE"),
		index=True,
	)
	operator_id: Mapped[str] = mapped_column(String(36), index=True)
	operator_name: Mapped[str | None] = mapped_column(String(255))
	metric_date: Mapped[datetime] = mapped_column(DateTime, index=True)
	pages_scanned: Mapped[int] = mapped_column(Integer, default=0)
	pages_verified: Mapped[int] = mapped_column(Integer, default=0)
	pages_rejected: Mapped[int] = mapped_column(Integer, default=0)
	documents_completed: Mapped[int] = mapped_column(Integer, default=0)
	session_hours: Mapped[float] = mapped_column(Float, default=0.0)
	pages_per_hour: Mapped[float] = mapped_column(Float, default=0.0)
	quality_score: Mapped[float | None] = mapped_column(Float)
	issues_caused: Mapped[int] = mapped_column(Integer, default=0)


class ProjectIssueModel(Base):
	"""Project-level issues and problems."""
	__tablename__ = "project_issues"

	id: Mapped[str] = mapped_column(String(36), primary_key=True)
	project_id: Mapped[str] = mapped_column(
		String(36),
		ForeignKey("scanning_projects.id", ondelete="CASCADE"),
		index=True,
	)
	batch_id: Mapped[str | None] = mapped_column(String(36))
	title: Mapped[str] = mapped_column(String(255))
	description: Mapped[str | None] = mapped_column(String(2000))
	issue_type: Mapped[str] = mapped_column(String(50))
	severity: Mapped[str] = mapped_column(String(50), default="minor")
	status: Mapped[str] = mapped_column(String(50), default="open")
	reported_by_id: Mapped[str | None] = mapped_column(String(36))
	reported_by_name: Mapped[str | None] = mapped_column(String(255))
	assigned_to_id: Mapped[str | None] = mapped_column(String(36))
	assigned_to_name: Mapped[str | None] = mapped_column(String(255))
	resolution: Mapped[str | None] = mapped_column(String(2000))
	created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
	updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
	resolved_at: Mapped[datetime | None] = mapped_column(DateTime)


# =====================================================
# Enterprise-Scale Extensions for Million-Document Digitization
# =====================================================


class SubProjectModel(Base):
	"""
	Hierarchical sub-projects for organizing massive digitization projects.
	Allows breaking down projects with millions of documents into
	manageable sub-projects by department, document type, or timeframe.
	"""
	__tablename__ = "sub_projects"

	id: Mapped[str] = mapped_column(String(36), primary_key=True)
	parent_project_id: Mapped[str] = mapped_column(
		String(36),
		ForeignKey("scanning_projects.id", ondelete="CASCADE"),
		index=True,
	)
	code: Mapped[str] = mapped_column(String(50), index=True)  # e.g., "PROJ-2026-HR-001"
	name: Mapped[str] = mapped_column(String(255))
	description: Mapped[str | None] = mapped_column(String(2000))
	category: Mapped[str | None] = mapped_column(String(100))  # e.g., "HR Records", "Financial", "Legal"
	status: Mapped[str] = mapped_column(String(50), default="planning")
	priority: Mapped[int] = mapped_column(Integer, default=5)  # 1-10, 10 = highest
	total_estimated_pages: Mapped[int] = mapped_column(Integer, default=0)
	scanned_pages: Mapped[int] = mapped_column(Integer, default=0)
	verified_pages: Mapped[int] = mapped_column(Integer, default=0)
	rejected_pages: Mapped[int] = mapped_column(Integer, default=0)
	assigned_location_id: Mapped[str | None] = mapped_column(String(36))
	start_date: Mapped[datetime | None] = mapped_column(DateTime)
	target_end_date: Mapped[datetime | None] = mapped_column(DateTime)
	actual_end_date: Mapped[datetime | None] = mapped_column(DateTime)
	created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
	updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ScanningLocationModel(Base):
	"""
	Physical scanning locations/sites for multi-site operations.
	Supports distributed digitization across multiple facilities.
	"""
	__tablename__ = "scanning_locations"

	id: Mapped[str] = mapped_column(String(36), primary_key=True)
	tenant_id: Mapped[str] = mapped_column(String(36), index=True)
	code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
	name: Mapped[str] = mapped_column(String(255))
	address: Mapped[str | None] = mapped_column(String(500))
	city: Mapped[str | None] = mapped_column(String(100))
	country: Mapped[str | None] = mapped_column(String(100))
	timezone: Mapped[str] = mapped_column(String(50), default="UTC")
	is_active: Mapped[bool] = mapped_column(Boolean, default=True)
	scanner_capacity: Mapped[int] = mapped_column(Integer, default=1)  # Max scanners
	operator_capacity: Mapped[int] = mapped_column(Integer, default=2)  # Max operators
	daily_page_capacity: Mapped[int] = mapped_column(Integer, default=5000)
	contact_name: Mapped[str | None] = mapped_column(String(255))
	contact_email: Mapped[str | None] = mapped_column(String(255))
	contact_phone: Mapped[str | None] = mapped_column(String(50))
	notes: Mapped[str | None] = mapped_column(String(2000))
	created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
	updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ShiftModel(Base):
	"""
	Shift definitions for multi-shift scanning operations.
	Enables 24/7 digitization operations.
	"""
	__tablename__ = "scanning_shifts"

	id: Mapped[str] = mapped_column(String(36), primary_key=True)
	tenant_id: Mapped[str] = mapped_column(String(36), index=True)
	location_id: Mapped[str | None] = mapped_column(String(36))
	name: Mapped[str] = mapped_column(String(100))  # e.g., "Morning", "Afternoon", "Night"
	start_time: Mapped[str] = mapped_column(String(10))  # "08:00"
	end_time: Mapped[str] = mapped_column(String(10))  # "16:00"
	days_of_week: Mapped[str] = mapped_column(String(20), default="1,2,3,4,5")  # 1=Mon, 7=Sun
	target_pages_per_operator: Mapped[int] = mapped_column(Integer, default=500)
	break_minutes: Mapped[int] = mapped_column(Integer, default=60)
	is_active: Mapped[bool] = mapped_column(Boolean, default=True)
	created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ShiftAssignmentModel(Base):
	"""Operator shift assignments."""
	__tablename__ = "shift_assignments"

	id: Mapped[str] = mapped_column(String(36), primary_key=True)
	shift_id: Mapped[str] = mapped_column(
		String(36),
		ForeignKey("scanning_shifts.id", ondelete="CASCADE"),
		index=True,
	)
	operator_id: Mapped[str] = mapped_column(String(36), index=True)
	operator_name: Mapped[str | None] = mapped_column(String(255))
	project_id: Mapped[str | None] = mapped_column(String(36))
	assignment_date: Mapped[datetime] = mapped_column(DateTime, index=True)
	status: Mapped[str] = mapped_column(String(50), default="scheduled")  # scheduled, completed, absent
	actual_start: Mapped[datetime | None] = mapped_column(DateTime)
	actual_end: Mapped[datetime | None] = mapped_column(DateTime)
	pages_scanned: Mapped[int] = mapped_column(Integer, default=0)
	notes: Mapped[str | None] = mapped_column(String(1000))


class ProjectCostModel(Base):
	"""
	Cost tracking for scanning projects.
	Tracks labor, equipment, materials, and other costs.
	"""
	__tablename__ = "project_costs"

	id: Mapped[str] = mapped_column(String(36), primary_key=True)
	project_id: Mapped[str] = mapped_column(
		String(36),
		ForeignKey("scanning_projects.id", ondelete="CASCADE"),
		index=True,
	)
	cost_date: Mapped[datetime] = mapped_column(DateTime, index=True)
	cost_type: Mapped[str] = mapped_column(String(50))  # labor, equipment, materials, storage, other
	category: Mapped[str | None] = mapped_column(String(100))  # e.g., "Scanner Operator", "Paper Handling"
	description: Mapped[str | None] = mapped_column(String(500))
	quantity: Mapped[float] = mapped_column(Float, default=1.0)
	unit_cost: Mapped[float] = mapped_column(Float, default=0.0)
	total_cost: Mapped[float] = mapped_column(Float, default=0.0)
	currency: Mapped[str] = mapped_column(String(3), default="USD")
	operator_id: Mapped[str | None] = mapped_column(String(36))
	location_id: Mapped[str | None] = mapped_column(String(36))
	batch_id: Mapped[str | None] = mapped_column(String(36))
	notes: Mapped[str | None] = mapped_column(String(1000))
	created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ProjectBudgetModel(Base):
	"""
	Budget planning and tracking for projects.
	"""
	__tablename__ = "project_budgets"

	id: Mapped[str] = mapped_column(String(36), primary_key=True)
	project_id: Mapped[str] = mapped_column(
		String(36),
		ForeignKey("scanning_projects.id", ondelete="CASCADE"),
		index=True,
	)
	budget_name: Mapped[str] = mapped_column(String(255))
	total_budget: Mapped[float] = mapped_column(Float, default=0.0)
	labor_budget: Mapped[float] = mapped_column(Float, default=0.0)
	equipment_budget: Mapped[float] = mapped_column(Float, default=0.0)
	materials_budget: Mapped[float] = mapped_column(Float, default=0.0)
	storage_budget: Mapped[float] = mapped_column(Float, default=0.0)
	other_budget: Mapped[float] = mapped_column(Float, default=0.0)
	contingency_budget: Mapped[float] = mapped_column(Float, default=0.0)
	currency: Mapped[str] = mapped_column(String(3), default="USD")
	spent_to_date: Mapped[float] = mapped_column(Float, default=0.0)
	cost_per_page: Mapped[float | None] = mapped_column(Float)  # Calculated
	target_cost_per_page: Mapped[float | None] = mapped_column(Float)
	is_approved: Mapped[bool] = mapped_column(Boolean, default=False)
	approved_by_id: Mapped[str | None] = mapped_column(String(36))
	approved_at: Mapped[datetime | None] = mapped_column(DateTime)
	created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
	updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SLAModel(Base):
	"""
	Service Level Agreement tracking for projects.
	"""
	__tablename__ = "project_slas"

	id: Mapped[str] = mapped_column(String(36), primary_key=True)
	project_id: Mapped[str] = mapped_column(
		String(36),
		ForeignKey("scanning_projects.id", ondelete="CASCADE"),
		index=True,
	)
	name: Mapped[str] = mapped_column(String(255))
	description: Mapped[str | None] = mapped_column(String(1000))
	sla_type: Mapped[str] = mapped_column(String(50))  # completion, quality, turnaround
	target_value: Mapped[float] = mapped_column(Float)  # e.g., 99.5% quality, 30 days turnaround
	target_unit: Mapped[str] = mapped_column(String(50))  # percent, days, hours, pages
	current_value: Mapped[float] = mapped_column(Float, default=0.0)
	threshold_warning: Mapped[float | None] = mapped_column(Float)  # Alert at this level
	threshold_critical: Mapped[float | None] = mapped_column(Float)  # Critical alert
	status: Mapped[str] = mapped_column(String(50), default="on_track")  # on_track, at_risk, breached
	penalty_amount: Mapped[float | None] = mapped_column(Float)  # Financial penalty if breached
	penalty_currency: Mapped[str] = mapped_column(String(3), default="USD")
	start_date: Mapped[datetime] = mapped_column(DateTime)
	end_date: Mapped[datetime] = mapped_column(DateTime)
	last_checked_at: Mapped[datetime | None] = mapped_column(DateTime)
	breached_at: Mapped[datetime | None] = mapped_column(DateTime)
	created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SLAAlertModel(Base):
	"""SLA breach alerts and notifications."""
	__tablename__ = "sla_alerts"

	id: Mapped[str] = mapped_column(String(36), primary_key=True)
	sla_id: Mapped[str] = mapped_column(
		String(36),
		ForeignKey("project_slas.id", ondelete="CASCADE"),
		index=True,
	)
	alert_type: Mapped[str] = mapped_column(String(50))  # warning, critical, breach
	alert_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
	message: Mapped[str] = mapped_column(String(1000))
	current_value: Mapped[float] = mapped_column(Float)
	target_value: Mapped[float] = mapped_column(Float)
	acknowledged_by_id: Mapped[str | None] = mapped_column(String(36))
	acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime)
	resolution_notes: Mapped[str | None] = mapped_column(String(2000))


class EquipmentMaintenanceModel(Base):
	"""
	Equipment maintenance scheduling and tracking.
	Ensures scanners are properly maintained for optimal performance.
	"""
	__tablename__ = "equipment_maintenance"

	id: Mapped[str] = mapped_column(String(36), primary_key=True)
	resource_id: Mapped[str] = mapped_column(
		String(36),
		ForeignKey("scanning_resources.id", ondelete="CASCADE"),
		index=True,
	)
	maintenance_type: Mapped[str] = mapped_column(String(50))  # preventive, corrective, calibration
	title: Mapped[str] = mapped_column(String(255))
	description: Mapped[str | None] = mapped_column(String(2000))
	scheduled_date: Mapped[datetime] = mapped_column(DateTime, index=True)
	completed_date: Mapped[datetime | None] = mapped_column(DateTime)
	status: Mapped[str] = mapped_column(String(50), default="scheduled")  # scheduled, in_progress, completed, cancelled
	priority: Mapped[int] = mapped_column(Integer, default=5)
	estimated_downtime_hours: Mapped[float] = mapped_column(Float, default=1.0)
	actual_downtime_hours: Mapped[float | None] = mapped_column(Float)
	technician_name: Mapped[str | None] = mapped_column(String(255))
	cost: Mapped[float] = mapped_column(Float, default=0.0)
	parts_replaced: Mapped[str | None] = mapped_column(String(1000))
	notes: Mapped[str | None] = mapped_column(String(2000))
	next_maintenance_date: Mapped[datetime | None] = mapped_column(DateTime)
	created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class OperatorCertificationModel(Base):
	"""
	Operator certifications and training records.
	Tracks qualifications for different equipment and document types.
	"""
	__tablename__ = "operator_certifications"

	id: Mapped[str] = mapped_column(String(36), primary_key=True)
	operator_id: Mapped[str] = mapped_column(String(36), index=True)
	operator_name: Mapped[str | None] = mapped_column(String(255))
	certification_type: Mapped[str] = mapped_column(String(100))  # scanner_model, document_type, qc_reviewer
	certification_name: Mapped[str] = mapped_column(String(255))
	level: Mapped[str] = mapped_column(String(50), default="basic")  # basic, intermediate, advanced, expert
	issued_date: Mapped[datetime] = mapped_column(DateTime)
	expiry_date: Mapped[datetime | None] = mapped_column(DateTime)
	issued_by: Mapped[str | None] = mapped_column(String(255))
	is_active: Mapped[bool] = mapped_column(Boolean, default=True)
	score: Mapped[float | None] = mapped_column(Float)  # Certification test score
	notes: Mapped[str | None] = mapped_column(String(1000))
	created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CapacityPlanModel(Base):
	"""
	Capacity planning for projects.
	Estimates resource requirements to meet deadlines.
	"""
	__tablename__ = "capacity_plans"

	id: Mapped[str] = mapped_column(String(36), primary_key=True)
	project_id: Mapped[str] = mapped_column(
		String(36),
		ForeignKey("scanning_projects.id", ondelete="CASCADE"),
		index=True,
	)
	plan_name: Mapped[str] = mapped_column(String(255))
	plan_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
	target_completion_date: Mapped[datetime] = mapped_column(DateTime)
	total_pages_remaining: Mapped[int] = mapped_column(Integer, default=0)
	working_days_remaining: Mapped[int] = mapped_column(Integer, default=0)
	required_pages_per_day: Mapped[int] = mapped_column(Integer, default=0)
	current_daily_capacity: Mapped[int] = mapped_column(Integer, default=0)
	capacity_gap: Mapped[int] = mapped_column(Integer, default=0)  # Negative = over capacity
	recommended_operators: Mapped[int] = mapped_column(Integer, default=0)
	recommended_scanners: Mapped[int] = mapped_column(Integer, default=0)
	recommended_shifts_per_day: Mapped[int] = mapped_column(Integer, default=1)
	confidence_score: Mapped[float] = mapped_column(Float, default=0.7)
	assumptions: Mapped[str | None] = mapped_column(String(2000))
	recommendations: Mapped[str | None] = mapped_column(String(2000))
	created_by_id: Mapped[str | None] = mapped_column(String(36))
	is_approved: Mapped[bool] = mapped_column(Boolean, default=False)
	created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DocumentTypeDistributionModel(Base):
	"""
	Track document type distribution within a project.
	Helps with resource planning and quality monitoring.
	"""
	__tablename__ = "document_type_distributions"

	id: Mapped[str] = mapped_column(String(36), primary_key=True)
	project_id: Mapped[str] = mapped_column(
		String(36),
		ForeignKey("scanning_projects.id", ondelete="CASCADE"),
		index=True,
	)
	document_type: Mapped[str] = mapped_column(String(100), index=True)
	document_type_name: Mapped[str] = mapped_column(String(255))
	estimated_count: Mapped[int] = mapped_column(Integer, default=0)
	actual_count: Mapped[int] = mapped_column(Integer, default=0)
	estimated_pages: Mapped[int] = mapped_column(Integer, default=0)
	actual_pages: Mapped[int] = mapped_column(Integer, default=0)
	avg_pages_per_document: Mapped[float] = mapped_column(Float, default=1.0)
	requires_special_handling: Mapped[bool] = mapped_column(Boolean, default=False)
	special_handling_notes: Mapped[str | None] = mapped_column(String(1000))
	priority: Mapped[int] = mapped_column(Integer, default=5)
	assigned_operator_ids: Mapped[str | None] = mapped_column(String(1000))  # Comma-separated
	created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
	updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class BatchPriorityQueueModel(Base):
	"""
	Priority queue for batch processing.
	Allows rush orders and priority processing.
	"""
	__tablename__ = "batch_priority_queue"

	id: Mapped[str] = mapped_column(String(36), primary_key=True)
	batch_id: Mapped[str] = mapped_column(
		String(36),
		ForeignKey("scanning_batches.id", ondelete="CASCADE"),
		index=True,
	)
	priority: Mapped[int] = mapped_column(Integer, default=5, index=True)  # 1-10, 10 = highest
	priority_reason: Mapped[str | None] = mapped_column(String(500))  # e.g., "Client deadline", "Legal hold"
	due_date: Mapped[datetime | None] = mapped_column(DateTime, index=True)
	is_rush: Mapped[bool] = mapped_column(Boolean, default=False)
	rush_approved_by_id: Mapped[str | None] = mapped_column(String(36))
	rush_approved_at: Mapped[datetime | None] = mapped_column(DateTime)
	estimated_completion: Mapped[datetime | None] = mapped_column(DateTime)
	actual_completion: Mapped[datetime | None] = mapped_column(DateTime)
	queue_position: Mapped[int | None] = mapped_column(Integer)  # Calculated position
	created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
	updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ProjectContractModel(Base):
	"""
	Contract details for scanning projects.
	Tracks contractual obligations and deliverables.
	"""
	__tablename__ = "project_contracts"

	id: Mapped[str] = mapped_column(String(36), primary_key=True)
	project_id: Mapped[str] = mapped_column(
		String(36),
		ForeignKey("scanning_projects.id", ondelete="CASCADE"),
		index=True,
	)
	contract_number: Mapped[str] = mapped_column(String(100), index=True)
	client_name: Mapped[str] = mapped_column(String(255))
	client_contact_name: Mapped[str | None] = mapped_column(String(255))
	client_contact_email: Mapped[str | None] = mapped_column(String(255))
	contract_type: Mapped[str] = mapped_column(String(50))  # fixed_price, per_page, time_and_materials
	contract_value: Mapped[float] = mapped_column(Float, default=0.0)
	currency: Mapped[str] = mapped_column(String(3), default="USD")
	price_per_page: Mapped[float | None] = mapped_column(Float)
	minimum_pages: Mapped[int | None] = mapped_column(Integer)
	maximum_pages: Mapped[int | None] = mapped_column(Integer)
	payment_terms: Mapped[str | None] = mapped_column(String(500))
	start_date: Mapped[datetime] = mapped_column(DateTime)
	end_date: Mapped[datetime] = mapped_column(DateTime)
	deliverables: Mapped[str | None] = mapped_column(String(2000))
	special_requirements: Mapped[str | None] = mapped_column(String(2000))
	status: Mapped[str] = mapped_column(String(50), default="active")  # draft, active, completed, cancelled
	created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
	updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class WorkloadForecastModel(Base):
	"""
	Workload forecasting for resource planning.
	Uses historical data to predict future workload.
	"""
	__tablename__ = "workload_forecasts"

	id: Mapped[str] = mapped_column(String(36), primary_key=True)
	project_id: Mapped[str] = mapped_column(
		String(36),
		ForeignKey("scanning_projects.id", ondelete="CASCADE"),
		index=True,
	)
	forecast_date: Mapped[datetime] = mapped_column(DateTime, index=True)
	forecast_period_start: Mapped[datetime] = mapped_column(DateTime)
	forecast_period_end: Mapped[datetime] = mapped_column(DateTime)
	predicted_pages: Mapped[int] = mapped_column(Integer, default=0)
	predicted_operators_needed: Mapped[int] = mapped_column(Integer, default=0)
	predicted_scanners_needed: Mapped[int] = mapped_column(Integer, default=0)
	confidence_score: Mapped[float] = mapped_column(Float, default=0.7)
	model_used: Mapped[str | None] = mapped_column(String(100))  # e.g., "linear_regression", "ai_forecast"
	actual_pages: Mapped[int | None] = mapped_column(Integer)  # Filled in after period ends
	accuracy: Mapped[float | None] = mapped_column(Float)  # Calculated after period ends
	created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ProjectCheckpointModel(Base):
	"""
	Project checkpoints/gates for large-scale projects.
	Ensures quality and progress at key milestones.
	"""
	__tablename__ = "project_checkpoints"

	id: Mapped[str] = mapped_column(String(36), primary_key=True)
	project_id: Mapped[str] = mapped_column(
		String(36),
		ForeignKey("scanning_projects.id", ondelete="CASCADE"),
		index=True,
	)
	checkpoint_number: Mapped[int] = mapped_column(Integer)
	name: Mapped[str] = mapped_column(String(255))
	description: Mapped[str | None] = mapped_column(String(1000))
	checkpoint_type: Mapped[str] = mapped_column(String(50))  # progress, quality, delivery, review
	target_date: Mapped[datetime] = mapped_column(DateTime)
	actual_date: Mapped[datetime | None] = mapped_column(DateTime)
	target_percentage: Mapped[float] = mapped_column(Float)  # e.g., 25%, 50%, 75%, 100%
	actual_percentage: Mapped[float | None] = mapped_column(Float)
	status: Mapped[str] = mapped_column(String(50), default="pending")  # pending, passed, failed, waived
	pass_criteria: Mapped[str | None] = mapped_column(String(2000))
	review_notes: Mapped[str | None] = mapped_column(String(2000))
	reviewed_by_id: Mapped[str | None] = mapped_column(String(36))
	reviewed_by_name: Mapped[str | None] = mapped_column(String(255))
	reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
	created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

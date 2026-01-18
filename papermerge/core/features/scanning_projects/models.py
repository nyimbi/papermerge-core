# (c) Copyright Datacraft, 2026
"""SQLAlchemy models for Scanning Projects feature."""
from datetime import datetime

from sqlalchemy import String, Integer, Float, Boolean, DateTime, ForeignKey, Enum, JSON
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
	__tablename__ = "scanning_projects"

	id: Mapped[str] = mapped_column(String(36), primary_key=True)
	tenant_id: Mapped[str] = mapped_column(String(36), index=True)
	name: Mapped[str] = mapped_column(String(255))
	description: Mapped[str | None] = mapped_column(String(1000))
	status: Mapped[ScanningProjectStatus] = mapped_column(
		Enum(ScanningProjectStatus),
		default=ScanningProjectStatus.PLANNING,
	)
	total_estimated_pages: Mapped[int] = mapped_column(Integer, default=0)
	scanned_pages: Mapped[int] = mapped_column(Integer, default=0)
	verified_pages: Mapped[int] = mapped_column(Integer, default=0)
	rejected_pages: Mapped[int] = mapped_column(Integer, default=0)
	target_dpi: Mapped[int] = mapped_column(Integer, default=300)
	color_mode: Mapped[ColorMode] = mapped_column(
		Enum(ColorMode),
		default=ColorMode.GRAYSCALE,
	)
	quality_sample_rate: Mapped[int] = mapped_column(Integer, default=5)
	start_date: Mapped[datetime | None] = mapped_column(DateTime)
	target_end_date: Mapped[datetime | None] = mapped_column(DateTime)
	actual_end_date: Mapped[datetime | None] = mapped_column(DateTime)
	created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
	updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

	batches: Mapped[list["ScanningBatchModel"]] = relationship(
		back_populates="project",
		cascade="all, delete-orphan",
	)
	milestones: Mapped[list["ScanningMilestoneModel"]] = relationship(
		back_populates="project",
		cascade="all, delete-orphan",
	)


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

	project: Mapped["ScanningProjectModel"] = relationship(back_populates="batches")
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

	project: Mapped["ScanningProjectModel"] = relationship(back_populates="milestones")


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

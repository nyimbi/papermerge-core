# (c) Copyright Datacraft, 2026
"""SQLAlchemy ORM model for Batch Templates."""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from papermerge.core.db.base import Base


class BatchTemplateModel(Base):
	"""
	Reusable scanning configuration templates.
	A template captures all scan-quality settings so operators can
	apply a consistent config to new batches without re-entering values.
	"""
	__tablename__ = "batch_templates"

	__table_args__ = (
		UniqueConstraint("tenant_id", "name", name="uq_batch_templates_tenant_name"),
	)

	id: Mapped[str] = mapped_column(String(36), primary_key=True)
	name: Mapped[str] = mapped_column(String(255), nullable=False)
	description: Mapped[str | None] = mapped_column(String(2000), nullable=True)

	# Scan quality settings
	dpi: Mapped[int] = mapped_column(Integer, default=300)
	color_mode: Mapped[str] = mapped_column(String(20), default="color")       # color | grayscale | black_white
	paper_size: Mapped[str] = mapped_column(String(20), default="A4")          # A4 | A3 | Letter | Legal | auto
	quality_threshold: Mapped[float] = mapped_column(Float, default=60.0)
	barcode_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
	auto_deskew: Mapped[bool] = mapped_column(Boolean, default=True)
	auto_enhance: Mapped[bool] = mapped_column(Boolean, default=False)
	expected_pages_per_document: Mapped[int | None] = mapped_column(Integer, nullable=True)
	notes_template: Mapped[str | None] = mapped_column(String(2000), nullable=True)

	# Ownership / multi-tenancy
	tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
	created_by_id: Mapped[str] = mapped_column(String(36), nullable=False)

	# Timestamps + counters
	created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
	updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
	usage_count: Mapped[int] = mapped_column(Integer, default=0)

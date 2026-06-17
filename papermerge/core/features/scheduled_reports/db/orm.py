# (c) Copyright Datacraft, 2026
"""ORM model for scheduled report configurations."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
	Boolean,
	DateTime,
	ForeignKey,
	Index,
	Integer,
	String,
	Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from papermerge.core.db.base import Base
from papermerge.core.utils.uuid_compat import uuid7str


class ScheduledReport(Base):
	"""
	Persists a recurring report delivery configuration.

	schedule  : "daily" | "weekly" | "monthly"
	report_type: "document_summary" | "ocr_quality" | "scanning_productivity" | "expiry_upcoming"
	format    : "csv" | "xlsx"
	recipients: comma-separated email addresses
	filters   : JSON-encoded extra filter params (tenant-scoped queries honour these)
	"""

	__tablename__ = "scheduled_reports"

	id: Mapped[str] = mapped_column(
		String(32),
		primary_key=True,
		default=uuid7str,
	)
	name: Mapped[str] = mapped_column(String(200), nullable=False)
	report_type: Mapped[str] = mapped_column(String(50), nullable=False)
	# "daily" | "weekly" | "monthly"
	schedule: Mapped[str] = mapped_column(String(20), nullable=False)
	# UTC hour (0-23) at which to send
	delivery_hour: Mapped[int] = mapped_column(Integer, default=8)
	# 0=Monday … 6=Sunday; only relevant when schedule="weekly"
	day_of_week: Mapped[int | None] = mapped_column(Integer, nullable=True)
	# comma-separated list of recipient email addresses
	recipients: Mapped[str] = mapped_column(Text, nullable=False)
	# "csv" | "xlsx"
	format: Mapped[str] = mapped_column(String(10), default="xlsx")
	# JSON-encoded dict of extra filter parameters
	filters: Mapped[str] = mapped_column(Text, default="{}")
	is_active: Mapped[bool] = mapped_column(Boolean, default=True)
	last_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
	send_count: Mapped[int] = mapped_column(Integer, default=0)

	tenant_id: Mapped[UUID] = mapped_column(
		ForeignKey("tenants.id", ondelete="CASCADE"),
		nullable=False,
	)
	created_by_id: Mapped[UUID] = mapped_column(
		ForeignKey("core_users.id", ondelete="SET NULL"),
		nullable=True,
	)
	created_at: Mapped[datetime] = mapped_column(
		DateTime,
		default=datetime.utcnow,
		nullable=False,
	)

	__table_args__ = (
		Index("ix_scheduled_reports_tenant", "tenant_id"),
		Index("ix_scheduled_reports_active", "is_active"),
		Index("ix_scheduled_reports_schedule", "schedule"),
	)

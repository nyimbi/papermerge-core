# (c) Copyright Datacraft, 2026
"""Exception Event ORM models."""
from datetime import datetime
from enum import Enum

from sqlalchemy import String, ForeignKey, Integer, Boolean, Text, Float, func, Index
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import TIMESTAMP, JSONB

from papermerge.core.db.base import Base
from papermerge.core.utils.uuid_compat import uuid7str
from papermerge.core.utils.tz import utc_now


class ExceptionType(str, Enum):
	"""Types of exceptions that can occur during scanning/processing."""
	QUALITY_REJECTED = "quality_rejected"
	MISSING_SIGNATURE = "missing_signature"
	INCOMPLETE_SET = "incomplete_set"
	BARCODE_UNREADABLE = "barcode_unreadable"
	ORIENTATION_ERROR = "orientation_error"


class ExceptionSeverity(str, Enum):
	"""Severity levels for exceptions."""
	WARNING = "warning"
	ERROR = "error"
	CRITICAL = "critical"


class ExceptionStatus(str, Enum):
	"""Status of an exception event."""
	OPEN = "open"
	IN_REVIEW = "in_review"
	RESOLVED = "resolved"
	DISMISSED = "dismissed"
	AUTO_RESOLVED = "auto_resolved"


class RoutingAction(str, Enum):
	"""Routing actions for exception handling."""
	RESCAN_QUEUE = "rescan_queue"
	SUPERVISOR_REVIEW = "supervisor_review"
	HALT_BATCH = "halt_batch"
	AUTO_FIX = "auto_fix"


class RuleAction(str, Enum):
	"""Actions a routing rule can take."""
	RESCAN_QUEUE = "rescan_queue"
	SUPERVISOR_REVIEW = "supervisor_review"
	HALT_BATCH = "halt_batch"
	NOTIFY_OPERATOR = "notify_operator"
	AUTO_DISMISS = "auto_dismiss"


class ExceptionEvent(Base):
	"""An exception event raised during scanning or document processing."""
	__tablename__ = "exception_events"

	id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7str)

	# Context FKs — all SET NULL so records survive related entity deletion
	scan_job_id: Mapped[str | None] = mapped_column(
		String(36),
		ForeignKey("scan_jobs.id", ondelete="SET NULL"),
		nullable=True,
		index=True,
	)
	document_id: Mapped[str | None] = mapped_column(
		String(36),
		ForeignKey("nodes.id", ondelete="SET NULL"),
		nullable=True,
		index=True,
	)
	batch_id: Mapped[str | None] = mapped_column(
		String(36),
		ForeignKey("scanning_batches.id", ondelete="SET NULL"),
		nullable=True,
		index=True,
	)
	page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

	# Classification
	exception_type: Mapped[str] = mapped_column(
		String(50), nullable=False, index=True
	)  # ExceptionType
	severity: Mapped[str] = mapped_column(
		String(20), nullable=False, default=ExceptionSeverity.ERROR.value
	)
	status: Mapped[str] = mapped_column(
		String(20), nullable=False, default=ExceptionStatus.OPEN.value, index=True
	)

	# Routing
	routing_action: Mapped[str | None] = mapped_column(String(50), nullable=True)

	# Details
	description: Mapped[str | None] = mapped_column(Text, nullable=True)
	auto_fixable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
	quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
	defects: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

	# Resolution
	resolved_by_id: Mapped[str | None] = mapped_column(
		String(36),
		ForeignKey("users.id", ondelete="SET NULL"),
		nullable=True,
	)
	resolved_at: Mapped[datetime | None] = mapped_column(
		TIMESTAMP(timezone=True), nullable=True
	)
	resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

	# Tenant isolation
	tenant_id: Mapped[str | None] = mapped_column(
		String(36),
		ForeignKey("tenants.id", ondelete="CASCADE"),
		nullable=True,
		index=True,
	)

	# Timestamps
	created_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), default=utc_now, nullable=False
	)
	updated_at: Mapped[datetime | None] = mapped_column(
		TIMESTAMP(timezone=True),
		default=utc_now,
		onupdate=func.now(),
		nullable=True,
	)

	__table_args__ = (
		Index("idx_exception_events_tenant_status", "tenant_id", "status"),
		Index("idx_exception_events_tenant_type", "tenant_id", "exception_type"),
		Index("idx_exception_events_created_at", "created_at"),
		Index("idx_exception_events_batch_status", "batch_id", "status"),
	)


class ExceptionRoutingRule(Base):
	"""Routing rule that determines how an exception type is handled."""
	__tablename__ = "exception_routing_rules"

	id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7str)

	tenant_id: Mapped[str | None] = mapped_column(
		String(36),
		ForeignKey("tenants.id", ondelete="CASCADE"),
		nullable=True,
		index=True,
	)
	# NULL = applies to all projects within the tenant
	project_id: Mapped[str | None] = mapped_column(
		String(36),
		nullable=True,
		index=True,
	)

	# Which exception type this rule handles
	exception_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

	# What to do
	action: Mapped[str] = mapped_column(String(50), nullable=False)  # RuleAction

	# Lower priority value = higher precedence
	priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
	is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

	# Additional config (e.g., notify_emails, auto_resolve_threshold)
	config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

	# Timestamps
	created_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), default=utc_now, nullable=False
	)
	updated_at: Mapped[datetime | None] = mapped_column(
		TIMESTAMP(timezone=True),
		default=utc_now,
		onupdate=func.now(),
		nullable=True,
	)

	__table_args__ = (
		Index("idx_exc_routing_rules_tenant_type", "tenant_id", "exception_type"),
		Index("idx_exc_routing_rules_active", "is_active"),
		Index("idx_exc_routing_rules_priority", "priority"),
	)

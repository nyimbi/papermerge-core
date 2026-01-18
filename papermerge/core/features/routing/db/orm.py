# (c) Copyright Datacraft, 2026
"""Routing ORM models."""
import uuid
from datetime import datetime
from uuid import UUID
from enum import Enum

from sqlalchemy import String, ForeignKey, Integer, Boolean, Text, func, Index
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import TIMESTAMP, JSONB

from papermerge.core.db.base import Base
from papermerge.core.utils.tz import utc_now


class DestinationType(str, Enum):
	FOLDER = "folder"
	WORKFLOW = "workflow"
	USER_INBOX = "user_inbox"


class RoutingMode(str, Enum):
	OPERATIONAL = "operational"
	ARCHIVAL = "archival"
	BOTH = "both"


class RoutingRule(Base):
	"""Auto-routing rule definition."""
	__tablename__ = "routing_rules"

	id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
	tenant_id: Mapped[UUID] = mapped_column(
		ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
	)

	name: Mapped[str] = mapped_column(String(255), nullable=False)
	description: Mapped[str | None] = mapped_column(Text)
	priority: Mapped[int] = mapped_column(Integer, default=100)

	# Matching conditions (JSON)
	# Example: {"document_type": "invoice", "metadata.vendor": "Acme"}
	conditions: Mapped[dict] = mapped_column(JSONB, nullable=False)

	# Destination
	destination_type: Mapped[str] = mapped_column(String(50), nullable=False)
	destination_id: Mapped[UUID | None] = mapped_column()

	# Mode
	mode: Mapped[str] = mapped_column(
		String(20), default=RoutingMode.BOTH.value, nullable=False
	)

	is_active: Mapped[bool] = mapped_column(Boolean, default=True)

	# Timestamps
	created_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), default=utc_now, nullable=False
	)
	updated_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), default=utc_now, onupdate=func.now(), nullable=False
	)
	created_by: Mapped[UUID | None] = mapped_column(
		ForeignKey("users.id", ondelete="SET NULL")
	)

	__table_args__ = (
		Index("idx_routing_rules_active", "tenant_id", "is_active", "priority"),
	)


class RoutingLog(Base):
	"""Log of routing decisions."""
	__tablename__ = "routing_logs"

	id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
	tenant_id: Mapped[UUID] = mapped_column(
		ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
	)
	document_id: Mapped[UUID] = mapped_column(
		ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False, index=True
	)

	# Routing result
	rule_id: Mapped[UUID | None] = mapped_column(
		ForeignKey("routing_rules.id", ondelete="SET NULL")
	)
	matched: Mapped[bool] = mapped_column(Boolean, nullable=False)

	destination_type: Mapped[str | None] = mapped_column(String(50))
	destination_id: Mapped[UUID | None] = mapped_column()

	# Context
	mode: Mapped[str] = mapped_column(String(20), nullable=False)
	evaluated_conditions: Mapped[dict | None] = mapped_column(JSONB)

	# Timestamps
	created_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), default=utc_now, nullable=False
	)

	__table_args__ = (
		Index("idx_routing_logs_document", "document_id"),
	)

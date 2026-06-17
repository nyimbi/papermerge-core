# (c) Copyright Datacraft, 2026
"""Auto-routing rule ORM model."""
import uuid
from datetime import datetime
from uuid import UUID

from sqlalchemy import String, ForeignKey, Integer, Float, Boolean, Index
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import TIMESTAMP

from papermerge.core.db.base import Base
from papermerge.core.utils.tz import utc_now


class AutoRoutingRule(Base):
	"""
	Rule that automatically moves a classified document into a target folder.

	Matching logic (applied in priority DESC order):
	  - document_type must equal the classified type string
	  - confidence >= confidence_threshold
	  - if project_id is set, the document must originate from that project
	"""
	__tablename__ = "auto_routing_rules"

	id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

	name: Mapped[str] = mapped_column(String(255), nullable=False)

	# The classified document type string this rule targets (e.g. "invoice", "contract")
	document_type: Mapped[str] = mapped_column(String(100), nullable=False)

	# Minimum confidence score (0.0–1.0) required to trigger the rule
	confidence_threshold: Mapped[float] = mapped_column(Float, default=0.75, nullable=False)

	# Target folder — FK to nodes table (folders are nodes with ctype='folder')
	destination_folder_id: Mapped[UUID] = mapped_column(
		ForeignKey("nodes.id", ondelete="CASCADE"),
		nullable=False,
	)

	# Optional: restrict rule to documents from a specific scanning project
	project_id: Mapped[UUID | None] = mapped_column(
		ForeignKey("nodes.id", ondelete="SET NULL"),
		nullable=True,
	)

	# Higher number = higher priority; first matching rule wins
	priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

	is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

	# How many times this rule successfully routed a document
	applied_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

	tenant_id: Mapped[UUID] = mapped_column(
		ForeignKey("tenants.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)

	created_by_id: Mapped[UUID] = mapped_column(
		ForeignKey("users.id", ondelete="RESTRICT"),
		nullable=False,
	)

	created_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True),
		default=utc_now,
		nullable=False,
	)

	updated_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True),
		default=utc_now,
		nullable=False,
	)

	__table_args__ = (
		Index(
			"idx_auto_routing_rules_tenant_active_priority",
			"tenant_id", "is_active", "priority",
		),
		Index(
			"idx_auto_routing_rules_document_type",
			"tenant_id", "document_type", "is_active",
		),
	)

	def __repr__(self) -> str:
		return (
			f"AutoRoutingRule(id={self.id}, name={self.name!r}, "
			f"document_type={self.document_type!r}, priority={self.priority})"
		)

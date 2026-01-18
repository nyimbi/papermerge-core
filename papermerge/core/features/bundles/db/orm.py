# (c) Copyright Datacraft, 2026
"""Bundle/Binder ORM models."""
import uuid
from datetime import datetime
from uuid import UUID
from enum import Enum

from sqlalchemy import String, ForeignKey, Integer, Boolean, Text, func, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import TIMESTAMP, JSONB

from papermerge.core.db.base import Base
from papermerge.core.db.mixins import AuditColumns
from papermerge.core.utils.tz import utc_now


class BundleStatus(str, Enum):
	DRAFT = "draft"
	ACTIVE = "active"
	ARCHIVED = "archived"
	LOCKED = "locked"


class Bundle(Base, AuditColumns):
	"""Document bundle/binder."""
	__tablename__ = "bundles"

	id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
	tenant_id: Mapped[UUID] = mapped_column(
		ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
	)

	title: Mapped[str] = mapped_column(String(255), nullable=False)
	description: Mapped[str | None] = mapped_column(Text)

	# Numbering
	bundle_number: Mapped[str | None] = mapped_column(String(50))

	# Status
	status: Mapped[str] = mapped_column(
		String(20), default=BundleStatus.DRAFT.value, nullable=False
	)

	# Parent case (optional)
	case_id: Mapped[UUID | None] = mapped_column(
		ForeignKey("cases.id", ondelete="SET NULL"), index=True
	)

	# Metadata
	metadata: Mapped[dict | None] = mapped_column(JSONB)

	# Relationships
	documents: Mapped[list["BundleDocument"]] = relationship(
		"BundleDocument", back_populates="bundle", cascade="all, delete-orphan",
		order_by="BundleDocument.sort_order"
	)
	sections: Mapped[list["BundleSection"]] = relationship(
		"BundleSection", back_populates="bundle", cascade="all, delete-orphan",
		order_by="BundleSection.sort_order"
	)

	__table_args__ = (
		Index("idx_bundles_tenant", "tenant_id"),
		Index("idx_bundles_case", "case_id"),
	)


class BundleSection(Base):
	"""Section divider within a bundle."""
	__tablename__ = "bundle_sections"

	id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
	bundle_id: Mapped[UUID] = mapped_column(
		ForeignKey("bundles.id", ondelete="CASCADE"), nullable=False, index=True
	)

	title: Mapped[str] = mapped_column(String(255), nullable=False)
	sort_order: Mapped[int] = mapped_column(Integer, nullable=False)

	# Timestamps
	created_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), default=utc_now, nullable=False
	)

	# Relationships
	bundle: Mapped["Bundle"] = relationship("Bundle", back_populates="sections")


class BundleDocument(Base):
	"""Document within a bundle."""
	__tablename__ = "bundle_documents"

	id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
	bundle_id: Mapped[UUID] = mapped_column(
		ForeignKey("bundles.id", ondelete="CASCADE"), nullable=False, index=True
	)
	document_id: Mapped[UUID] = mapped_column(
		ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False, index=True
	)

	# Ordering
	sort_order: Mapped[int] = mapped_column(Integer, nullable=False)

	# Section (optional)
	section_id: Mapped[UUID | None] = mapped_column(
		ForeignKey("bundle_sections.id", ondelete="SET NULL")
	)

	# Display overrides
	display_title: Mapped[str | None] = mapped_column(String(255))
	exhibit_number: Mapped[str | None] = mapped_column(String(50))

	# Page range (for partial inclusion)
	start_page: Mapped[int | None] = mapped_column(Integer)
	end_page: Mapped[int | None] = mapped_column(Integer)

	# Timestamps
	created_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), default=utc_now, nullable=False
	)

	# Relationships
	bundle: Mapped["Bundle"] = relationship("Bundle", back_populates="documents")

	__table_args__ = (
		UniqueConstraint("bundle_id", "document_id", name="uq_bundle_document"),
		Index("idx_bundle_documents_order", "bundle_id", "sort_order"),
	)

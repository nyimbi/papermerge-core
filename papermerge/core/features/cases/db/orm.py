# (c) Copyright Datacraft, 2026
"""Case ORM models."""
import uuid
from datetime import datetime
from uuid import UUID
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import String, ForeignKey, Integer, Boolean, Text, func, Index, UniqueConstraint, Date
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import TIMESTAMP, JSONB

if TYPE_CHECKING:
	from papermerge.core.features.portfolios.db.orm import Portfolio
	from papermerge.core.features.bundles.db.orm import Bundle

from papermerge.core.db.base import Base
from papermerge.core.db.mixins import AuditColumns
from papermerge.core.utils.tz import utc_now


class CaseStatus(str, Enum):
	OPEN = "open"
	ACTIVE = "active"
	PENDING = "pending"
	CLOSED = "closed"
	ARCHIVED = "archived"


class Case(Base, AuditColumns):
	"""Legal/business case container."""
	__tablename__ = "cases"

	id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
	tenant_id: Mapped[UUID] = mapped_column(
		ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
	)

	# Identification
	case_number: Mapped[str] = mapped_column(String(100), nullable=False)
	title: Mapped[str] = mapped_column(String(500), nullable=False)
	description: Mapped[str | None] = mapped_column(Text)

	# Status
	status: Mapped[str] = mapped_column(
		String(20), default=CaseStatus.OPEN.value, nullable=False
	)

	# Dates
	opened_date: Mapped[datetime | None] = mapped_column(Date)
	closed_date: Mapped[datetime | None] = mapped_column(Date)
	due_date: Mapped[datetime | None] = mapped_column(Date)

	# Classification
	case_type: Mapped[str | None] = mapped_column(String(100))
	jurisdiction: Mapped[str | None] = mapped_column(String(100))
	matter_id: Mapped[str | None] = mapped_column(String(100))

	# Parent portfolio (optional)
	portfolio_id: Mapped[UUID | None] = mapped_column(
		ForeignKey("portfolios.id", ondelete="SET NULL"), index=True
	)

	# Case metadata
	case_metadata: Mapped[dict | None] = mapped_column(JSONB)

	# Relationships
	portfolio: Mapped["Portfolio"] = relationship(
		"Portfolio", back_populates="cases", foreign_keys=[portfolio_id]
	)
	bundles: Mapped[list["Bundle"]] = relationship(
		"Bundle", back_populates="case", foreign_keys="Bundle.case_id"
	)
	documents: Mapped[list["CaseDocument"]] = relationship(
		"CaseDocument", back_populates="case", cascade="all, delete-orphan"
	)
	access_list: Mapped[list["CaseAccess"]] = relationship(
		"CaseAccess", back_populates="case", cascade="all, delete-orphan"
	)

	__table_args__ = (
		UniqueConstraint("tenant_id", "case_number", name="uq_case_number"),
		Index("idx_cases_tenant", "tenant_id"),
		Index("idx_cases_portfolio", "portfolio_id"),
		Index("idx_cases_status", "status"),
	)


class CaseDocument(Base):
	"""Direct document association with a case (not in bundle)."""
	__tablename__ = "case_documents"

	id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
	case_id: Mapped[UUID] = mapped_column(
		ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True
	)
	document_id: Mapped[UUID] = mapped_column(
		ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False, index=True
	)

	# Timestamps
	added_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), default=utc_now, nullable=False
	)
	added_by: Mapped[UUID | None] = mapped_column(
		ForeignKey("users.id", ondelete="SET NULL")
	)

	# Relationships
	case: Mapped["Case"] = relationship("Case", back_populates="documents")

	__table_args__ = (
		UniqueConstraint("case_id", "document_id", name="uq_case_document"),
	)


class CaseAccess(Base):
	"""Access control for cases."""
	__tablename__ = "case_access"

	id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
	case_id: Mapped[UUID] = mapped_column(
		ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True
	)

	# Subject
	subject_type: Mapped[str] = mapped_column(String(20), nullable=False)  # user, group, role
	subject_id: Mapped[UUID] = mapped_column(nullable=False)

	# Permissions
	allow_view: Mapped[bool] = mapped_column(Boolean, default=True)
	allow_download: Mapped[bool] = mapped_column(Boolean, default=False)
	allow_print: Mapped[bool] = mapped_column(Boolean, default=False)
	allow_edit: Mapped[bool] = mapped_column(Boolean, default=False)
	allow_share: Mapped[bool] = mapped_column(Boolean, default=False)

	# Validity
	valid_from: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
	valid_until: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

	# Timestamps
	created_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), default=utc_now, nullable=False
	)
	created_by: Mapped[UUID | None] = mapped_column(
		ForeignKey("users.id", ondelete="SET NULL")
	)

	# Relationships
	case: Mapped["Case"] = relationship("Case", back_populates="access_list")

	__table_args__ = (
		UniqueConstraint("case_id", "subject_type", "subject_id", name="uq_case_subject_access"),
		Index("idx_case_access_subject", "subject_type", "subject_id"),
	)

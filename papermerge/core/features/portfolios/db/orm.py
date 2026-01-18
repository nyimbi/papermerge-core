# (c) Copyright Datacraft, 2026
"""Portfolio ORM models."""
import uuid
from datetime import datetime
from uuid import UUID
from enum import Enum

from sqlalchemy import String, ForeignKey, Boolean, Text, func, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import TIMESTAMP, JSONB

from papermerge.core.db.base import Base
from papermerge.core.db.mixins import AuditColumns
from papermerge.core.utils.tz import utc_now


class PortfolioStatus(str, Enum):
	ACTIVE = "active"
	ARCHIVED = "archived"
	CLOSED = "closed"


class Portfolio(Base, AuditColumns):
	"""Portfolio containing cases."""
	__tablename__ = "portfolios"

	id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
	tenant_id: Mapped[UUID] = mapped_column(
		ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
	)

	# Identification
	name: Mapped[str] = mapped_column(String(255), nullable=False)
	code: Mapped[str | None] = mapped_column(String(50))
	description: Mapped[str | None] = mapped_column(Text)

	# Status
	status: Mapped[str] = mapped_column(
		String(20), default=PortfolioStatus.ACTIVE.value, nullable=False
	)

	# Client info
	client_name: Mapped[str | None] = mapped_column(String(255))
	client_id: Mapped[str | None] = mapped_column(String(100))

	# Metadata
	metadata: Mapped[dict | None] = mapped_column(JSONB)

	# Relationships
	cases: Mapped[list["Case"]] = relationship(
		"Case", back_populates="portfolio", foreign_keys="Case.portfolio_id"
	)
	access_list: Mapped[list["PortfolioAccess"]] = relationship(
		"PortfolioAccess", back_populates="portfolio", cascade="all, delete-orphan"
	)

	__table_args__ = (
		Index("idx_portfolios_tenant", "tenant_id"),
		Index("idx_portfolios_status", "status"),
	)


class PortfolioAccess(Base):
	"""Access control for portfolios."""
	__tablename__ = "portfolio_access"

	id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
	portfolio_id: Mapped[UUID] = mapped_column(
		ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False, index=True
	)

	# Subject
	subject_type: Mapped[str] = mapped_column(String(20), nullable=False)
	subject_id: Mapped[UUID] = mapped_column(nullable=False)

	# Permissions
	allow_view: Mapped[bool] = mapped_column(Boolean, default=True)
	allow_download: Mapped[bool] = mapped_column(Boolean, default=False)
	allow_print: Mapped[bool] = mapped_column(Boolean, default=False)
	allow_edit: Mapped[bool] = mapped_column(Boolean, default=False)
	allow_share: Mapped[bool] = mapped_column(Boolean, default=False)

	# Inherit to children
	inherit_to_cases: Mapped[bool] = mapped_column(Boolean, default=True)

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
	portfolio: Mapped["Portfolio"] = relationship("Portfolio", back_populates="access_list")

	__table_args__ = (
		UniqueConstraint("portfolio_id", "subject_type", "subject_id", name="uq_portfolio_subject_access"),
		Index("idx_portfolio_access_subject", "subject_type", "subject_id"),
	)

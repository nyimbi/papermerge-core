# (c) Copyright Datacraft, 2026
"""SQLAlchemy ORM model for document expiry settings."""
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, UniqueConstraint

from papermerge.core.db.base import Base
from papermerge.core.utils.uuid_compat import uuid7str


class DocumentExpiry(Base):
	"""Per-document expiry record: stores the expiry date, reminder schedule, and
	which milestones have already fired notifications."""
	__tablename__ = "document_expiry"

	id = Column(String(36), primary_key=True, default=uuid7str)

	# One-to-one with documents
	document_id = Column(
		String(36),
		ForeignKey("documents.id", ondelete="CASCADE"),
		nullable=False,
		unique=True,
	)

	# The date/time when the document expires
	expires_at = Column(DateTime, nullable=False)

	# JSON array of days-before-expiry to trigger reminders, e.g. "[30,7,1]"
	reminder_days = Column(String(255), nullable=False, default="[30,7,1]")

	# JSON array of days already notified, e.g. "[30]"; updated as reminders fire
	notified_milestones = Column(String(255), nullable=False, default="[]")

	created_by_id = Column(
		String(36),
		ForeignKey("users.id", ondelete="SET NULL"),
		nullable=True,
	)
	tenant_id = Column(
		String(36),
		ForeignKey("tenants.id", ondelete="CASCADE"),
		nullable=False,
	)
	created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
	updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

	__table_args__ = (
		UniqueConstraint("document_id", name="uq_document_expiry_document_id"),
		Index("ix_document_expiry_tenant_expires", "tenant_id", "expires_at"),
		Index("ix_document_expiry_expires_at", "expires_at"),
	)

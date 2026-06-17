# (c) Copyright Datacraft, 2026
"""ORM model for named legal holds on documents."""
from datetime import datetime

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column
from uuid6 import uuid7

from papermerge.core.db.base import Base
from papermerge.core.utils.tz import utc_now


def _uuid7str() -> str:
	return str(uuid7())


class LegalHold(Base):
	"""A named legal hold placed on a specific document.

	A document may have multiple concurrent active holds.  A hold is
	*active* when ``released_at`` is NULL.  Releasing sets ``released_at``
	and ``released_by_id`` without deleting the row — the history is kept.
	"""
	__tablename__ = "legal_hold_entries"

	id: Mapped[str] = mapped_column(
		String(36),
		primary_key=True,
		default=_uuid7str,
	)
	document_id: Mapped[str] = mapped_column(
		String(36),
		ForeignKey("documents.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	hold_name: Mapped[str] = mapped_column(String(255), nullable=False)
	hold_reason: Mapped[str] = mapped_column(Text, nullable=False)

	held_by_id: Mapped[str] = mapped_column(String(36), nullable=False)
	released_by_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

	held_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True),
		default=utc_now,
		nullable=False,
	)
	released_at: Mapped[datetime | None] = mapped_column(
		TIMESTAMP(timezone=True),
		nullable=True,
	)

	tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

	def __repr__(self) -> str:
		return (
			f"LegalHold(id={self.id!r}, doc={self.document_id!r}, "
			f"name={self.hold_name!r}, active={self.released_at is None})"
		)

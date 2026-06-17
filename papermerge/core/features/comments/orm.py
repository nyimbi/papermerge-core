from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from papermerge.core.db.base import Base


def _now() -> datetime:
	return datetime.now(timezone.utc)


class DocumentComment(Base):
	__tablename__ = "document_comments"

	id: Mapped[str] = mapped_column(String(36), primary_key=True)
	document_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
	page_number: Mapped[Optional[int]] = mapped_column(nullable=True)
	author_id: Mapped[str] = mapped_column(String(36), nullable=False)
	author_name: Mapped[str] = mapped_column(String(255), nullable=False)
	content: Mapped[str] = mapped_column(Text, nullable=False)
	is_resolved: Mapped[bool] = mapped_column(Boolean, default=False)
	parent_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
	created_at: Mapped[datetime] = mapped_column(
		DateTime(timezone=True), default=_now
	)
	updated_at: Mapped[datetime] = mapped_column(
		DateTime(timezone=True), default=_now, onupdate=_now
	)

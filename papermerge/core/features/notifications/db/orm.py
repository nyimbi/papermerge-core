from datetime import datetime
from uuid import UUID as PyUUID

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column
from uuid6 import uuid7

from papermerge.core.db.base import Base
from papermerge.core.utils.tz import utc_now


def _uuid7str() -> str:
	return str(uuid7())


class Notification(Base):
	__tablename__ = "notifications"

	id: Mapped[str] = mapped_column(
		String(36),
		primary_key=True,
		default=_uuid7str,
	)
	user_id: Mapped[PyUUID] = mapped_column(
		UUID(as_uuid=True),
		ForeignKey("users.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	type: Mapped[str] = mapped_column(String(20), nullable=False)
	title: Mapped[str] = mapped_column(String(255), nullable=False)
	message: Mapped[str] = mapped_column(Text, nullable=False)
	read: Mapped[bool] = mapped_column(
		Boolean,
		nullable=False,
		default=False,
		server_default="false",
	)
	link: Mapped[str | None] = mapped_column(String(500), nullable=True)
	extra: Mapped[dict | None] = mapped_column(JSONB, nullable=True, name="metadata")
	created_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True),
		default=utc_now,
		nullable=False,
	)

	def __repr__(self) -> str:
		return f"Notification(id={self.id!r}, user_id={self.user_id!r}, type={self.type!r})"

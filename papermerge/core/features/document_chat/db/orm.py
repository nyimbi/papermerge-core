"""ORM model for document chat messages."""
import uuid
from datetime import datetime

from sqlalchemy import String, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import TIMESTAMP

from papermerge.core.db.base import Base
from papermerge.core.utils.tz import utc_now


class DocumentChatMessage(Base):
	__tablename__ = "document_chat_messages"

	id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
	conversation_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
	document_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
	role: Mapped[str] = mapped_column(String(16), nullable=False)  # "user" | "assistant"
	content: Mapped[str] = mapped_column(Text, nullable=False)
	page_references: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON array
	created_by_id: Mapped[str] = mapped_column(String, nullable=False)
	tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
	created_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True),
		default=utc_now,
		nullable=False,
	)

	def __repr__(self) -> str:
		return f"DocumentChatMessage(id={self.id!r}, role={self.role!r}, conversation_id={self.conversation_id!r})"

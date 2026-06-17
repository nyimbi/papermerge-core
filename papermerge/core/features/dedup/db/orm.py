"""ORM model for document deduplication hashes."""
import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import TIMESTAMP

from papermerge.core.db.base import Base
from papermerge.core.utils.tz import utc_now


class DocumentHash(Base):
	__tablename__ = "document_hashes"

	id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

	document_id: Mapped[str] = mapped_column(
		String,
		ForeignKey("documents.node_id", ondelete="CASCADE"),
		nullable=False,
		unique=True,
		index=True,
	)

	# SHA-256 of the raw file bytes
	file_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

	# SHA-256 of normalised extracted text
	content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

	# pHash stored as hex string (for near-duplicate image detection)
	perceptual_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

	tenant_id: Mapped[str | None] = mapped_column(nullable=True)

	created_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True),
		default=utc_now,
		nullable=False,
	)

	updated_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True),
		default=utc_now,
		onupdate=utc_now,
		nullable=False,
	)

	def __repr__(self) -> str:
		return (
			f"DocumentHash("
			f"document_id={self.document_id!s:.8}, "
			f"file_hash={self.file_hash!s:.8})"
		)

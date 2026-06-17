import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, UniqueConstraint, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import TIMESTAMP

from papermerge.core.db.base import Base
from papermerge.core.utils.tz import utc_now


class DocumentRelationship(Base):
	__tablename__ = "document_relationships"

	id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

	source_document_id: Mapped[uuid.UUID] = mapped_column(
		ForeignKey("documents.node_id", ondelete="CASCADE"),
		nullable=False,
	)
	target_document_id: Mapped[uuid.UUID] = mapped_column(
		ForeignKey("documents.node_id", ondelete="CASCADE"),
		nullable=False,
	)

	# "related" | "supersedes" | "amendment_of" | "attachment_to" | "version_of"
	relationship_type: Mapped[str] = mapped_column(String(64), nullable=False)

	note: Mapped[str | None] = mapped_column(nullable=True)

	tenant_id: Mapped[str | None] = mapped_column(nullable=True)

	created_by_id: Mapped[uuid.UUID] = mapped_column(
		ForeignKey("users.id", ondelete="RESTRICT", deferrable=True, initially="DEFERRED"),
		nullable=False,
	)

	created_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True),
		default=utc_now,
		nullable=False,
	)

	__table_args__ = (
		UniqueConstraint(
			"source_document_id",
			"target_document_id",
			"relationship_type",
			name="uq_doc_relationship_src_tgt_type",
		),
	)

	def __repr__(self) -> str:
		return (
			f"DocumentRelationship("
			f"source={self.source_document_id!s:.8}, "
			f"target={self.target_document_id!s:.8}, "
			f"type={self.relationship_type})"
		)

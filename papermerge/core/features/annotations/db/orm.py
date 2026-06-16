from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import Float, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from papermerge.core.db.base import Base


class DocumentAnnotation(Base):
	"""
	Spatial annotation on a document page.
	x/y/width/height are normalised fractions of page dimensions (0.0–1.0),
	so they remain valid regardless of zoom level or render resolution.
	"""
	__tablename__ = "document_annotations"

	id: Mapped[UUID] = mapped_column(
		PG_UUID(as_uuid=True),
		primary_key=True,
		server_default=func.gen_random_uuid(),
	)
	document_id: Mapped[UUID] = mapped_column(
		PG_UUID(as_uuid=True),
		ForeignKey("documents.id", ondelete="CASCADE"),
		nullable=False,
	)
	page_number: Mapped[int] = mapped_column(nullable=False)
	# highlight | note | redaction
	annotation_type: Mapped[str] = mapped_column(String(32), nullable=False)

	# Normalised bounding box (fraction of page, 0–1)
	x: Mapped[float] = mapped_column(Float, nullable=False)
	y: Mapped[float] = mapped_column(Float, nullable=False)
	width: Mapped[float] = mapped_column(Float, nullable=False)
	height: Mapped[float] = mapped_column(Float, nullable=False)

	# Optional text for notes
	content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

	color: Mapped[str] = mapped_column(String(32), nullable=False, default="#FFD700")

	created_by_id: Mapped[str] = mapped_column(String(64), nullable=False)
	tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)

	created_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True),
		server_default=func.now(),
		nullable=False,
	)
	updated_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True),
		server_default=func.now(),
		onupdate=func.now(),
		nullable=False,
	)

	__table_args__ = (
		Index("idx_annotation_document_page", "document_id", "page_number"),
		Index("idx_annotation_tenant", "tenant_id"),
		Index("idx_annotation_created_by", "created_by_id"),
	)

	def __repr__(self) -> str:
		return (
			f"DocumentAnnotation(id={self.id}, doc={self.document_id}, "
			f"page={self.page_number}, type={self.annotation_type})"
		)

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import Float, Index, String, Text, func
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from papermerge.core.db.base import Base


class DocumentSignatureRequest(Base):
	"""
	A request for someone to digitally sign a document.
	On signing, a base64 PNG of the drawn signature is stamped onto the
	specified page at (x, y, width, height) expressed as normalised fractions
	(0.0–1.0) of the page dimensions.
	"""
	__tablename__ = "document_signature_requests"

	id: Mapped[UUID] = mapped_column(
		PG_UUID(as_uuid=True),
		primary_key=True,
		server_default=func.gen_random_uuid(),
	)

	document_id: Mapped[str] = mapped_column(String(64), nullable=False)

	requested_from_email: Mapped[str] = mapped_column(String(255), nullable=False)
	requested_from_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")

	requested_by_id: Mapped[str] = mapped_column(String(64), nullable=False)

	# "pending" | "signed" | "declined"
	status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")

	signed_at: Mapped[Optional[datetime]] = mapped_column(
		TIMESTAMP(timezone=True), nullable=True
	)
	declined_at: Mapped[Optional[datetime]] = mapped_column(
		TIMESTAMP(timezone=True), nullable=True
	)
	decline_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

	# base64-encoded PNG of the drawn signature
	signature_data: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

	# Where to stamp the signature on the document
	signature_page: Mapped[int] = mapped_column(nullable=False, default=1)
	signature_x: Mapped[float] = mapped_column(Float, nullable=False, default=0.7)
	signature_y: Mapped[float] = mapped_column(Float, nullable=False, default=0.85)
	signature_width: Mapped[float] = mapped_column(Float, nullable=False, default=0.25)
	signature_height: Mapped[float] = mapped_column(Float, nullable=False, default=0.1)

	# New document version produced after stamping
	signed_document_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

	tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)

	created_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True),
		server_default=func.now(),
		nullable=False,
	)

	__table_args__ = (
		Index("idx_sig_req_document", "document_id"),
		Index("idx_sig_req_status", "status"),
		Index("idx_sig_req_tenant", "tenant_id"),
		Index("idx_sig_req_requested_by", "requested_by_id"),
	)

	def __repr__(self) -> str:
		return (
			f"DocumentSignatureRequest(id={self.id}, doc={self.document_id}, "
			f"from={self.requested_from_email}, status={self.status})"
		)

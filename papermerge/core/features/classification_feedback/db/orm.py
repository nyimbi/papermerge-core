# (c) Copyright Datacraft, 2026
"""Classification feedback ORM model."""
import uuid
from datetime import datetime

from sqlalchemy import String, ForeignKey, Float, Index
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import TIMESTAMP

from papermerge.core.db.base import Base
from papermerge.core.utils.tz import utc_now


class ClassificationFeedback(Base):
	"""Records human corrections to AI-predicted document classifications."""
	__tablename__ = "classification_feedback"

	id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

	# The document being corrected
	document_id: Mapped[uuid.UUID] = mapped_column(
		ForeignKey("nodes.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)

	# What the model predicted (optional — may not always be available)
	predicted_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
	predicted_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

	# What the human said it actually is
	corrected_type: Mapped[str] = mapped_column(String(255), nullable=False)

	# Who made the correction
	feedback_by_id: Mapped[str] = mapped_column(String(255), nullable=False)

	# Tenant scoping
	tenant_id: Mapped[uuid.UUID] = mapped_column(
		ForeignKey("tenants.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)

	created_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), default=utc_now, nullable=False
	)

	__table_args__ = (
		Index("idx_clf_feedback_document", "document_id"),
		Index("idx_clf_feedback_tenant", "tenant_id"),
		Index("idx_clf_feedback_corrected_type", "corrected_type"),
	)

"""ORM model for document templates."""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from papermerge.core.db.base import Base
from papermerge.core.utils.tz import utc_now


class DocumentTemplate(Base):
	__tablename__ = "document_templates"

	id: Mapped[str] = mapped_column(
		String(36),
		primary_key=True,
		default=lambda: str(uuid.uuid4()),
	)
	name: Mapped[str] = mapped_column(String(255), nullable=False)
	description: Mapped[str] = mapped_column(Text, default="", nullable=False)
	category: Mapped[str] = mapped_column(String(100), default="general", nullable=False)

	# FK to documents.node_id (the template PDF itself); nullable — template may have no file
	template_file_id: Mapped[str | None] = mapped_column(
		String(36),
		ForeignKey("documents.node_id", ondelete="SET NULL"),
		nullable=True,
	)

	# JSON array of field definitions:
	# [{name, label, type: "text"|"date"|"number"|"checkbox", required, default_value}]
	field_definitions: Mapped[str] = mapped_column(Text, default="[]", nullable=False)

	is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

	created_by_id: Mapped[str] = mapped_column(
		String(36),
		ForeignKey("users.id", ondelete="RESTRICT"),
		nullable=False,
	)
	tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)

	created_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True),
		default=utc_now,
		nullable=False,
	)
	updated_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True),
		default=utc_now,
		nullable=False,
	)

	use_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

# (c) Copyright Datacraft, 2026
"""ORM model for IMAP email ingestion configuration."""
import uuid
from datetime import datetime

from sqlalchemy import Text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from papermerge.core.db.base import Base


class EmailIngestConfig(Base):
	__tablename__ = "email_ingest_configs"

	id: Mapped[str] = mapped_column(primary_key=True, default=lambda: str(uuid.uuid4()))
	name: Mapped[str] = mapped_column(nullable=False)

	# IMAP server settings
	host: Mapped[str] = mapped_column(nullable=False)
	port: Mapped[int] = mapped_column(nullable=False, default=993)
	username: Mapped[str] = mapped_column(nullable=False)
	# base64-encoded; Fernet-encrypted when IMAP_ENCRYPTION_KEY env var is set
	encrypted_password: Mapped[str] = mapped_column(Text, nullable=False)
	use_ssl: Mapped[bool] = mapped_column(nullable=False, default=True)
	mailbox_folder: Mapped[str] = mapped_column(nullable=False, default="INBOX")

	# Processing state
	last_processed_uid: Mapped[int] = mapped_column(nullable=False, default=0)

	# Routing
	destination_folder_id: Mapped[str | None] = mapped_column(nullable=True)
	project_id: Mapped[str | None] = mapped_column(nullable=True)

	# Scheduling
	is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
	check_interval_minutes: Mapped[int] = mapped_column(nullable=False, default=15)

	# Filtering — empty string means accept from anyone
	allowed_senders: Mapped[str] = mapped_column(Text, nullable=False, default="")

	# Ownership
	tenant_id: Mapped[str] = mapped_column(nullable=False, index=True)
	created_by_id: Mapped[str] = mapped_column(nullable=False)

	# Timestamps & stats
	created_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True),
		nullable=False,
		default=lambda: datetime.utcnow(),
	)
	last_checked_at: Mapped[datetime | None] = mapped_column(
		TIMESTAMP(timezone=True), nullable=True
	)
	documents_ingested: Mapped[int] = mapped_column(nullable=False, default=0)

	def __repr__(self) -> str:
		return f"EmailIngestConfig(id={self.id!r}, name={self.name!r}, host={self.host!r})"

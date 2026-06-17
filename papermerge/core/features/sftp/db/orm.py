# (c) Copyright Datacraft, 2026
"""ORM models for SFTP/FTP ingestion connector."""
import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column, relationship

from papermerge.core.db.base import Base


class SftpConnection(Base):
	__tablename__ = "sftp_connections"

	id: Mapped[str] = mapped_column(primary_key=True, default=lambda: str(uuid.uuid4()))
	name: Mapped[str] = mapped_column(nullable=False)  # display name e.g. "HQ Scanner Drop"
	host: Mapped[str] = mapped_column(nullable=False)
	port: Mapped[int] = mapped_column(nullable=False, default=22)
	username: Mapped[str] = mapped_column(nullable=False)

	# AES-encrypted via Fernet (cryptography package) or base64 placeholder
	password_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
	ssh_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)

	remote_path: Mapped[str] = mapped_column(nullable=False, default="/")
	file_pattern: Mapped[str] = mapped_column(nullable=False, default="*.pdf,*.tiff,*.jpg")
	poll_interval_minutes: Mapped[int] = mapped_column(nullable=False, default=5)

	# Optional destination folder in dArchiva
	destination_folder_id: Mapped[str | None] = mapped_column(nullable=True)

	is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
	last_polled_at: Mapped[datetime | None] = mapped_column(
		TIMESTAMP(timezone=True), nullable=True
	)
	last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
	docs_ingested_total: Mapped[int] = mapped_column(nullable=False, default=0)

	tenant_id: Mapped[str] = mapped_column(nullable=False, index=True)
	created_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True),
		nullable=False,
		default=lambda: datetime.utcnow(),
	)

	# Relationship to downloaded file tracking
	downloaded_files: Mapped[list["SftpDownloadedFile"]] = relationship(
		"SftpDownloadedFile",
		back_populates="connection",
		cascade="all, delete-orphan",
	)

	def __repr__(self) -> str:
		return f"SftpConnection(id={self.id!r}, name={self.name!r}, host={self.host!r})"


class SftpDownloadedFile(Base):
	"""Tracks which remote files have been downloaded to avoid re-ingestion."""
	__tablename__ = "sftp_downloaded_files"

	id: Mapped[str] = mapped_column(primary_key=True, default=lambda: str(uuid.uuid4()))
	connection_id: Mapped[str] = mapped_column(
		ForeignKey("sftp_connections.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	remote_path: Mapped[str] = mapped_column(nullable=False)
	file_size: Mapped[int] = mapped_column(nullable=False, default=0)
	downloaded_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True),
		nullable=False,
		default=lambda: datetime.utcnow(),
	)

	connection: Mapped["SftpConnection"] = relationship(
		"SftpConnection", back_populates="downloaded_files"
	)

	def __repr__(self) -> str:
		return f"SftpDownloadedFile(id={self.id!r}, remote_path={self.remote_path!r})"

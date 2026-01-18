# (c) Copyright Datacraft, 2026
"""Email feature database models."""
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import String, Text, Boolean, Integer, ForeignKey, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from uuid_extensions import uuid7str

from papermerge.core.db.base import Base

if TYPE_CHECKING:
	from papermerge.core.db.models import Document, User


class EmailThreadModel(Base):
	"""Email thread/conversation grouping."""
	__tablename__ = "email_threads"

	id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7str)
	thread_id: Mapped[str] = mapped_column(String(255), index=True, unique=True)
	subject: Mapped[str] = mapped_column(String(1000))
	message_count: Mapped[int] = mapped_column(Integer, default=0)
	first_message_date: Mapped[datetime | None] = mapped_column(DateTime)
	last_message_date: Mapped[datetime | None] = mapped_column(DateTime)
	participants: Mapped[dict | None] = mapped_column(JSON)
	folder_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("nodes.id"))
	owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))

	created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
	updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

	# Relationships
	imports: Mapped[list["EmailImportModel"]] = relationship(back_populates="thread")


class EmailImportModel(Base):
	"""Imported email with metadata."""
	__tablename__ = "email_imports"

	id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7str)
	message_id: Mapped[str] = mapped_column(String(512), index=True, unique=True)
	thread_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("email_threads.id"))
	document_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("documents.id"))

	# Email headers
	subject: Mapped[str | None] = mapped_column(String(1000))
	from_address: Mapped[str] = mapped_column(String(500))
	from_name: Mapped[str | None] = mapped_column(String(255))
	to_addresses: Mapped[list | None] = mapped_column(JSON)
	cc_addresses: Mapped[list | None] = mapped_column(JSON)
	bcc_addresses: Mapped[list | None] = mapped_column(JSON)
	reply_to: Mapped[str | None] = mapped_column(String(500))
	in_reply_to: Mapped[str | None] = mapped_column(String(512))
	references: Mapped[list | None] = mapped_column(JSON)

	# Email content
	body_text: Mapped[str | None] = mapped_column(Text)
	body_html: Mapped[str | None] = mapped_column(Text)
	has_attachments: Mapped[bool] = mapped_column(Boolean, default=False)
	attachment_count: Mapped[int] = mapped_column(Integer, default=0)

	# Dates
	sent_date: Mapped[datetime | None] = mapped_column(DateTime)
	received_date: Mapped[datetime | None] = mapped_column(DateTime)

	# Import metadata
	source: Mapped[str] = mapped_column(String(50))  # upload, imap, api, outlook, gmail
	source_account_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("email_accounts.id"))
	raw_headers: Mapped[dict | None] = mapped_column(JSON)
	import_status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, processing, completed, failed
	import_error: Mapped[str | None] = mapped_column(Text)

	# Ownership
	owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
	folder_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("nodes.id"))

	created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
	updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

	# Relationships
	thread: Mapped["EmailThreadModel | None"] = relationship(back_populates="imports")
	attachments: Mapped[list["EmailAttachmentModel"]] = relationship(back_populates="email_import", cascade="all, delete-orphan")
	document: Mapped["Document | None"] = relationship()


class EmailAttachmentModel(Base):
	"""Email attachment linked to imported document."""
	__tablename__ = "email_attachments"

	id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7str)
	email_import_id: Mapped[str] = mapped_column(String(36), ForeignKey("email_imports.id", ondelete="CASCADE"))
	document_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("documents.id"))

	filename: Mapped[str] = mapped_column(String(500))
	content_type: Mapped[str] = mapped_column(String(255))
	size_bytes: Mapped[int] = mapped_column(Integer)
	content_id: Mapped[str | None] = mapped_column(String(255))  # For inline attachments
	is_inline: Mapped[bool] = mapped_column(Boolean, default=False)
	checksum: Mapped[str | None] = mapped_column(String(64))  # SHA-256

	import_status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, imported, skipped, failed
	import_error: Mapped[str | None] = mapped_column(Text)

	created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

	# Relationships
	email_import: Mapped["EmailImportModel"] = relationship(back_populates="attachments")
	document: Mapped["Document | None"] = relationship()


class EmailAccountModel(Base):
	"""Configured email account for ingestion."""
	__tablename__ = "email_accounts"

	id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7str)
	name: Mapped[str] = mapped_column(String(255))
	account_type: Mapped[str] = mapped_column(String(50))  # imap, graph_api, gmail_api
	email_address: Mapped[str] = mapped_column(String(500))

	# IMAP settings
	imap_host: Mapped[str | None] = mapped_column(String(255))
	imap_port: Mapped[int | None] = mapped_column(Integer)
	imap_use_ssl: Mapped[bool] = mapped_column(Boolean, default=True)
	imap_username: Mapped[str | None] = mapped_column(String(255))
	imap_password_encrypted: Mapped[str | None] = mapped_column(Text)

	# OAuth settings (for Graph API / Gmail)
	oauth_provider: Mapped[str | None] = mapped_column(String(50))  # azure, google
	oauth_tenant_id: Mapped[str | None] = mapped_column(String(100))
	oauth_client_id: Mapped[str | None] = mapped_column(String(255))
	oauth_client_secret_encrypted: Mapped[str | None] = mapped_column(Text)
	oauth_refresh_token_encrypted: Mapped[str | None] = mapped_column(Text)
	oauth_access_token_encrypted: Mapped[str | None] = mapped_column(Text)
	oauth_token_expires: Mapped[datetime | None] = mapped_column(DateTime)

	# Sync settings
	sync_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
	sync_folders: Mapped[list | None] = mapped_column(JSON)  # List of folders to sync
	sync_since_date: Mapped[datetime | None] = mapped_column(DateTime)
	last_sync_at: Mapped[datetime | None] = mapped_column(DateTime)
	last_sync_uid: Mapped[str | None] = mapped_column(String(100))
	sync_interval_minutes: Mapped[int] = mapped_column(Integer, default=15)

	# Target settings
	target_folder_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("nodes.id"))
	auto_process: Mapped[bool] = mapped_column(Boolean, default=True)
	import_attachments: Mapped[bool] = mapped_column(Boolean, default=True)
	attachment_filter: Mapped[list | None] = mapped_column(JSON)  # e.g., ["application/pdf", "image/*"]

	# Status
	is_active: Mapped[bool] = mapped_column(Boolean, default=True)
	connection_status: Mapped[str] = mapped_column(String(20), default="unknown")  # unknown, connected, error
	connection_error: Mapped[str | None] = mapped_column(Text)

	# Ownership
	owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))

	created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
	updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class EmailRuleModel(Base):
	"""Email processing rules for automated handling."""
	__tablename__ = "email_rules"

	id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7str)
	name: Mapped[str] = mapped_column(String(255))
	description: Mapped[str | None] = mapped_column(Text)
	account_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("email_accounts.id"))
	is_active: Mapped[bool] = mapped_column(Boolean, default=True)
	priority: Mapped[int] = mapped_column(Integer, default=100)

	# Conditions (AND logic)
	conditions: Mapped[list] = mapped_column(JSON, default=list)
	# Format: [{"field": "from", "operator": "contains", "value": "@example.com"}, ...]
	# Fields: from, to, cc, subject, body, attachment_name, attachment_type
	# Operators: equals, contains, starts_with, ends_with, matches (regex), exists

	# Actions
	actions: Mapped[list] = mapped_column(JSON, default=list)
	# Format: [{"action": "move_to_folder", "folder_id": "..."}, ...]
	# Actions: move_to_folder, add_tag, set_document_type, skip_import, extract_attachments_only,
	#          notify, run_workflow, set_custom_field

	# Ownership
	owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))

	created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
	updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

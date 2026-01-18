# (c) Copyright Datacraft, 2026
"""Encryption ORM models."""
import uuid
from datetime import datetime
from uuid import UUID
from enum import Enum

from sqlalchemy import String, ForeignKey, Integer, Boolean, Text, func, Index, UniqueConstraint, LargeBinary
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import TIMESTAMP

from papermerge.core.db.base import Base
from papermerge.core.utils.tz import utc_now


class AccessRequestStatus(str, Enum):
	PENDING = "pending"
	APPROVED = "approved"
	DENIED = "denied"
	EXPIRED = "expired"


class KeyEncryptionKey(Base):
	"""Tenant key encryption key (KEK)."""
	__tablename__ = "key_encryption_keys"

	id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
	tenant_id: Mapped[UUID] = mapped_column(
		ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
	)

	key_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
	encrypted_kek: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
	is_active: Mapped[bool] = mapped_column(Boolean, default=True)

	# Timestamps
	created_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), default=utc_now, nullable=False
	)
	rotated_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
	expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

	__table_args__ = (
		UniqueConstraint("tenant_id", "key_version", name="uq_tenant_key_version"),
		Index("idx_kek_tenant_active", "tenant_id", "is_active"),
	)


class DocumentEncryptionKey(Base):
	"""Document encryption key (DEK)."""
	__tablename__ = "document_encryption_keys"

	id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
	document_id: Mapped[UUID] = mapped_column(
		ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False, index=True
	)

	key_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
	encrypted_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
	key_algorithm: Mapped[str] = mapped_column(String(50), default="AES-256-GCM", nullable=False)

	kek_id: Mapped[UUID] = mapped_column(
		ForeignKey("key_encryption_keys.id", ondelete="RESTRICT"), nullable=False
	)

	# Timestamps
	created_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), default=utc_now, nullable=False
	)
	rotated_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

	__table_args__ = (
		UniqueConstraint("document_id", "key_version", name="uq_document_key_version"),
		Index("idx_dek_document", "document_id"),
	)


class HiddenDocumentAccess(Base):
	"""Access request for hidden documents."""
	__tablename__ = "hidden_document_access"

	id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
	document_id: Mapped[UUID] = mapped_column(
		ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False, index=True
	)

	# Request
	requested_by: Mapped[UUID] = mapped_column(
		ForeignKey("users.id", ondelete="CASCADE"), nullable=False
	)
	requested_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), default=utc_now, nullable=False
	)
	reason: Mapped[str] = mapped_column(Text, nullable=False)

	# Approval
	approved_by: Mapped[UUID | None] = mapped_column(
		ForeignKey("users.id", ondelete="SET NULL")
	)
	approved_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

	status: Mapped[str] = mapped_column(
		String(20), default=AccessRequestStatus.PENDING.value, nullable=False
	)
	expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

	# Timestamps
	created_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), default=utc_now, nullable=False
	)

	__table_args__ = (
		Index("idx_hidden_access_document", "document_id"),
		Index("idx_hidden_access_status", "status"),
	)

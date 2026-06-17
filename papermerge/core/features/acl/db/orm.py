"""ORM model for document/folder access control lists."""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from papermerge.core.db.base import Base


class DocumentACL(Base):
	"""
	Per-resource ACL entry granting a principal (user or group) specific
	permissions on a document or folder node.

	Multiple entries per resource are allowed — one per principal.
	"""

	__tablename__ = "document_acls"

	id: Mapped[uuid.UUID] = mapped_column(
		PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
	)

	# What resource this ACL governs
	resource_type: Mapped[str] = mapped_column(String(20), nullable=False)
	resource_id: Mapped[str] = mapped_column(String(36), nullable=False)

	# Who gets the permission
	principal_type: Mapped[str] = mapped_column(String(20), nullable=False)
	principal_id: Mapped[str] = mapped_column(String(36), nullable=False)
	# Denormalized for display without extra joins
	principal_name: Mapped[str] = mapped_column(String(255), nullable=False)

	# Permissions (additive)
	can_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
	can_write: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
	can_delete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
	can_share: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

	# Audit / lifecycle
	granted_by_id: Mapped[str] = mapped_column(String(36), nullable=False)
	tenant_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

	created_at: Mapped[datetime] = mapped_column(
		DateTime(timezone=True),
		server_default=func.now(),
		nullable=False,
	)
	expires_at: Mapped[datetime | None] = mapped_column(
		DateTime(timezone=True), nullable=True
	)

	__table_args__ = (
		CheckConstraint(
			"resource_type IN ('document', 'folder')",
			name="document_acls_resource_type_check",
		),
		CheckConstraint(
			"principal_type IN ('user', 'group')",
			name="document_acls_principal_type_check",
		),
		# One ACL entry per (resource, principal) pair
		UniqueConstraint(
			"resource_type",
			"resource_id",
			"principal_type",
			"principal_id",
			name="uq_document_acls_resource_principal",
		),
		# Fast lookup: what can this principal do on this resource?
		Index("ix_document_acls_resource", "resource_type", "resource_id"),
		Index("ix_document_acls_principal", "principal_type", "principal_id"),
		Index("ix_document_acls_tenant", "tenant_id"),
	)

	def __repr__(self) -> str:
		return (
			f"DocumentACL(id={self.id}, "
			f"{self.resource_type}:{self.resource_id} -> "
			f"{self.principal_type}:{self.principal_id} "
			f"r={self.can_read} w={self.can_write} d={self.can_delete} s={self.can_share})"
		)

	@property
	def is_expired(self) -> bool:
		if self.expires_at is None:
			return False
		return datetime.utcnow() > self.expires_at.replace(tzinfo=None)

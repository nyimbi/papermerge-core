"""
API Keys ORM model.

API keys are tenant-scoped, long-lived credentials for external integrations
(webhooks, CI/CD, scripts). Distinct from api_tokens (user PATs) — these are
attached to a tenant + creating user, not just a user.

Key format: "dak_" + secrets.token_urlsafe(32)
Stored as SHA-256 hash only — plaintext never persisted.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from papermerge.core.db.base import Base


def _utcnow() -> datetime:
	return datetime.now(timezone.utc)


class ApiKey(Base):
	"""
	API key for external integrations.

	Scoped to a tenant, created by a specific user. Stores only the SHA-256
	hash and an 8-char display prefix — plaintext is returned once at creation.
	"""
	__tablename__ = "api_keys"

	id: Mapped[uuid.UUID] = mapped_column(
		PGUUID(as_uuid=True),
		primary_key=True,
		default=uuid.uuid4,
	)

	# Human-readable label (e.g. "Production webhook", "CI pipeline")
	name: Mapped[str] = mapped_column(String(255), nullable=False)

	# SHA-256 hex digest of the plaintext key — primary auth lookup column
	key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

	# First 8 chars of the full key for UI display (e.g. "dak_xyz1")
	key_prefix: Mapped[str] = mapped_column(String(12), nullable=False)

	# JSON array of scope strings e.g. '["read", "write", "webhooks"]'
	scopes: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

	last_used_at: Mapped[datetime | None] = mapped_column(
		DateTime(timezone=True), nullable=True
	)

	expires_at: Mapped[datetime | None] = mapped_column(
		DateTime(timezone=True), nullable=True
	)

	is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

	created_by_id: Mapped[uuid.UUID] = mapped_column(
		PGUUID(as_uuid=True),
		ForeignKey("users.id", ondelete="CASCADE"),
		nullable=False,
	)

	tenant_id: Mapped[uuid.UUID] = mapped_column(
		PGUUID(as_uuid=True),
		ForeignKey("tenants.id", ondelete="CASCADE"),
		nullable=False,
	)

	created_at: Mapped[datetime] = mapped_column(
		DateTime(timezone=True),
		nullable=False,
		default=_utcnow,
	)

	__table_args__ = (
		Index("idx_api_keys_key_hash", "key_hash"),
		Index("idx_api_keys_tenant_id", "tenant_id"),
		Index("idx_api_keys_created_by_id", "created_by_id"),
	)

	def __repr__(self) -> str:
		return f"<ApiKey(id={self.id}, name={self.name!r}, prefix={self.key_prefix!r})>"

	@property
	def is_expired(self) -> bool:
		if self.expires_at is None:
			return False
		return datetime.now(timezone.utc) > self.expires_at

	@property
	def scope_list(self) -> list[str]:
		import json
		try:
			return json.loads(self.scopes)
		except Exception:
			return []

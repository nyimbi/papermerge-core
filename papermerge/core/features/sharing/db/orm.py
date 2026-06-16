import uuid
import secrets
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, Integer, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from papermerge.core.db.base import Base


class DocumentShareLink(Base):
    """Expiring, optionally password-protected share link for a document."""

    __tablename__ = "document_share_links"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,
    )

    token: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
        default=lambda: secrets.token_urlsafe(32),
    )

    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    max_views: Mapped[int | None] = mapped_column(Integer, nullable=True)
    view_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        nullable=False, default=datetime.utcnow
    )

    __table_args__ = (
        Index("ix_document_share_links_document_id", "document_id"),
        Index("ix_document_share_links_token", "token", unique=True),
        Index("ix_document_share_links_tenant_id", "tenant_id"),
    )

    def __repr__(self) -> str:
        return (
            f"DocumentShareLink(id={self.id}, document_id={self.document_id}, "
            f"token={self.token!r}, is_active={self.is_active})"
        )

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return datetime.utcnow() > self.expires_at

    @property
    def is_exhausted(self) -> bool:
        if self.max_views is None:
            return False
        return self.view_count >= self.max_views

    @property
    def is_valid(self) -> bool:
        return self.is_active and not self.is_expired and not self.is_exhausted

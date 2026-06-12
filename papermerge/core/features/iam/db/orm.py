import uuid
import secrets
from datetime import datetime

from sqlalchemy import String, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID, ARRAY

from papermerge.core.db.base import Base


class UserInvitation(Base):
	__tablename__ = "user_invitations"

	id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
	email: Mapped[str] = mapped_column(String, nullable=False)
	invited_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
	status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
	token: Mapped[str] = mapped_column(String, unique=True, nullable=False, default=lambda: secrets.token_urlsafe(32))
	role_ids: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
	created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
	expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
	accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
	last_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
	tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

	def __repr__(self) -> str:
		return f"UserInvitation(email={self.email!r}, status={self.status!r})"

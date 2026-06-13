import uuid
from datetime import datetime

from sqlalchemy import String, Integer, LargeBinary, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID

from papermerge.core.db.base import Base


class UserPasskey(Base):
	__tablename__ = "user_passkeys"

	id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
	user_id: Mapped[uuid.UUID] = mapped_column(
		UUID(as_uuid=True),
		ForeignKey("users.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	credential_id: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, unique=True)
	public_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
	sign_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
	name: Mapped[str] = mapped_column(String(255), nullable=False, default="Passkey")
	created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
	last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class WebAuthnChallenge(Base):
	__tablename__ = "webauthn_challenges"

	id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
	user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
	challenge: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
	challenge_type: Mapped[str] = mapped_column(String(20), nullable=False)  # 'registration' | 'authentication'
	created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
	expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

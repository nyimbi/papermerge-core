import uuid
from datetime import datetime

from sqlalchemy import String, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import ARRAY, UUID

from papermerge.core.db.base import Base


class UserMFASettings(Base):
	__tablename__ = "user_mfa_settings"

	id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
	user_id: Mapped[uuid.UUID] = mapped_column(
		UUID(as_uuid=True),
		ForeignKey("users.id", ondelete="CASCADE"),
		unique=True,
		nullable=False,
	)
	totp_secret: Mapped[str | None] = mapped_column(String, nullable=True)
	totp_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
	# Hashed backup codes stored as array
	backup_codes: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
	backup_codes_generated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
	created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
	updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

	def __repr__(self) -> str:
		return f"UserMFASettings(user_id={self.user_id}, totp_enabled={self.totp_enabled})"

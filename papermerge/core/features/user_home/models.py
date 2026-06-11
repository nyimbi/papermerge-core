import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, UniqueConstraint, Index, String, Boolean, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID, JSONB, TIMESTAMP

from papermerge.core.db.base import Base


class UserNotification(Base):
	__tablename__ = "user_notifications"

	id: Mapped[uuid.UUID] = mapped_column(
		UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
	)
	user_id: Mapped[uuid.UUID] = mapped_column(
		UUID(as_uuid=True),
		ForeignKey("users.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	tenant_id: Mapped[str | None] = mapped_column(String, nullable=True)
	type: Mapped[str] = mapped_column(String(32), nullable=False)
	title: Mapped[str] = mapped_column(Text, nullable=False)
	message: Mapped[str] = mapped_column(Text, nullable=False)
	is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
	link: Mapped[str | None] = mapped_column(Text, nullable=True)
	notification_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
	created_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), nullable=False, server_default="now()"
	)
	read_at: Mapped[datetime | None] = mapped_column(
		TIMESTAMP(timezone=True), nullable=True
	)

	def __repr__(self) -> str:
		return f"UserNotification(id={self.id}, user_id={self.user_id}, type={self.type}, is_read={self.is_read})"


class UserFavorite(Base):
	__tablename__ = "user_favorites"

	__table_args__ = (
		UniqueConstraint("user_id", "item_type", "item_id", name="uq_user_favorite_item"),
	)

	id: Mapped[uuid.UUID] = mapped_column(
		UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
	)
	user_id: Mapped[uuid.UUID] = mapped_column(
		UUID(as_uuid=True),
		ForeignKey("users.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	tenant_id: Mapped[str | None] = mapped_column(String, nullable=True)
	item_type: Mapped[str] = mapped_column(String(32), nullable=False)
	item_id: Mapped[str] = mapped_column(String(255), nullable=False)
	title: Mapped[str] = mapped_column(Text, nullable=False)
	path: Mapped[str | None] = mapped_column(Text, nullable=True)
	icon: Mapped[str | None] = mapped_column(String(128), nullable=True)
	pinned_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), nullable=False, server_default="now()"
	)

	def __repr__(self) -> str:
		return f"UserFavorite(id={self.id}, user_id={self.user_id}, item_type={self.item_type}, item_id={self.item_id})"


class UserSearchHistory(Base):
	__tablename__ = "user_search_history"

	__table_args__ = (
		Index("idx_search_history_user_searched_at", "user_id", "searched_at"),
	)

	id: Mapped[uuid.UUID] = mapped_column(
		UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
	)
	user_id: Mapped[uuid.UUID] = mapped_column(
		UUID(as_uuid=True),
		ForeignKey("users.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	query: Mapped[str] = mapped_column(Text, nullable=False)
	filters: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
	result_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
	searched_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), nullable=False, server_default="now()"
	)

	def __repr__(self) -> str:
		return f"UserSearchHistory(id={self.id}, user_id={self.user_id}, query={self.query!r})"

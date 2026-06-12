from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import String, Text, ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from papermerge.core.db.base import Base
from papermerge.core.utils.tz import utc_now


class SystemSettings(Base):
	"""
	Generic key-value settings store keyed by category.

	PK is the category name (e.g. "tenant", "ocr", "email").
	The settings blob is stored as JSONB.
	"""
	__tablename__ = "system_settings"

	id: Mapped[str] = mapped_column(String(100), primary_key=True)
	settings: Mapped[dict] = mapped_column(
		JSONB,
		nullable=False,
		default=dict,
		server_default="{}",
	)
	updated_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True),
		default=utc_now,
		onupdate=func.now(),
		nullable=False,
	)
	updated_by_id: Mapped[str | None] = mapped_column(
		Text,
		ForeignKey("users.id", ondelete="SET NULL"),
		nullable=True,
	)


class WebhookConfig(Base):
	__tablename__ = "webhook_configs"

	id: Mapped[str] = mapped_column(String(36), primary_key=True)
	name: Mapped[str] = mapped_column(String(255), nullable=False)
	url: Mapped[str] = mapped_column(Text, nullable=False)
	# ARRAY of text for event names
	events: Mapped[list] = mapped_column(
		ARRAY(Text),
		nullable=False,
		default=list,
		server_default="{}",
	)
	active: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="true")
	secret: Mapped[str | None] = mapped_column(Text, nullable=True)
	created_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True),
		default=utc_now,
		nullable=False,
	)

	def __repr__(self) -> str:
		return f"WebhookConfig(id={self.id}, name={self.name})"


class NotificationSettings(Base):
	"""Per-user notification preferences stored as JSONB."""
	__tablename__ = "notification_settings"

	user_id: Mapped[str] = mapped_column(
		Text,
		ForeignKey("users.id", ondelete="CASCADE"),
		primary_key=True,
	)
	preferences: Mapped[dict] = mapped_column(
		JSONB,
		nullable=False,
		default=dict,
		server_default="{}",
	)
	updated_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True),
		default=utc_now,
		onupdate=func.now(),
		nullable=False,
	)

	def __repr__(self) -> str:
		return f"NotificationSettings(user_id={self.user_id})"

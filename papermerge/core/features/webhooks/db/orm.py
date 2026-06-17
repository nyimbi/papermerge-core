import uuid
from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from papermerge.core.db.base import Base


class OutboundWebhook(Base):
	__tablename__ = "outbound_webhooks"

	id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
	tenant_id: Mapped[UUID] = mapped_column(
		ForeignKey("tenants.id", ondelete="CASCADE"),
		nullable=False,
	)
	url: Mapped[str] = mapped_column(String(2048), nullable=False)
	# e.g. ["document.created", "document.ocr_complete", "batch.complete"]
	events: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
	# HMAC-SHA256 signing secret (stored as plain string; callers should treat
	# it as opaque / never expose it in list responses)
	secret: Mapped[str] = mapped_column(String(64), nullable=False)
	is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
	created_at: Mapped[datetime] = mapped_column(
		DateTime(timezone=True),
		nullable=False,
		default=datetime.utcnow,
		server_default="now()",
	)
	# Delivery tracking — updated after each attempt
	last_delivery_at: Mapped[datetime | None] = mapped_column(
		DateTime(timezone=True), nullable=True
	)
	last_delivery_status: Mapped[int | None] = mapped_column(Integer, nullable=True)

	deliveries: Mapped[list["WebhookDelivery"]] = relationship(
		back_populates="webhook",
		order_by="WebhookDelivery.created_at.desc()",
		lazy="select",
	)


class WebhookDelivery(Base):
	__tablename__ = "webhook_deliveries"

	id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
	webhook_id: Mapped[UUID] = mapped_column(
		ForeignKey("outbound_webhooks.id", ondelete="CASCADE"),
		nullable=False,
	)
	event_type: Mapped[str] = mapped_column(String(128), nullable=False)
	payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
	# "pending" | "delivered" | "failed"
	status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", server_default="pending")
	attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
	last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
	response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
	response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
	delivered_at: Mapped[datetime | None] = mapped_column(
		DateTime(timezone=True), nullable=True
	)
	created_at: Mapped[datetime] = mapped_column(
		DateTime(timezone=True),
		nullable=False,
		default=datetime.utcnow,
		server_default="now()",
	)

	webhook: Mapped[OutboundWebhook] = relationship(back_populates="deliveries")

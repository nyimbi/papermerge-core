from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


SUPPORTED_EVENTS = [
	"document.created",
	"document.classified",
	"document.ocr_complete",
	"scan.batch_complete",
	"routing.rule_applied",
	"document.expiring",
	"batch.complete",
	"exception.raised",
]


class WebhookCreate(BaseModel):
	model_config = ConfigDict(extra="forbid")

	url: str = Field(..., max_length=2048)
	events: list[str] = Field(..., min_length=1)
	secret: str = Field(..., min_length=8, max_length=64)


class WebhookUpdate(BaseModel):
	model_config = ConfigDict(extra="forbid")

	url: str | None = Field(None, max_length=2048)
	events: list[str] | None = None
	secret: str | None = Field(None, min_length=8, max_length=64)
	is_active: bool | None = None


class WebhookOut(BaseModel):
	model_config = ConfigDict(from_attributes=True)

	id: UUID
	tenant_id: UUID
	url: str
	events: list[str]
	is_active: bool
	created_at: datetime
	last_delivery_at: datetime | None
	last_delivery_status: int | None


class DeliveryOut(BaseModel):
	model_config = ConfigDict(from_attributes=True)

	id: UUID
	webhook_id: UUID
	event_type: str
	payload: dict
	status: str = "pending"
	attempts: int = 0
	last_attempt_at: datetime | None = None
	response_status: int | None
	response_body: str | None
	delivered_at: datetime | None
	created_at: datetime

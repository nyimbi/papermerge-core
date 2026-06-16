import logging
import secrets
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.engine import get_db
from papermerge.core.features.auth import get_current_user
from papermerge.core.features.webhooks.db.orm import OutboundWebhook, WebhookDelivery
from papermerge.core.features.webhooks.schema import (
	DeliveryOut,
	WebhookCreate,
	WebhookOut,
	WebhookUpdate,
)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

logger = logging.getLogger(__name__)

_TENANT_SENTINEL = UUID("00000000-0000-0000-0000-000000000001")


def _tenant_id(user) -> UUID:
	"""Best-effort tenant resolution: prefer user.tenant_id, fall back to user.id."""
	tid = getattr(user, "tenant_id", None)
	return tid if tid else user.id


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@router.get("/", response_model=list[WebhookOut])
async def list_webhooks(
	user=Depends(get_current_user),
	db: AsyncSession = Depends(get_db),
) -> list[WebhookOut]:
	"""List all outbound webhooks for the current tenant."""
	tid = _tenant_id(user)
	result = await db.execute(
		select(OutboundWebhook)
		.where(OutboundWebhook.tenant_id == tid)
		.order_by(OutboundWebhook.created_at.desc())
	)
	rows = result.scalars().all()
	return [WebhookOut.model_validate(r) for r in rows]


@router.post("/", response_model=WebhookOut, status_code=201)
async def create_webhook(
	body: WebhookCreate,
	user=Depends(get_current_user),
	db: AsyncSession = Depends(get_db),
) -> WebhookOut:
	"""Create a new outbound webhook."""
	tid = _tenant_id(user)
	wh = OutboundWebhook(
		tenant_id=tid,
		url=body.url,
		events=body.events,
		secret=body.secret,
	)
	db.add(wh)
	await db.commit()
	await db.refresh(wh)
	logger.info(f"webhook created id={wh.id} tenant={tid} url={wh.url}")
	return WebhookOut.model_validate(wh)


@router.patch("/{webhook_id}", response_model=WebhookOut)
async def update_webhook(
	webhook_id: UUID,
	body: WebhookUpdate,
	user=Depends(get_current_user),
	db: AsyncSession = Depends(get_db),
) -> WebhookOut:
	"""Update URL, events, secret, or active state."""
	tid = _tenant_id(user)
	wh = await _get_owned(db, webhook_id, tid)

	if body.url is not None:
		wh.url = body.url
	if body.events is not None:
		wh.events = body.events
	if body.secret is not None:
		wh.secret = body.secret
	if body.is_active is not None:
		wh.is_active = body.is_active

	await db.commit()
	await db.refresh(wh)
	return WebhookOut.model_validate(wh)


@router.delete("/{webhook_id}", status_code=204)
async def delete_webhook(
	webhook_id: UUID,
	user=Depends(get_current_user),
	db: AsyncSession = Depends(get_db),
) -> None:
	"""Delete a webhook and its delivery history."""
	tid = _tenant_id(user)
	wh = await _get_owned(db, webhook_id, tid)
	await db.delete(wh)
	await db.commit()


@router.get("/{webhook_id}/deliveries", response_model=list[DeliveryOut])
async def list_deliveries(
	webhook_id: UUID,
	limit: int = 50,
	user=Depends(get_current_user),
	db: AsyncSession = Depends(get_db),
) -> list[DeliveryOut]:
	"""Return the most recent delivery log entries for a webhook."""
	tid = _tenant_id(user)
	await _get_owned(db, webhook_id, tid)  # ownership check

	result = await db.execute(
		select(WebhookDelivery)
		.where(WebhookDelivery.webhook_id == webhook_id)
		.order_by(WebhookDelivery.created_at.desc())
		.limit(limit)
	)
	rows = result.scalars().all()
	return [DeliveryOut.model_validate(r) for r in rows]


@router.post("/{webhook_id}/test", response_model=DeliveryOut, status_code=202)
async def test_webhook(
	webhook_id: UUID,
	user=Depends(get_current_user),
	db: AsyncSession = Depends(get_db),
) -> DeliveryOut:
	"""Enqueue a test ping delivery for a webhook."""
	from papermerge.core.tasks import send_task

	tid = _tenant_id(user)
	wh = await _get_owned(db, webhook_id, tid)

	payload = {
		"event_type": "ping",
		"tenant_id": str(tid),
		"triggered_by": str(user.id),
	}

	send_task(
		"darchiva.webhooks.deliver",
		kwargs={
			"webhook_id": str(wh.id),
			"event_type": "ping",
			"payload": payload,
		},
	)

	# Return a placeholder delivery record (not yet persisted)
	import uuid as _uuid
	from datetime import datetime, timezone

	placeholder = WebhookDelivery(
		id=_uuid.uuid4(),
		webhook_id=wh.id,
		event_type="ping",
		payload=payload,
		created_at=datetime.now(timezone.utc),
	)
	return DeliveryOut.model_validate(placeholder)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_owned(
	db: AsyncSession, webhook_id: UUID, tenant_id: UUID
) -> OutboundWebhook:
	result = await db.execute(
		select(OutboundWebhook).where(
			OutboundWebhook.id == webhook_id,
			OutboundWebhook.tenant_id == tenant_id,
		)
	)
	wh = result.scalar_one_or_none()
	if wh is None:
		raise HTTPException(status_code=404, detail="Webhook not found")
	return wh

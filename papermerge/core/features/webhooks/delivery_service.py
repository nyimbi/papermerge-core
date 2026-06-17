"""Webhook delivery service.

High-level async functions for delivering webhook events and emitting
events to all subscribed webhooks for a tenant.

The actual HTTP dispatch is delegated to the Celery task
``darchiva.webhooks.deliver`` so retries and backoff are handled by the
worker pool, not the web process.  When Celery/Redis is unavailable the
delivery is attempted inline (best-effort, no retry).
"""
import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.features.webhooks.db.orm import OutboundWebhook, WebhookDelivery

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def deliver_webhook(
	webhook_id: str,
	event_type: str,
	payload_dict: dict,
	session: AsyncSession,
) -> WebhookDelivery:
	"""Deliver a single webhook event inline.

	Creates a WebhookDelivery record, POSTs the payload with an HMAC-SHA256
	signature, and updates the record with the outcome.

	For queued/retried delivery from background tasks use the
	``darchiva.webhooks.deliver`` Celery task instead.
	"""
	wh = await session.get(OutboundWebhook, uuid.UUID(webhook_id))
	if not wh or not wh.is_active:
		logger.info("deliver_webhook: webhook %s inactive or missing, skipping", webhook_id[:8])
		raise ValueError(f"Webhook {webhook_id} not found or inactive")

	delivery_id = uuid.uuid4()
	body_bytes = json.dumps(payload_dict, separators=(",", ":"), sort_keys=True).encode()
	sig = hmac.new(wh.secret.encode(), body_bytes, hashlib.sha256).hexdigest()

	delivery = WebhookDelivery(
		id=delivery_id,
		webhook_id=wh.id,
		event_type=event_type,
		payload=payload_dict,
		status="pending",
		attempts=0,
	)
	session.add(delivery)
	await session.flush()

	response_status: int | None = None
	response_body: str | None = None
	delivered_at: datetime | None = None
	now = datetime.now(timezone.utc)

	try:
		headers = {
			"Content-Type": "application/json",
			"X-dArchiva-Event": event_type,
			"X-dArchiva-Signature": f"sha256={sig}",
			"X-dArchiva-Delivery": str(delivery_id),
		}
		async with httpx.AsyncClient(timeout=15) as client:
			resp = await client.post(wh.url, content=body_bytes, headers=headers)

		response_status = resp.status_code
		response_body = resp.text[:4096]
		delivered_at = datetime.now(timezone.utc)
		delivery.status = "delivered" if 200 <= response_status < 300 else "failed"
		logger.info(
			"deliver_webhook: %s event=%s http=%s",
			webhook_id[:8], event_type, response_status,
		)

	except Exception as exc:
		delivery.status = "failed"
		response_body = str(exc)[:4096]
		logger.warning("deliver_webhook: inline attempt failed for %s: %s", webhook_id[:8], exc)

	delivery.attempts += 1
	delivery.last_attempt_at = now
	delivery.response_status = response_status
	delivery.response_body = response_body
	delivery.delivered_at = delivered_at
	wh.last_delivery_at = delivered_at or now
	wh.last_delivery_status = response_status

	await session.commit()
	await session.refresh(delivery)
	return delivery


async def emit_event(
	event_type: str,
	payload: dict,
	tenant_id: str,
	session: AsyncSession,
) -> list[str]:
	"""Fan-out an event to all active webhooks subscribed to it for tenant.

	Queues a Celery deliver task per webhook (falls back to send_task no-op
	when Redis is absent).  Returns the list of webhook IDs that were queued.
	"""
	from papermerge.core.tasks import send_task

	result = await session.execute(
		select(OutboundWebhook).where(
			OutboundWebhook.tenant_id == uuid.UUID(tenant_id),
			OutboundWebhook.is_active == True,  # noqa: E712
		)
	)
	webhooks = result.scalars().all()

	queued: list[str] = []
	for wh in webhooks:
		if event_type in (wh.events or []):
			send_task(
				"darchiva.webhooks.deliver",
				kwargs={
					"webhook_id": str(wh.id),
					"event_type": event_type,
					"payload": payload,
				},
			)
			queued.append(str(wh.id))
			logger.debug(
				"emit_event: queued %s -> webhook %s", event_type, str(wh.id)[:8]
			)

	return queued


async def retry_delivery(
	delivery_id: str,
	session: AsyncSession,
) -> WebhookDelivery:
	"""Re-attempt a failed or pending delivery immediately (inline).

	Fetches the original payload and webhook config, then calls
	``deliver_webhook`` to perform a fresh HTTP attempt.
	"""
	delivery = await session.get(WebhookDelivery, uuid.UUID(delivery_id))
	if not delivery:
		raise ValueError(f"Delivery {delivery_id} not found")

	# Reset to pending so deliver_webhook picks it up fresh
	delivery.status = "pending"
	await session.flush()

	return await deliver_webhook(
		webhook_id=str(delivery.webhook_id),
		event_type=delivery.event_type,
		payload_dict=delivery.payload,
		session=session,
	)

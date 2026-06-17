# (c) Copyright Datacraft, 2026
"""
Notification publisher — async and sync interfaces.

Async:  await publish_notification(tenant_id, event, data)
Sync:   publish_notification_sync(tenant_id, event, data)  — safe to call from Celery tasks.

Events
------
batch_status_changed  : a scan batch moved to a new status
sla_breach            : an SLA deadline was exceeded
exception_raised      : an unhandled exception surfaced in a pipeline stage
scan_complete         : a scanning project finished all batches
classification_done   : AI document classification finished
"""
import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

KNOWN_EVENTS = frozenset({
	"batch_status_changed",
	"sla_breach",
	"exception_raised",
	"scan_complete",
	"classification_done",
})


def _get_redis_url() -> str:
	url = os.environ.get("PM_REDIS_URL")
	if url:
		return url
	try:
		from papermerge.core.config import get_settings
		settings = get_settings()
		if settings.redis_url:
			return str(settings.redis_url)
	except Exception:
		pass
	return "redis://localhost:6379/0"


def _channel_name(tenant_id: str) -> str:
	return f"darchiva:notifications:{tenant_id}"


def _build_payload(event: str, data: dict[str, Any]) -> str:
	return json.dumps({
		"event": event,
		"data": data,
		"timestamp": datetime.now(timezone.utc).isoformat(),
	})


# ---------------------------------------------------------------------------
# Async API
# ---------------------------------------------------------------------------

async def publish_notification(
	tenant_id: str,
	event: str,
	data: dict[str, Any],
) -> None:
	"""
	Publish a notification to all WebSocket clients in *tenant_id*.

	Also delivers directly to any in-process WebSocket connections via the
	module-level ConnectionManager (useful in single-process dev/test setups
	where Redis may not be running).
	"""
	payload = _build_payload(event, data)

	# In-process delivery (zero-latency for same-process connections).
	try:
		from papermerge.core.features.notifications.websocket import manager
		await manager.broadcast_to_tenant(tenant_id, payload)
	except Exception as exc:
		logger.debug("In-process broadcast failed: %s", exc)

	# Redis pub/sub delivery (cross-process / multi-worker).
	try:
		import redis.asyncio as aioredis

		redis_url = _get_redis_url()
		async with aioredis.from_url(redis_url, decode_responses=True) as client:
			channel = _channel_name(tenant_id)
			await client.publish(channel, payload)
			logger.debug("Published %s to %s", event, channel)
	except ImportError:
		logger.debug("redis-py not available; skipping Redis publish for event=%s", event)
	except Exception as exc:
		logger.warning("Redis publish failed (event=%s, tenant=%s): %s", event, tenant_id, exc)


# ---------------------------------------------------------------------------
# Sync API — Celery-safe
# ---------------------------------------------------------------------------

def publish_notification_sync(
	tenant_id: str,
	event: str,
	data: dict[str, Any],
) -> None:
	"""
	Synchronous wrapper around :func:`publish_notification`.

	Uses ``redis-py``'s synchronous client directly (no event loop required),
	making it safe to call from Celery task workers.
	"""
	payload = _build_payload(event, data)

	try:
		import redis as sync_redis

		redis_url = _get_redis_url()
		client = sync_redis.from_url(redis_url, decode_responses=True)
		channel = _channel_name(tenant_id)
		client.publish(channel, payload)
		client.close()
		logger.debug("Sync-published %s to %s", event, channel)
	except ImportError:
		logger.debug("redis-py not available; skipping sync Redis publish for event=%s", event)
	except Exception as exc:
		logger.warning("Sync Redis publish failed (event=%s, tenant=%s): %s", event, tenant_id, exc)

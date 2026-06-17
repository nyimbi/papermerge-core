# (c) Copyright Datacraft, 2026
"""
WebSocket endpoint and connection manager for real-time dArchiva notifications.

Clients connect to GET /ws/notifications?token=<bearer_token>.
Messages are pushed from Redis pub/sub channel darchiva:notifications:{tenant_id}.
"""
import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from uuid import UUID

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Connection manager
# ---------------------------------------------------------------------------

class NotificationConnectionManager:
	"""Track open WebSocket connections, keyed by tenant_id."""

	def __init__(self):
		# tenant_id -> list[WebSocket]
		self._connections: dict[str, list[WebSocket]] = {}
		# websocket -> tenant_id  (reverse index for O(1) disconnect lookup)
		self._ws_tenant: dict[WebSocket, str] = {}

	async def connect(self, websocket: WebSocket, tenant_id: str) -> None:
		await websocket.accept()
		self._connections.setdefault(tenant_id, []).append(websocket)
		self._ws_tenant[websocket] = tenant_id
		logger.debug("WS connect: tenant=%s total=%d", tenant_id, len(self._connections[tenant_id]))

	def disconnect(self, websocket: WebSocket) -> None:
		tenant_id = self._ws_tenant.pop(websocket, None)
		if tenant_id and tenant_id in self._connections:
			try:
				self._connections[tenant_id].remove(websocket)
			except ValueError:
				pass
			if not self._connections[tenant_id]:
				del self._connections[tenant_id]
		logger.debug("WS disconnect: tenant=%s", tenant_id)

	async def broadcast_to_tenant(self, tenant_id: str, message: str) -> None:
		"""Send a raw JSON string to every socket in a tenant."""
		sockets = list(self._connections.get(tenant_id, []))
		dead: list[WebSocket] = []
		for ws in sockets:
			try:
				await ws.send_text(message)
			except Exception as exc:
				logger.warning("Failed to send to socket (tenant=%s): %s", tenant_id, exc)
				dead.append(ws)
		for ws in dead:
			self.disconnect(ws)


# Module-level singleton used by the WebSocket handler and publisher.
manager = NotificationConnectionManager()


# ---------------------------------------------------------------------------
# Redis pub/sub helpers
# ---------------------------------------------------------------------------

def _get_redis_url() -> str:
	"""Resolve Redis URL from settings or environment (matches celery_app.py precedence)."""
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


# ---------------------------------------------------------------------------
# WebSocket handler
# ---------------------------------------------------------------------------

async def notifications_handler(websocket: WebSocket, tenant_id: str) -> None:
	"""
	Long-lived WebSocket handler.

	Subscribes to the Redis pub/sub channel for the tenant and forwards every
	published JSON message to the connected client.  Also handles client-sent
	"ping" -> "pong" keepalives.
	"""
	await manager.connect(websocket, tenant_id)

	redis_client = None
	pubsub = None

	try:
		import redis.asyncio as aioredis  # redis-py >= 4.2 ships this sub-package

		redis_url = _get_redis_url()
		redis_client = aioredis.from_url(redis_url, decode_responses=True)
		pubsub = redis_client.pubsub()
		channel = _channel_name(tenant_id)
		await pubsub.subscribe(channel)
		logger.info("WS subscribed to %s", channel)

		async def _redis_reader() -> None:
			"""Forward Redis messages to the WebSocket."""
			async for message in pubsub.listen():
				if message["type"] != "message":
					continue
				data = message.get("data", "")
				if isinstance(data, str):
					try:
						await websocket.send_text(data)
					except Exception as exc:
						logger.debug("Send failed, closing redis reader: %s", exc)
						break

		async def _ws_reader() -> None:
			"""Read client messages; echo pong for ping, ignore everything else."""
			while True:
				try:
					text = await asyncio.wait_for(websocket.receive_text(), timeout=60.0)
					if text == "ping":
						await websocket.send_text("pong")
				except asyncio.TimeoutError:
					# No message for 60 s — send a server-side keepalive ping.
					try:
						await websocket.send_text("ping")
					except Exception:
						break
				except WebSocketDisconnect:
					break
				except Exception:
					break

		# Run both coroutines concurrently; cancel the other when one finishes.
		redis_task = asyncio.create_task(_redis_reader())
		ws_task = asyncio.create_task(_ws_reader())

		done, pending = await asyncio.wait(
			{redis_task, ws_task},
			return_when=asyncio.FIRST_COMPLETED,
		)
		for t in pending:
			t.cancel()
			try:
				await t
			except (asyncio.CancelledError, Exception):
				pass

	except WebSocketDisconnect:
		logger.debug("WS disconnected cleanly: tenant=%s", tenant_id)
	except ImportError:
		# redis-py not installed — fall back to a simple polling loop with no
		# Redis integration so the endpoint at least doesn't 500.
		logger.warning("redis-py not available; WebSocket notifications disabled for tenant=%s", tenant_id)
		try:
			while True:
				text = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
				if text == "ping":
					await websocket.send_text("pong")
		except (asyncio.TimeoutError, WebSocketDisconnect, Exception):
			pass
	except Exception as exc:
		logger.exception("Unexpected WS error for tenant=%s: %s", tenant_id, exc)
	finally:
		manager.disconnect(websocket)
		if pubsub is not None:
			try:
				await pubsub.unsubscribe()
				await pubsub.close()
			except Exception:
				pass
		if redis_client is not None:
			try:
				await redis_client.aclose()
			except Exception:
				pass

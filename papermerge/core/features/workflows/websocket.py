# (c) Copyright Datacraft, 2026
"""WebSocket handler for real-time workflow notifications."""
import asyncio
import logging
from uuid import UUID
from typing import Any
from datetime import datetime

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class WorkflowNotification(BaseModel):
	"""Notification payload for WebSocket messages."""
	event_type: str  # approval_created, deadline_reminder, escalation, sla_breach
	title: str
	message: str
	severity: str = "info"  # info, warning, error
	data: dict = {}
	timestamp: datetime


class ConnectionManager:
	"""Manage WebSocket connections for workflow notifications."""

	def __init__(self):
		# Map user_id -> list of active connections
		self._connections: dict[UUID, list[WebSocket]] = {}
		# Map tenant_id -> list of user_ids (for broadcast)
		self._tenant_users: dict[UUID, set[UUID]] = {}

	async def connect(self, websocket: WebSocket, user_id: UUID, tenant_id: UUID):
		"""Accept a new WebSocket connection."""
		await websocket.accept()

		if user_id not in self._connections:
			self._connections[user_id] = []
		self._connections[user_id].append(websocket)

		if tenant_id not in self._tenant_users:
			self._tenant_users[tenant_id] = set()
		self._tenant_users[tenant_id].add(user_id)

		logger.info(f"WebSocket connected: user={user_id}, tenant={tenant_id}")

	def disconnect(self, websocket: WebSocket, user_id: UUID, tenant_id: UUID):
		"""Remove a WebSocket connection."""
		if user_id in self._connections:
			if websocket in self._connections[user_id]:
				self._connections[user_id].remove(websocket)
			if not self._connections[user_id]:
				del self._connections[user_id]

		if tenant_id in self._tenant_users:
			self._tenant_users[tenant_id].discard(user_id)
			if not self._tenant_users[tenant_id]:
				del self._tenant_users[tenant_id]

		logger.info(f"WebSocket disconnected: user={user_id}")

	async def send_to_user(self, user_id: UUID, notification: WorkflowNotification):
		"""Send notification to a specific user."""
		if user_id not in self._connections:
			return

		message = notification.model_dump_json()
		disconnected = []

		for websocket in self._connections[user_id]:
			try:
				await websocket.send_text(message)
			except Exception as e:
				logger.warning(f"Failed to send to user {user_id}: {e}")
				disconnected.append(websocket)

		# Clean up disconnected sockets
		for ws in disconnected:
			self._connections[user_id].remove(ws)

	async def broadcast_to_tenant(self, tenant_id: UUID, notification: WorkflowNotification):
		"""Broadcast notification to all users in a tenant."""
		if tenant_id not in self._tenant_users:
			return

		for user_id in self._tenant_users[tenant_id]:
			await self.send_to_user(user_id, notification)

	async def broadcast_to_users(self, user_ids: list[UUID], notification: WorkflowNotification):
		"""Send notification to multiple specific users."""
		for user_id in user_ids:
			await self.send_to_user(user_id, notification)


# Global connection manager instance
manager = ConnectionManager()


# Notification helper functions

async def notify_approval_created(
	user_id: UUID,
	approval_request_id: UUID,
	title: str,
	description: str | None = None,
	document_id: UUID | None = None,
	deadline_at: datetime | None = None,
):
	"""Notify user about a new approval request."""
	from papermerge.core.utils.tz import utc_now

	notification = WorkflowNotification(
		event_type="approval_created",
		title="New Approval Request",
		message=f"You have a new approval request: {title}",
		severity="info",
		data={
			"approval_request_id": str(approval_request_id),
			"title": title,
			"description": description,
			"document_id": str(document_id) if document_id else None,
			"deadline_at": deadline_at.isoformat() if deadline_at else None,
		},
		timestamp=utc_now(),
	)
	await manager.send_to_user(user_id, notification)


async def notify_deadline_reminder(
	user_id: UUID,
	approval_request_id: UUID,
	title: str,
	threshold_percent: int,
	deadline_at: datetime,
):
	"""Send deadline reminder notification."""
	from papermerge.core.utils.tz import utc_now

	severity = "info" if threshold_percent < 75 else ("warning" if threshold_percent < 90 else "error")

	notification = WorkflowNotification(
		event_type="deadline_reminder",
		title=f"Deadline Reminder ({threshold_percent}%)",
		message=f"Request '{title}' deadline approaching",
		severity=severity,
		data={
			"approval_request_id": str(approval_request_id),
			"title": title,
			"threshold_percent": threshold_percent,
			"deadline_at": deadline_at.isoformat(),
		},
		timestamp=utc_now(),
	)
	await manager.send_to_user(user_id, notification)


async def notify_escalation(
	user_id: UUID,
	approval_request_id: UUID,
	title: str,
	escalation_level: int,
	escalated_from: UUID | None = None,
):
	"""Notify user about an escalated approval request."""
	from papermerge.core.utils.tz import utc_now

	notification = WorkflowNotification(
		event_type="escalation",
		title="Escalated Request",
		message=f"Request '{title}' has been escalated to you (level {escalation_level})",
		severity="warning",
		data={
			"approval_request_id": str(approval_request_id),
			"title": title,
			"escalation_level": escalation_level,
			"escalated_from": str(escalated_from) if escalated_from else None,
		},
		timestamp=utc_now(),
	)
	await manager.send_to_user(user_id, notification)


async def notify_sla_breach(
	user_id: UUID,
	alert_id: UUID,
	title: str,
	message: str,
	workflow_id: UUID | None = None,
	instance_id: UUID | None = None,
):
	"""Notify user about an SLA breach."""
	from papermerge.core.utils.tz import utc_now

	notification = WorkflowNotification(
		event_type="sla_breach",
		title="SLA Breach Alert",
		message=message,
		severity="error",
		data={
			"alert_id": str(alert_id),
			"title": title,
			"workflow_id": str(workflow_id) if workflow_id else None,
			"instance_id": str(instance_id) if instance_id else None,
		},
		timestamp=utc_now(),
	)
	await manager.send_to_user(user_id, notification)


async def notify_delegation(
	user_id: UUID,
	approval_request_id: UUID,
	title: str,
	delegated_from_name: str,
	reason: str | None = None,
):
	"""Notify user about a delegated approval request."""
	from papermerge.core.utils.tz import utc_now

	notification = WorkflowNotification(
		event_type="delegation",
		title="Delegated Request",
		message=f"'{title}' delegated to you by {delegated_from_name}",
		severity="info",
		data={
			"approval_request_id": str(approval_request_id),
			"title": title,
			"delegated_from_name": delegated_from_name,
			"reason": reason,
		},
		timestamp=utc_now(),
	)
	await manager.send_to_user(user_id, notification)


# WebSocket endpoint handler
async def workflow_notifications_handler(
	websocket: WebSocket,
	user_id: UUID,
	tenant_id: UUID,
):
	"""
	WebSocket handler for workflow notifications.

	Mount this in your FastAPI app:
		@app.websocket("/ws/workflows/notifications")
		async def ws_notifications(websocket: WebSocket, ...):
			await workflow_notifications_handler(websocket, user.id, user.tenant_id)
	"""
	await manager.connect(websocket, user_id, tenant_id)

	try:
		while True:
			# Keep connection alive, handle any client messages
			data = await websocket.receive_text()

			# Client can send ping/pong or acknowledgments
			if data == "ping":
				await websocket.send_text("pong")

	except WebSocketDisconnect:
		manager.disconnect(websocket, user_id, tenant_id)
	except Exception as e:
		logger.exception(f"WebSocket error for user {user_id}: {e}")
		manager.disconnect(websocket, user_id, tenant_id)

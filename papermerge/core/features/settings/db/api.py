from __future__ import annotations

from typing import Any

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.features.settings.db.orm import (
	SystemSettings,
	WebhookConfig,
	NotificationSettings,
)
from papermerge.core.utils.tz import utc_now


async def get_settings(session: AsyncSession, category: str) -> dict[str, Any]:
	"""Return raw settings dict for *category*, or {} if not yet persisted."""
	stmt = select(SystemSettings).where(SystemSettings.id == category)
	result = await session.execute(stmt)
	row = result.scalar_one_or_none()
	if row is None:
		return {}
	return row.settings or {}


async def upsert_settings(
	session: AsyncSession,
	category: str,
	data: dict[str, Any],
	updated_by_id: str | None = None,
) -> dict[str, Any]:
	"""Merge *data* into existing settings for *category* and persist."""
	stmt = select(SystemSettings).where(SystemSettings.id == category)
	result = await session.execute(stmt)
	row = result.scalar_one_or_none()

	if row is None:
		row = SystemSettings(
			id=category,
			settings=data,
			updated_by_id=updated_by_id,
		)
		session.add(row)
	else:
		merged = {**(row.settings or {}), **data}
		row.settings = merged
		row.updated_by_id = updated_by_id

	await session.commit()
	await session.refresh(row)
	return row.settings


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------

async def get_webhooks(session: AsyncSession) -> list[WebhookConfig]:
	result = await session.execute(select(WebhookConfig))
	return list(result.scalars().all())


async def create_webhook(session: AsyncSession, data: dict[str, Any]) -> WebhookConfig:
	from uuid6 import uuid7
	hook = WebhookConfig(
		id=str(uuid7()),
		name=data["name"],
		url=data["url"],
		events=data.get("events", []),
		active=data.get("active", True),
		secret=data.get("secret"),
	)
	session.add(hook)
	await session.commit()
	await session.refresh(hook)
	return hook


async def update_webhook(
	session: AsyncSession,
	id: str,
	data: dict[str, Any],
) -> WebhookConfig | None:
	stmt = select(WebhookConfig).where(WebhookConfig.id == id)
	result = await session.execute(stmt)
	hook = result.scalar_one_or_none()
	if hook is None:
		return None

	for field, value in data.items():
		if value is not None and hasattr(hook, field):
			setattr(hook, field, value)

	await session.commit()
	await session.refresh(hook)
	return hook


async def delete_webhook(session: AsyncSession, id: str) -> bool:
	stmt = delete(WebhookConfig).where(WebhookConfig.id == id)
	result = await session.execute(stmt)
	await session.commit()
	return result.rowcount > 0


# ---------------------------------------------------------------------------
# Notification preferences (per-user)
# ---------------------------------------------------------------------------

async def get_notification_prefs(session: AsyncSession, user_id: str) -> dict[str, Any]:
	stmt = select(NotificationSettings).where(NotificationSettings.user_id == user_id)
	result = await session.execute(stmt)
	row = result.scalar_one_or_none()
	if row is None:
		return {}
	return row.preferences or {}


async def upsert_notification_prefs(
	session: AsyncSession,
	user_id: str,
	data: dict[str, Any],
) -> dict[str, Any]:
	stmt = select(NotificationSettings).where(NotificationSettings.user_id == user_id)
	result = await session.execute(stmt)
	row = result.scalar_one_or_none()

	if row is None:
		row = NotificationSettings(user_id=user_id, preferences=data)
		session.add(row)
	else:
		merged = {**(row.preferences or {}), **data}
		row.preferences = merged

	await session.commit()
	await session.refresh(row)
	return row.preferences

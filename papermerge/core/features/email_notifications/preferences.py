# (c) Copyright Datacraft, 2026
"""
Per-user email notification preferences for dArchiva scanning events.

Storage is delegated to the existing NotificationSettings ORM table
(settings/db/api.py).  No new ORM models are introduced.

Preference keys (all boolean except `notification_email`):
  batch_complete    — email on batch → complete
  sla_breach        — email on SLA warning/critical
  exceptions        — email on processing exceptions
  weekly_summary    — weekly KPI digest
  notification_email — override address (falls back to user.email if blank)
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.features.settings.db.api import (
	get_notification_prefs,
	upsert_notification_prefs,
)

# Keys this feature manages — kept isolated from the general notification prefs.
_KEYS = frozenset({
	"batch_complete",
	"sla_breach",
	"exceptions",
	"weekly_summary",
	"notification_email",
})

_DEFAULTS: dict[str, Any] = {
	"batch_complete": True,
	"sla_breach": True,
	"exceptions": True,
	"weekly_summary": False,
	"notification_email": "",
}


def _extract(raw: dict[str, Any]) -> dict[str, Any]:
	"""Pull only our keys out of the full preferences blob."""
	return {k: raw.get(k, _DEFAULTS[k]) for k in _DEFAULTS}


async def get_email_prefs(session: AsyncSession, user_id: str) -> dict[str, Any]:
	"""Return dArchiva email notification prefs for *user_id*."""
	raw = await get_notification_prefs(session, user_id)
	return _extract(raw)


async def upsert_email_prefs(
	session: AsyncSession,
	user_id: str,
	data: dict[str, Any],
) -> dict[str, Any]:
	"""
	Merge *data* (only recognised keys) into the user's notification prefs
	and return the updated dArchiva slice.
	"""
	filtered = {k: v for k, v in data.items() if k in _KEYS}
	raw = await upsert_notification_prefs(session, user_id, filtered)
	return _extract(raw)

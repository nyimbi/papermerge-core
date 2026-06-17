# (c) Copyright Datacraft, 2026
"""Celery task for document expiry reminder notifications.

WIRING NEEDED: Add to celery_app.py:
    task_routes:
        "darchiva.expiry.check_reminders": {"queue": prefixed("core")}
    beat_schedule:
        "expiry-reminders": {
            "task": "darchiva.expiry.check_reminders",
            "schedule": 86400.0,   # once per day
        }
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from celery import shared_task

_log = logging.getLogger(__name__)


def _now_utc() -> datetime:
	return datetime.now(timezone.utc).replace(tzinfo=None)


@shared_task(
	bind=True,
	max_retries=3,
	default_retry_delay=300,
	name="darchiva.expiry.check_reminders",
)
def check_expiry_reminders(self) -> dict:
	"""Daily sweep: fire reminder notifications for documents approaching expiry.

	For each DocumentExpiry record:
	  - Computes days until expiry
	  - For each day threshold in reminder_days: if days_until_expiry <= threshold
	    AND threshold not already in notified_milestones → send notification + record milestone
	"""
	import asyncio

	from sqlalchemy import select

	from papermerge.core.db.engine import get_session
	from papermerge.core.features.expiry.db.orm import DocumentExpiry

	async def _run() -> dict:
		fired = 0
		errors = 0
		now = _now_utc()

		async with get_session() as session:
			stmt = select(DocumentExpiry).where(DocumentExpiry.expires_at >= now)
			result = await session.execute(stmt)
			records = result.scalars().all()

			for record in records:
				try:
					reminder_days: list[int] = json.loads(record.reminder_days or "[]")
					notified: list[int] = json.loads(record.notified_milestones or "[]")

					delta = record.expires_at - now
					days_until = delta.days  # may be negative if somehow past — skip those

					if days_until < 0:
						continue

					for threshold in reminder_days:
						if days_until <= threshold and threshold not in notified:
							_send_expiry_notification(
								document_id=record.document_id,
								tenant_id=record.tenant_id,
								created_by_id=record.created_by_id,
								days_until=days_until,
								threshold=threshold,
								expires_at=record.expires_at,
							)
							notified.append(threshold)
							fired += 1

					record.notified_milestones = json.dumps(sorted(set(notified), reverse=True))
					record.updated_at = now

				except Exception as exc:
					_log.warning(
						"check_expiry_reminders: failed for doc=%s: %s",
						record.document_id,
						exc,
					)
					errors += 1

			await session.commit()

		_log.info(
			"check_expiry_reminders: complete — fired=%d errors=%d total=%d",
			fired,
			errors,
			len(records),
		)
		return {"fired": fired, "errors": errors, "total": len(records)}

	try:
		return asyncio.run(_run())
	except Exception as exc:
		_log.error("check_expiry_reminders: task error: %s", exc)
		raise self.retry(exc=exc)


def _send_expiry_notification(
	*,
	document_id: str,
	tenant_id: str,
	created_by_id: str | None,
	days_until: int,
	threshold: int,
	expires_at: datetime,
) -> None:
	"""Attempt to send a notification via the notifications feature.

	Falls back to a log warning if the notifications feature is unavailable.
	"""
	_log.info(
		"expiry reminder: doc=%s days_until=%d threshold=%d expires=%s",
		document_id,
		days_until,
		threshold,
		expires_at.isoformat(),
	)

	# Attempt in-app notification if we have a user to notify
	if created_by_id is None:
		_log.debug("expiry reminder: no created_by_id for doc=%s, skipping in-app notification", document_id)
		return

	try:
		from papermerge.core.features.notifications.schema import NotificationCreate
		from papermerge.core.features.notifications.publisher import publish_notification

		if days_until == 0:
			urgency = "expires TODAY"
		elif days_until == 1:
			urgency = "expires TOMORROW"
		else:
			urgency = f"expires in {days_until} days"

		notif = NotificationCreate(
			user_id=created_by_id,
			type="warning",
			title=f"Document expiry reminder",
			message=f"Document {document_id!r} {urgency} (on {expires_at.strftime('%Y-%m-%d')}).",
			link=f"/documents/{document_id}",
		)
		publish_notification(notif)
	except Exception as exc:
		_log.warning(
			"expiry reminder: could not send in-app notification for doc=%s: %s",
			document_id,
			exc,
		)

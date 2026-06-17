# (c) Copyright Datacraft, 2026
"""Celery tasks for IMAP email ingestion.

# WIRING NEEDED: add to celery_app.py:
#
# task_routes:
#   "darchiva.email_ingest.check_mailbox":  {"queue": prefixed("core")}
#   "darchiva.email_ingest.check_all":      {"queue": prefixed("core")}
#
# beat_schedule:
#   "email-ingest": {
#       "task": "darchiva.email_ingest.check_all",
#       "schedule": 900.0,   # every 15 minutes
#   }
"""
import asyncio
import logging
from datetime import datetime, timezone

from celery import shared_task

logger = logging.getLogger(__name__)


async def _check_one(config_id: str) -> int:
	from papermerge.core.db.engine import get_async_session_maker
	from papermerge.core.features.email_ingest.db.orm import EmailIngestConfig
	from papermerge.core.features.email_ingest.service import check_mailbox

	async_session = get_async_session_maker()
	async with async_session() as session:
		config = await session.get(EmailIngestConfig, config_id)
		if not config:
			logger.error("EmailIngestConfig not found: %s", config_id)
			return 0
		if not config.is_active:
			return 0
		return await check_mailbox(config, session)


@shared_task(
	bind=True,
	max_retries=3,
	default_retry_delay=60,
	name="darchiva.email_ingest.check_mailbox",
)
def check_mailbox_task(self, config_id: str) -> int:
	"""Check one IMAP config for new messages and queue attachments for ingestion."""
	logger.info("email_ingest.check_mailbox: config=%s", config_id[:8])
	try:
		return asyncio.run(_check_one(config_id))
	except Exception as exc:
		logger.warning(
			"email_ingest.check_mailbox failed config=%s retry=%d/%d: %s",
			config_id[:8], self.request.retries, self.max_retries, exc,
		)
		raise self.retry(exc=exc)


@shared_task(name="darchiva.email_ingest.check_all")
def check_all_mailboxes() -> dict:
	"""Fan-out check_mailbox_task for every active EmailIngestConfig that is due.

	Called by Celery beat every 15 minutes.  Respects per-config
	check_interval_minutes so a config with interval=60 is only polled
	once per hour even though the beat fires every 15 min.
	"""
	logger.info("email_ingest.check_all: scanning active configs")

	async def _find_due() -> list[str]:
		from papermerge.core.db.engine import get_async_session_maker
		from papermerge.core.features.email_ingest.db.orm import EmailIngestConfig
		from sqlalchemy import select

		async_session = get_async_session_maker()
		now = datetime.now(tz=timezone.utc)

		async with async_session() as session:
			stmt = select(EmailIngestConfig).where(EmailIngestConfig.is_active.is_(True))
			result = await session.execute(stmt)
			configs = result.scalars().all()

			due = []
			for c in configs:
				if c.last_checked_at is None:
					due.append(c.id)
					continue
				# last_checked_at may be naive (utcnow) or tz-aware
				last = c.last_checked_at
				if last.tzinfo is None:
					last = last.replace(tzinfo=timezone.utc)
				elapsed_min = (now - last).total_seconds() / 60
				if elapsed_min >= c.check_interval_minutes:
					due.append(c.id)
			return due

	due_ids = asyncio.run(_find_due())
	queued = 0
	for cid in due_ids:
		check_mailbox_task.delay(cid)
		queued += 1

	logger.info("email_ingest.check_all: queued=%d", queued)
	return {"queued": queued}

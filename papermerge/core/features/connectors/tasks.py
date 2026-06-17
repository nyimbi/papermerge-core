# (c) Copyright Datacraft, 2026
"""Celery task: periodic sync of all active external connectors.

WIRING NEEDED: Add to celery_app.py:

  task_routes["darchiva.connectors.sync_all"] = {"queue": prefixed("core")}

  beat_schedule["connector-sync"] = {
      "task": "darchiva.connectors.sync_all",
      "schedule": 3600.0,  # every hour; individual connectors use sync_interval_minutes
  }
"""
from __future__ import annotations

import asyncio
import logging

from celery import shared_task

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Async implementation
# ---------------------------------------------------------------------------


async def _sync_all() -> dict:
	from sqlalchemy import select

	from papermerge.core.db.engine import get_async_session_maker
	from papermerge.core.features.connectors.db.orm import ConnectorConfig
	from papermerge.core.features.connectors.service import (
		sync_dropbox_folder,
		sync_local_folder,
	)

	async_session = get_async_session_maker()
	results: list[dict] = []

	async with async_session() as session:
		rows = await session.execute(
			select(ConnectorConfig).where(ConnectorConfig.is_active.is_(True))
		)
		configs = list(rows.scalars().all())

	for config in configs:
		try:
			async with async_session() as session:
				if config.connector_type == "dropbox":
					# Re-fetch within session to allow commit
					result = await session.execute(
						select(ConnectorConfig).where(ConnectorConfig.id == config.id)
					)
					obj = result.scalar_one()
					new_files = await sync_dropbox_folder(obj, session)
				elif config.connector_type == "local_folder":
					result = await session.execute(
						select(ConnectorConfig).where(ConnectorConfig.id == config.id)
					)
					obj = result.scalar_one()
					new_files = await sync_local_folder(obj, session)
				else:
					_log.info(
						"sync_all: skipping connector=%s type=%s (not implemented)",
						config.id,
						config.connector_type,
					)
					continue

			results.append(
				{"connector_id": str(config.id), "type": config.connector_type, "new_files": new_files}
			)
			_log.info(
				"sync_all: connector=%s type=%s new_files=%d",
				config.id,
				config.connector_type,
				new_files,
			)
		except Exception as exc:
			_log.error(
				"sync_all: connector=%s error=%s",
				config.id,
				exc,
				exc_info=True,
			)
			results.append(
				{"connector_id": str(config.id), "type": config.connector_type, "error": str(exc)}
			)

	total = sum(r.get("new_files", 0) for r in results)
	_log.info("sync_all: complete — connectors=%d total_new_files=%d", len(results), total)
	return {"connectors": results, "total_new_files": total}


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------


@shared_task(
	bind=True,
	max_retries=1,
	default_retry_delay=60,
	name="darchiva.connectors.sync_all",
)
def sync_all_connectors(self) -> dict:
	"""
	Periodic task: sync all active external connectors.

	Iterates every connector with is_active=True, dispatches the appropriate
	sync function (Dropbox, local folder), and records new file counts.
	"""
	_log.info("sync_all_connectors: task started")
	loop = asyncio.new_event_loop()
	try:
		return loop.run_until_complete(_sync_all())
	except Exception as exc:
		_log.error("sync_all_connectors: unhandled error: %s", exc, exc_info=True)
		raise self.retry(exc=exc)
	finally:
		loop.close()

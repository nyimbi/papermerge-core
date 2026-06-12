"""
System health and infrastructure service.

Real checks are attempted; failures are caught and surfaced as degraded status
rather than 500s so the dashboard always gets a response.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.features.system.schema import (
	CacheHealth,
	DatabaseHealth,
	QueueInfo,
	ScheduledTask,
	ServiceInfo,
	ServiceMetrics,
	StorageHealth,
	SystemHealth,
	WorkerInfo,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Known services catalogue
# ---------------------------------------------------------------------------

_KNOWN_SERVICES: list[dict[str, Any]] = [
	{"id": "api", "name": "API Server", "type": "api", "host": "localhost", "port": 8000},
	{"id": "db", "name": "PostgreSQL", "type": "database", "host": "localhost", "port": 5432},
	{"id": "redis", "name": "Redis", "type": "cache", "host": "localhost", "port": 6379},
	{"id": "celery", "name": "Celery Worker", "type": "worker", "host": "localhost", "port": None},
	{"id": "minio", "name": "MinIO", "type": "storage", "host": "localhost", "port": 9000},
]

_KNOWN_SCHEDULED_TASKS: list[dict[str, Any]] = [
	{
		"id": "ocr_retry",
		"name": "Retry Failed OCR",
		"task_name": "papermerge.core.tasks.ocr.retry_failed",
		"schedule": "0 */2 * * *",
		"category": "ocr",
		"description": "Re-queues documents whose OCR failed in the last 24 hours",
		"timeout_seconds": 300,
	},
	{
		"id": "retention_cleanup",
		"name": "Retention Cleanup",
		"task_name": "papermerge.core.tasks.retention.cleanup",
		"schedule": "0 3 * * *",
		"category": "storage",
		"description": "Deletes documents past their retention expiry",
		"timeout_seconds": 600,
	},
	{
		"id": "index_rebuild",
		"name": "Search Index Rebuild",
		"task_name": "papermerge.core.tasks.search.rebuild_index",
		"schedule": "0 1 * * 0",
		"category": "search",
		"description": "Full rebuild of the search index (weekly)",
		"timeout_seconds": 3600,
	},
	{
		"id": "audit_purge",
		"name": "Audit Log Purge",
		"task_name": "papermerge.core.tasks.audit.purge_old_logs",
		"schedule": "0 4 1 * *",
		"category": "audit",
		"description": "Removes audit log entries older than the configured retention window",
		"timeout_seconds": 300,
	},
	{
		"id": "thumbnail_generate",
		"name": "Generate Missing Thumbnails",
		"task_name": "papermerge.core.tasks.thumbnails.generate_missing",
		"schedule": "30 */6 * * *",
		"category": "storage",
		"description": "Generates thumbnails for recently uploaded documents",
		"timeout_seconds": 600,
	},
]

# ---------------------------------------------------------------------------
# Health checks
# ---------------------------------------------------------------------------

async def _check_database(session: AsyncSession) -> DatabaseHealth:
	t0 = time.monotonic()
	try:
		from sqlalchemy import text
		await session.execute(text("SELECT 1"))
		latency_ms = (time.monotonic() - t0) * 1000
		return DatabaseHealth(connected=True, latency_ms=round(latency_ms, 2))
	except Exception as exc:
		log.warning("DB health check failed: %s", exc)
		return DatabaseHealth(connected=False, latency_ms=0.0)


async def _check_redis() -> CacheHealth:
	try:
		import redis.asyncio as aioredis
		from papermerge.core import config  # type: ignore[attr-defined]
		redis_url = getattr(config.settings, "redis_url", None) or "redis://localhost:6379/0"
		t0 = time.monotonic()
		client = aioredis.from_url(redis_url, socket_connect_timeout=2)
		await client.ping()
		latency_ms = (time.monotonic() - t0) * 1000
		info = await client.info("memory")
		await client.aclose()
		return CacheHealth(
			connected=True,
			latency_ms=round(latency_ms, 2),
			memory_used_bytes=info.get("used_memory", 0),
			memory_max_bytes=info.get("maxmemory", 0),
			keys_count=0,  # would need DBSIZE; skip to avoid extra RTT
		)
	except Exception as exc:
		log.warning("Redis health check failed: %s", exc)
		return CacheHealth(connected=False, latency_ms=0.0)


async def _check_storage() -> StorageHealth:
	try:
		from papermerge.core import config  # type: ignore[attr-defined]
		import boto3  # type: ignore[import-untyped]
		settings = getattr(config, "settings", None)
		if settings is None:
			raise RuntimeError("config.settings unavailable")
		t0 = time.monotonic()
		# Fire-and-forget head request to the bucket
		s3 = boto3.client(
			"s3",
			endpoint_url=getattr(settings, "s3_endpoint_url", None),
			aws_access_key_id=getattr(settings, "s3_access_key_id", None),
			aws_secret_access_key=getattr(settings, "s3_secret_access_key", None),
		)
		bucket = getattr(settings, "s3_bucket_name", "papermerge")
		s3.head_bucket(Bucket=bucket)
		latency_ms = (time.monotonic() - t0) * 1000
		return StorageHealth(available=True, latency_ms=round(latency_ms, 2))
	except Exception as exc:
		log.warning("Storage health check failed: %s", exc)
		return StorageHealth(available=False, latency_ms=0.0)


async def get_system_health(session: AsyncSession) -> SystemHealth:
	db_health = await _check_database(session)
	cache_health = await _check_redis()
	storage_health = await _check_storage()

	if not db_health.connected:
		overall = "unhealthy"
	elif not cache_health.connected or not storage_health.available:
		overall = "degraded"
	else:
		overall = "healthy"

	return SystemHealth(
		overall_status=overall,
		services=get_services(),
		workers=await get_workers(),
		queues=await get_queues(),
		scheduled_tasks=get_scheduled_tasks(),
		database=db_health,
		storage=storage_health,
		cache=cache_health,
	)


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------

def get_services() -> list[ServiceInfo]:
	services = []
	for s in _KNOWN_SERVICES:
		status = _ping_service(s["host"], s["port"])
		services.append(ServiceInfo(
			id=s["id"],
			name=s["name"],
			type=s["type"],
			status="running" if status else "unknown",
			host=s["host"],
			port=s["port"],
			healthy=status,
		))
	return services


def _ping_service(host: str, port: int | None) -> bool:
	if port is None:
		return True  # can't TCP-probe; assume up
	import socket
	try:
		with socket.create_connection((host, port), timeout=1):
			return True
	except OSError:
		return False


# ---------------------------------------------------------------------------
# Workers
# ---------------------------------------------------------------------------

async def get_workers() -> list[WorkerInfo]:
	try:
		from celery import current_app as celery_app  # type: ignore[import-untyped]
		inspect = celery_app.control.inspect(timeout=2)
		active = inspect.active() or {}
		stats = inspect.stats() or {}

		workers = []
		for worker_name, tasks in active.items():
			wstats = stats.get(worker_name, {})
			pool = wstats.get("pool", {})
			workers.append(WorkerInfo(
				id=worker_name,
				name=worker_name,
				queue="celery",
				status="running",
				concurrency=pool.get("max-concurrency", 1),
				active_tasks=len(tasks),
				started_at=None,
			))
		return workers
	except Exception as exc:
		log.debug("Celery inspect failed (non-fatal): %s", exc)
		return []


# ---------------------------------------------------------------------------
# Queues
# ---------------------------------------------------------------------------

async def get_queues() -> list[QueueInfo]:
	queue_names = ["celery", "ocr", "index", "email"]
	queues = []
	try:
		import redis.asyncio as aioredis
		from papermerge.core import config  # type: ignore[attr-defined]
		redis_url = getattr(config.settings, "redis_url", None) or "redis://localhost:6379/0"
		client = aioredis.from_url(redis_url, socket_connect_timeout=2)
		for name in queue_names:
			length = await client.llen(name)
			queues.append(QueueInfo(name=name, pending=length))
		await client.aclose()
	except Exception as exc:
		log.debug("Redis queue check failed (non-fatal): %s", exc)
		queues = [QueueInfo(name=n) for n in queue_names]
	return queues


# ---------------------------------------------------------------------------
# Scheduled tasks
# ---------------------------------------------------------------------------

def get_scheduled_tasks() -> list[ScheduledTask]:
	return [ScheduledTask(**t) for t in _KNOWN_SCHEDULED_TASKS]

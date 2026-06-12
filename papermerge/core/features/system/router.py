from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.engine import get_db
from papermerge.core.features.auth import scopes
from papermerge.core.features.auth.dependencies import require_scopes
from papermerge.core.features.system import service as svc
from papermerge.core.features.system.schema import (
	ActionResult,
	PurgeResult,
	QueueInfo,
	RetryResult,
	ScheduledTask,
	ScheduledTaskUpdate,
	ServiceConfig,
	ServiceConfigUpdate,
	ServiceInfo,
	SystemHealth,
	WorkerConfig,
	WorkerConfigUpdate,
	WorkerInfo,
)

log = logging.getLogger(__name__)

router = APIRouter(
	prefix="/system",
	tags=["system"],
)

# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@router.get("/health", response_model=SystemHealth)
async def get_health(
	_user: require_scopes(scopes.NODE_VIEW),
	db: AsyncSession = Depends(get_db),
) -> SystemHealth:
	"""Full system health check — DB, Redis, storage, workers."""
	return await svc.get_system_health(db)


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------

@router.get("/services", response_model=list[ServiceInfo])
async def list_services(
	_user: require_scopes(scopes.NODE_VIEW),
) -> list[ServiceInfo]:
	return svc.get_services()


@router.post("/services/{service_id}/{action}", response_model=ServiceInfo)
async def service_action(
	service_id: str,
	action: str,
	_user: require_scopes(scopes.NODE_CREATE),
) -> ServiceInfo:
	"""
	Trigger start / stop / restart on a service.

	In production this would delegate to systemd / docker / k8s.
	Currently logs the request and returns updated status.
	"""
	valid_actions = {"start", "stop", "restart"}
	if action not in valid_actions:
		raise HTTPException(
			status_code=status.HTTP_400_BAD_REQUEST,
			detail=f"Invalid action '{action}'. Must be one of {sorted(valid_actions)}",
		)

	services = svc.get_services()
	target = next((s for s in services if s.id == service_id), None)
	if target is None:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Service '{service_id}' not found")

	log.info("Service action requested: %s -> %s", service_id, action)

	# Reflect expected post-action state in the response
	status_map = {"start": "running", "stop": "stopped", "restart": "starting"}
	target.status = status_map[action]
	target.healthy = action != "stop"
	return target


@router.patch("/services/{service_id}/config", response_model=ServiceInfo)
async def update_service_config(
	service_id: str,
	body: ServiceConfigUpdate,
	user: require_scopes(scopes.NODE_CREATE),
	db: AsyncSession = Depends(get_db),
) -> ServiceInfo:
	"""Persist service config overrides in SystemSettings['service_configs']."""
	from papermerge.core.features.settings.db import api as settings_api

	stored = await settings_api.get_settings(db, "service_configs")
	configs: dict = stored.get("services", {})
	configs[service_id] = {**configs.get(service_id, {}), **body.model_dump(exclude_none=True)}
	await settings_api.upsert_settings(db, "service_configs", {"services": configs}, str(user.id))

	services = svc.get_services()
	target = next((s for s in services if s.id == service_id), None)
	if target is None:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Service '{service_id}' not found")
	return target


# ---------------------------------------------------------------------------
# Workers
# ---------------------------------------------------------------------------

@router.get("/workers", response_model=list[WorkerInfo])
async def list_workers(
	_user: require_scopes(scopes.NODE_VIEW),
) -> list[WorkerInfo]:
	return await svc.get_workers()


@router.post("/workers/{worker_id}/{action}", response_model=ActionResult)
async def worker_action(
	worker_id: str,
	action: str,
	_user: require_scopes(scopes.NODE_CREATE),
) -> ActionResult:
	valid_actions = {"start", "stop", "restart", "pause", "resume"}
	if action not in valid_actions:
		raise HTTPException(
			status_code=status.HTTP_400_BAD_REQUEST,
			detail=f"Invalid action '{action}'. Must be one of {sorted(valid_actions)}",
		)

	log.info("Worker action requested: %s -> %s", worker_id, action)
	return ActionResult(success=True, message=f"Worker '{worker_id}' {action} requested")


@router.patch("/workers/{worker_id}/config", response_model=ActionResult)
async def update_worker_config(
	worker_id: str,
	body: WorkerConfigUpdate,
	user: require_scopes(scopes.NODE_CREATE),
	db: AsyncSession = Depends(get_db),
) -> ActionResult:
	from papermerge.core.features.settings.db import api as settings_api

	stored = await settings_api.get_settings(db, "worker_configs")
	configs: dict = stored.get("workers", {})
	configs[worker_id] = {**configs.get(worker_id, {}), **body.model_dump(exclude_none=True)}
	await settings_api.upsert_settings(db, "worker_configs", {"workers": configs}, str(user.id))
	log.info("Worker config updated: %s", worker_id)
	return ActionResult(success=True, message=f"Worker '{worker_id}' config updated")


# ---------------------------------------------------------------------------
# Queues
# ---------------------------------------------------------------------------

@router.get("/queues", response_model=list[QueueInfo])
async def list_queues(
	_user: require_scopes(scopes.NODE_VIEW),
) -> list[QueueInfo]:
	return await svc.get_queues()


@router.post("/queues/{queue_name}/purge", response_model=PurgeResult)
async def purge_queue(
	queue_name: str,
	_user: require_scopes(scopes.NODE_CREATE),
) -> PurgeResult:
	purged = 0
	try:
		import redis.asyncio as aioredis
		from papermerge.core import config  # type: ignore[attr-defined]
		redis_url = getattr(config.settings, "redis_url", None) or "redis://localhost:6379/0"
		client = aioredis.from_url(redis_url, socket_connect_timeout=2)
		purged = await client.llen(queue_name)
		await client.delete(queue_name)
		await client.aclose()
		log.info("Queue purged: %s (%d messages)", queue_name, purged)
	except Exception as exc:
		log.warning("Queue purge failed: %s", exc)
	return PurgeResult(purged=purged)


@router.post("/queues/{queue_name}/retry-failed", response_model=RetryResult)
async def retry_failed(
	queue_name: str,
	_user: require_scopes(scopes.NODE_CREATE),
) -> RetryResult:
	retried = 0
	try:
		failed_key = f"{queue_name}:failed"
		import redis.asyncio as aioredis
		from papermerge.core import config  # type: ignore[attr-defined]
		redis_url = getattr(config.settings, "redis_url", None) or "redis://localhost:6379/0"
		client = aioredis.from_url(redis_url, socket_connect_timeout=2)
		messages = await client.lrange(failed_key, 0, -1)
		for msg in messages:
			await client.rpush(queue_name, msg)
		if messages:
			await client.delete(failed_key)
		retried = len(messages)
		await client.aclose()
		log.info("Retried %d failed messages from %s", retried, queue_name)
	except Exception as exc:
		log.warning("Retry-failed failed: %s", exc)
	return RetryResult(retried=retried)


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

@router.get("/scheduler/tasks", response_model=list[ScheduledTask])
async def list_scheduled_tasks(
	_user: require_scopes(scopes.NODE_VIEW),
) -> list[ScheduledTask]:
	return svc.get_scheduled_tasks()


@router.patch("/scheduler/tasks/{task_id}", response_model=ScheduledTask)
async def update_scheduled_task(
	task_id: str,
	body: ScheduledTaskUpdate,
	user: require_scopes(scopes.NODE_CREATE),
	db: AsyncSession = Depends(get_db),
) -> ScheduledTask:
	from papermerge.core.features.settings.db import api as settings_api

	tasks = svc.get_scheduled_tasks()
	target = next((t for t in tasks if t.id == task_id), None)
	if target is None:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Task '{task_id}' not found")

	# Persist overrides
	stored = await settings_api.get_settings(db, "scheduler_overrides")
	overrides: dict = stored.get("tasks", {})
	overrides[task_id] = {**overrides.get(task_id, {}), **body.model_dump(exclude_none=True)}
	await settings_api.upsert_settings(db, "scheduler_overrides", {"tasks": overrides}, str(user.id))

	# Apply to response object
	if body.enabled is not None:
		target.enabled = body.enabled
	if body.schedule is not None:
		target.schedule = body.schedule
	if body.timeout_seconds is not None:
		target.timeout_seconds = body.timeout_seconds

	return target


@router.post("/scheduler/tasks/{task_id}/run", response_model=ActionResult)
async def run_scheduled_task(
	task_id: str,
	_user: require_scopes(scopes.NODE_CREATE),
) -> ActionResult:
	tasks = svc.get_scheduled_tasks()
	target = next((t for t in tasks if t.id == task_id), None)
	if target is None:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Task '{task_id}' not found")

	try:
		from celery import current_app as celery_app  # type: ignore[import-untyped]
		celery_app.send_task(target.task_name)
		log.info("Triggered scheduled task immediately: %s (%s)", task_id, target.task_name)
		return ActionResult(success=True, message=f"Task '{task_id}' triggered")
	except Exception as exc:
		log.warning("Failed to trigger task %s: %s", task_id, exc)
		return ActionResult(success=False, message=str(exc))

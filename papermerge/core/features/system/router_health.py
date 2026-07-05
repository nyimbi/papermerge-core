"""
Focused health endpoints for the System Health Dashboard.

Exposes three routes:
  GET /system/health   — full snapshot (workers + queues + storage + DB + Redis)
  GET /system/queues   — queue depths only (fast poll, ~100 ms)
  GET /system/workers  — worker list only

All three delegate to the existing service layer in
papermerge.core.features.system.service so there is no logic duplication.
The router is registered separately from the main system router so the
wiring agent can mount it independently if desired, or it can be included
alongside the existing router — both share the /system prefix.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.engine import get_db
from papermerge.core.features.auth import scopes
from papermerge.core.features.auth.dependencies import require_scopes
from papermerge.core.features.system import service as svc
from papermerge.core.features.system.schema import (
    QueueInfo,
    SystemHealth,
    WorkerInfo,
)

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/system",
    tags=["system-health"],
)


class WorkerRuntimeInfo(BaseModel):
    name: str
    status: str = "running"
    active_tasks: int = 0
    queues: list[str] = Field(default_factory=list)


class WorkersResponse(BaseModel):
    workers: list[WorkerRuntimeInfo] = Field(default_factory=list)
    total_active: int = 0
    active: int = 0
    total: int = 0


def _inspect_celery_workers() -> WorkersResponse:
    try:
        try:
            from papermerge.celery_app import app as celery_app
        except Exception:
            from celery import current_app as celery_app  # type: ignore[import-untyped]

        inspect = celery_app.control.inspect(timeout=2)
        active = inspect.active() or {}
        active_queues = inspect.active_queues() or {}
    except Exception as exc:
        log.debug("Celery worker inspect failed (non-fatal): %s", exc)
        return WorkersResponse()

    workers: list[WorkerRuntimeInfo] = []
    total_active = 0
    for worker_name, tasks in active.items():
        queue_items = active_queues.get(worker_name) or []
        queues = [
            queue.get("name")
            for queue in queue_items
            if isinstance(queue, dict) and queue.get("name")
        ]
        active_count = len(tasks or [])
        total_active += active_count
        workers.append(
            WorkerRuntimeInfo(
                name=worker_name,
                status="running",
                active_tasks=active_count,
                queues=queues,
            )
        )
    return WorkersResponse(
        workers=workers,
        total_active=total_active,
        active=total_active,
        total=len(workers),
    )


# ---------------------------------------------------------------------------
# Full health snapshot
# ---------------------------------------------------------------------------

@router.get("/health", response_model=SystemHealth)
async def get_health(
    _user: require_scopes(scopes.NODE_VIEW),
    db: AsyncSession = Depends(get_db),
) -> SystemHealth:
    """
    Full system health snapshot.

    Returned shape (camelCased by the frontend API client):
    {
      overall_status: "healthy"|"degraded"|"unhealthy",
      workers: [{id, name, queue, status, active_tasks, ...}],
      queues:  [{name, pending, active, consumers, ...}],
      database: {connected, latency_ms, ...},
      storage:  {available, latency_ms, used_bytes, total_bytes, objects_count},
      cache:    {connected, latency_ms, memory_used_bytes, ...},
    }
    """
    return await svc.get_system_health(db)


# ---------------------------------------------------------------------------
# Queue depths — lightweight, intended for frequent polling
# ---------------------------------------------------------------------------

@router.get("/queues", response_model=list[QueueInfo])
async def get_queues(
    _user: require_scopes(scopes.NODE_VIEW),
) -> list[QueueInfo]:
    """
    Returns pending depth for each known Celery queue.

    Touches only Redis (one LLEN per queue) so typical latency is < 50 ms.
    Safe to poll every 10 s from the dashboard.
    """
    return await svc.get_queues()


# ---------------------------------------------------------------------------
# Worker list
# ---------------------------------------------------------------------------

@router.get("/workers", response_model=WorkersResponse)
async def get_workers(
    _user: require_scopes(scopes.NODE_VIEW),
) -> WorkersResponse:
    """
    Returns live worker data via Celery inspect (timeout = 2 s).

    Returns an empty list when no workers are reachable rather than raising.
    """
    return _inspect_celery_workers()

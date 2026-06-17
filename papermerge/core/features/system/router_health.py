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

@router.get("/workers", response_model=list[WorkerInfo])
async def get_workers(
    _user: require_scopes(scopes.NODE_VIEW),
) -> list[WorkerInfo]:
    """
    Returns live worker data via Celery inspect (timeout = 2 s).

    Returns an empty list when no workers are reachable rather than raising.
    """
    return await svc.get_workers()

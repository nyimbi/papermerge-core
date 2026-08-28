"""
Service status and document metrics endpoints for the Health Monitor dashboard.

Exposes two admin routes (auto-discovered by router_loader):

  GET /admin/health/services
    Checks each dependency in parallel and returns a list of service health
    records with status "ok" | "degraded" | "down" and latency_ms.

  GET /admin/health/metrics
    Runs lightweight COUNT queries against the documents / scan_batches tables
    and returns operational metrics (documents today, OCR queue depth, etc.).

Both routes are guarded by NODE_VIEW scope (same as /system/health) so no new
permission surface is introduced.  They never raise 500 — degraded checks are
caught and returned as status="down".
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, text
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.engine import get_db
from papermerge.core.features.auth import scopes
from papermerge.core.features.auth.dependencies import require_scopes

log = logging.getLogger(__name__)

router = APIRouter(
	prefix="/admin/health",
	tags=["admin-health"],
)

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ServiceStatus(BaseModel):
	model_config = ConfigDict(extra="forbid")

	name: str
	status: str  # "ok" | "degraded" | "down" | "unknown"
	latency_ms: float = 0.0
	details: str = ""


class ServicesResponse(BaseModel):
	model_config = ConfigDict(extra="forbid")

	services: list[ServiceStatus]
	degraded_count: int = 0
	down_count: int = 0


class MetricItem(BaseModel):
	model_config = ConfigDict(extra="forbid")

	name: str
	value: int
	unit: str = ""
	trend: str | None = None  # "up" | "down" | "stable"


class MetricsResponse(BaseModel):
	model_config = ConfigDict(extra="forbid")

	metrics: list[MetricItem]
	collected_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ---------------------------------------------------------------------------
# Individual service probes
# ---------------------------------------------------------------------------


async def _probe_postgres(session: AsyncSession) -> ServiceStatus:
	t0 = time.monotonic()
	try:
		await session.execute(text("SELECT 1"))
		latency_ms = round((time.monotonic() - t0) * 1000, 2)
		return ServiceStatus(name="postgres", status="ok", latency_ms=latency_ms)
	except Exception as exc:
		log.warning("postgres probe failed: %s", exc)
		return ServiceStatus(name="postgres", status="down", details=str(exc)[:200])


async def _probe_redis() -> ServiceStatus:
	try:
		import redis.asyncio as aioredis
		from papermerge.core import config  # type: ignore[attr-defined]

		redis_url = getattr(config.settings, "redis_url", None) or "redis://localhost:6379/0"
		t0 = time.monotonic()
		client = aioredis.from_url(redis_url, socket_connect_timeout=2)
		await client.ping()
		latency_ms = round((time.monotonic() - t0) * 1000, 2)
		await client.aclose()
		return ServiceStatus(name="redis", status="ok", latency_ms=latency_ms)
	except ImportError:
		return ServiceStatus(name="redis", status="unknown", details="redis-py not installed")
	except Exception as exc:
		log.warning("redis probe failed: %s", exc)
		return ServiceStatus(name="redis", status="down", details=str(exc)[:200])


async def _probe_celery_workers() -> ServiceStatus:
	try:
		from celery import current_app as celery_app  # type: ignore[import-untyped]

		t0 = time.monotonic()
		inspect = celery_app.control.inspect(timeout=2)
		active = inspect.active() or {}
		latency_ms = round((time.monotonic() - t0) * 1000, 2)
		worker_count = len(active)
		if worker_count == 0:
			return ServiceStatus(
				name="celery_workers",
				status="degraded",
				latency_ms=latency_ms,
				details="No active workers found",
			)
		return ServiceStatus(
			name="celery_workers",
			status="ok",
			latency_ms=latency_ms,
			details=f"{worker_count} worker(s) active",
		)
	except Exception as exc:
		log.warning("celery workers probe failed: %s", exc)
		return ServiceStatus(name="celery_workers", status="down", details=str(exc)[:200])


async def _probe_celery_queue_depth() -> ServiceStatus:
	try:
		import redis.asyncio as aioredis
		from papermerge.core import config  # type: ignore[attr-defined]

		redis_url = getattr(config.settings, "redis_url", None) or "redis://localhost:6379/0"
		t0 = time.monotonic()
		client = aioredis.from_url(redis_url, socket_connect_timeout=2)
		queue_names = ["celery", "ocr", "index", "email"]
		depths = {}
		for name in queue_names:
			depths[name] = await client.llen(name)
		await client.aclose()
		latency_ms = round((time.monotonic() - t0) * 1000, 2)
		total = sum(depths.values())
		detail = ", ".join(f"{k}:{v}" for k, v in depths.items() if v > 0) or "all empty"
		status = "ok" if total < 100 else "degraded"
		return ServiceStatus(
			name="celery_queue_depth",
			status=status,
			latency_ms=latency_ms,
			details=detail,
		)
	except ImportError:
		return ServiceStatus(name="celery_queue_depth", status="unknown", details="redis-py not installed")
	except Exception as exc:
		log.warning("celery queue depth probe failed: %s", exc)
		return ServiceStatus(name="celery_queue_depth", status="down", details=str(exc)[:200])


async def _probe_litellm() -> ServiceStatus:
	try:
		import httpx
		from papermerge.core.config import get_settings
		cfg = get_settings()
		litellm_base = (cfg.litellm_base_url or "").rstrip("/")
		if not litellm_base:
			return ServiceStatus(name="litellm", status="unavailable")
		litellm_url = f"{litellm_base}/health"
		t0 = time.monotonic()
		async with httpx.AsyncClient(timeout=2.0) as client:
			resp = await client.get(litellm_url)
		latency_ms = round((time.monotonic() - t0) * 1000, 2)
		if resp.status_code < 400:
			return ServiceStatus(name="litellm", status="ok", latency_ms=latency_ms)
		return ServiceStatus(
			name="litellm",
			status="degraded",
			latency_ms=latency_ms,
			details=f"HTTP {resp.status_code}",
		)
	except ImportError:
		return ServiceStatus(name="litellm", status="unknown", details="httpx not installed")
	except Exception as exc:
		log.warning("litellm probe failed: %s", exc)
		return ServiceStatus(name="litellm", status="down", details=str(exc)[:200])


async def _probe_storage() -> ServiceStatus:
	try:
		from papermerge.core import config  # type: ignore[attr-defined]
		import boto3  # type: ignore[import-untyped]

		settings = config.settings
		t0 = time.monotonic()
		s3 = boto3.client(
			"s3",
			endpoint_url=getattr(settings, "s3_endpoint_url", None),
			aws_access_key_id=getattr(settings, "s3_access_key_id", None),
			aws_secret_access_key=getattr(settings, "s3_secret_access_key", None),
		)
		bucket = getattr(settings, "s3_bucket_name", "papermerge")
		s3.head_bucket(Bucket=bucket)
		latency_ms = round((time.monotonic() - t0) * 1000, 2)
		return ServiceStatus(name="storage", status="ok", latency_ms=latency_ms)
	except Exception as exc:
		log.warning("storage probe failed: %s", exc)
		return ServiceStatus(name="storage", status="down", details=str(exc)[:200])


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/services", response_model=ServicesResponse)
async def get_service_statuses(
	_user: require_scopes(scopes.NODE_VIEW),
	db: AsyncSession = Depends(get_db),
) -> ServicesResponse:
	"""
	Check each downstream service dependency in parallel.

	Returns status "ok"|"degraded"|"down"|"unknown" and latency_ms per service.
	Never returns 500 — failed probes become status="down".
	"""
	results: list[ServiceStatus] = await asyncio.gather(
		_probe_postgres(db),
		_probe_redis(),
		_probe_celery_workers(),
		_probe_celery_queue_depth(),
		_probe_litellm(),
		_probe_storage(),
	)

	degraded = sum(1 for s in results if s.status == "degraded")
	down = sum(1 for s in results if s.status == "down")

	return ServicesResponse(services=results, degraded_count=degraded, down_count=down)


@router.get("/metrics", response_model=MetricsResponse)
async def get_health_metrics(
	_user: require_scopes(scopes.NODE_VIEW),
	db: AsyncSession = Depends(get_db),
) -> MetricsResponse:
	"""
	Document and pipeline operational metrics from the database.

	All counts run as single SQL queries so latency is negligible.
	Never returns 500 — query failures yield a metric with value -1.
	"""
	today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
	metrics: list[MetricItem] = []

	# ── documents_total ──────────────────────────────────────────────────────
	try:
		row = await db.execute(text("SELECT COUNT(*) FROM documents"))
		metrics.append(MetricItem(name="documents_total", value=row.scalar() or 0, unit="docs"))
	except Exception as exc:
		log.warning("documents_total query failed: %s", exc)
		metrics.append(MetricItem(name="documents_total", value=-1, unit="docs"))

	# ── documents_today ──────────────────────────────────────────────────────
	try:
		row = await db.execute(
			text("SELECT COUNT(*) FROM nodes WHERE ctype = 'document' AND created_at >= :today"),
			{"today": today_start},
		)
		metrics.append(MetricItem(name="documents_today", value=row.scalar() or 0, unit="docs", trend="up"))
	except Exception as exc:
		log.warning("documents_today query failed: %s", exc)
		metrics.append(MetricItem(name="documents_today", value=-1, unit="docs"))

	# ── ocr_queue_depth ──────────────────────────────────────────────────────
	try:
		row = await db.execute(
			text(
				"SELECT COUNT(*) FROM documents "
				"WHERE ocr_status IN ('RECEIVED', 'STARTED')"
			)
		)
		ocr_depth = row.scalar() or 0
		metrics.append(MetricItem(
			name="ocr_queue_depth",
			value=ocr_depth,
			unit="docs",
			trend="stable" if ocr_depth == 0 else "up",
		))
	except Exception as exc:
		log.warning("ocr_queue_depth query failed: %s", exc)
		metrics.append(MetricItem(name="ocr_queue_depth", value=-1, unit="docs"))

	# ── failed_ocr_today ─────────────────────────────────────────────────────
	try:
		row = await db.execute(
			text(
				"SELECT COUNT(*) FROM documents "
				"WHERE ocr_status = 'FAILURE' AND updated_at >= :today"
			),
			{"today": today_start},
		)
		failed_ocr = row.scalar() or 0
		metrics.append(MetricItem(
			name="failed_ocr_today",
			value=failed_ocr,
			unit="docs",
			trend="down" if failed_ocr == 0 else "up",
		))
	except Exception as exc:
		log.warning("failed_ocr_today query failed: %s", exc)
		metrics.append(MetricItem(name="failed_ocr_today", value=-1, unit="docs"))

	# ── active_scans_today ───────────────────────────────────────────────────
	try:
		row = await db.execute(
			text("SELECT COUNT(*) FROM scan_batches WHERE created_at >= :today"),
			{"today": today_start},
		)
		metrics.append(MetricItem(name="active_scans_today", value=row.scalar() or 0, unit="batches"))
	except Exception as exc:
		log.warning("active_scans_today query failed: %s", exc)
		metrics.append(MetricItem(name="active_scans_today", value=-1, unit="batches"))

	# ── storage_used_bytes (from document_versions size sum) ─────────────────
	try:
		row = await db.execute(text("SELECT COALESCE(SUM(size), 0) FROM document_versions"))
		metrics.append(MetricItem(name="storage_used_bytes", value=row.scalar() or 0, unit="bytes"))
	except Exception as exc:
		log.warning("storage_used_bytes query failed: %s", exc)
		metrics.append(MetricItem(name="storage_used_bytes", value=-1, unit="bytes"))

	return MetricsResponse(metrics=metrics)

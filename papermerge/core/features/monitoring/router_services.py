# (c) Copyright Datacraft, 2026
"""Admin health endpoints — service probes and operational metrics.

Auto-discovered by papermerge.core.router_loader (router_*.py glob).

Routes:
  GET /admin/health/services  — parallel liveness probe for each dependency
  GET /admin/health/metrics   — document/pipeline counters from the DB
"""
import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.engine import get_db
from papermerge.core.features.auth import scopes
from papermerge.core.features.auth.dependencies import require_scopes
from papermerge.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(
	prefix="/admin/health",
	tags=["admin-health"],
)

# ── Auth dependency ───────────────────────────────────────────────────────────

def _require_admin(user=Depends(require_scopes(scopes.Scopes.TENANT_ADMIN))):
	return user


# ── Response schemas ──────────────────────────────────────────────────────────

class ServiceStatus(BaseModel):
	name: str
	status: str  # "ok" | "degraded" | "down" | "unknown"
	latency_ms: float | None = None
	details: str = ""

	model_config = ConfigDict(from_attributes=True)


class ServicesResponse(BaseModel):
	services: list[ServiceStatus]
	degraded_count: int
	down_count: int
	collected_at: datetime

	model_config = ConfigDict(from_attributes=True)


class MetricItem(BaseModel):
	name: str
	value: int | float
	unit: str

	model_config = ConfigDict(from_attributes=True)


class MetricsResponse(BaseModel):
	metrics: list[MetricItem]
	collected_at: datetime

	model_config = ConfigDict(from_attributes=True)


# ── Service probe helpers ─────────────────────────────────────────────────────

async def _probe_postgres(db_session: AsyncSession) -> ServiceStatus:
	t0 = time.perf_counter()
	try:
		await db_session.execute(text("SELECT 1"))
		latency_ms = (time.perf_counter() - t0) * 1000
		return ServiceStatus(
			name="postgres",
			status="ok",
			latency_ms=round(latency_ms, 2),
			details="SELECT 1 succeeded",
		)
	except Exception as exc:
		logger.warning("postgres probe failed: %s", exc)
		return ServiceStatus(name="postgres", status="down", details=str(exc))


def _probe_redis() -> ServiceStatus:
	if not settings.redis_url:
		return ServiceStatus(name="redis", status="unknown", details="REDIS_URL not configured")
	t0 = time.perf_counter()
	try:
		import redis as _redis  # optional dep — don't fail import at module load
		r = _redis.from_url(str(settings.redis_url), socket_timeout=2, socket_connect_timeout=2)
		r.ping()
		latency_ms = (time.perf_counter() - t0) * 1000
		return ServiceStatus(
			name="redis",
			status="ok",
			latency_ms=round(latency_ms, 2),
			details="PING OK",
		)
	except ImportError:
		return ServiceStatus(name="redis", status="unknown", details="redis package not installed")
	except Exception as exc:
		logger.warning("redis probe failed: %s", exc)
		return ServiceStatus(name="redis", status="down", details=str(exc))


def _probe_litellm() -> ServiceStatus:
	t0 = time.perf_counter()
	try:
		import httpx
		# Use the configured base URL, strip the /v1 suffix if present
		base = str(settings.litellm_base_url).rstrip("/")
		if base.endswith("/v1"):
			base = base[:-3]
		resp = httpx.get(f"{base}/health", timeout=2.0)
		latency_ms = (time.perf_counter() - t0) * 1000
		if resp.status_code == 200:
			return ServiceStatus(
				name="litellm",
				status="ok",
				latency_ms=round(latency_ms, 2),
				details=f"HTTP {resp.status_code}",
			)
		return ServiceStatus(
			name="litellm",
			status="degraded",
			latency_ms=round(latency_ms, 2),
			details=f"HTTP {resp.status_code}",
		)
	except Exception as exc:
		logger.warning("litellm probe failed: %s", exc)
		return ServiceStatus(name="litellm", status="down", details=str(exc))


def _probe_storage() -> ServiceStatus:
	t0 = time.perf_counter()
	try:
		media_root = settings.media_root
		if not media_root.exists():
			return ServiceStatus(
				name="storage",
				status="down",
				details=f"media_root {media_root} does not exist",
			)
		# Verify writable by touching a probe file
		probe = media_root / ".health_probe"
		probe.write_text("ok")
		probe.unlink()
		latency_ms = (time.perf_counter() - t0) * 1000
		return ServiceStatus(
			name="storage",
			status="ok",
			latency_ms=round(latency_ms, 2),
			details=f"{media_root} is writable",
		)
	except Exception as exc:
		logger.warning("storage probe failed: %s", exc)
		return ServiceStatus(name="storage", status="down", details=str(exc))


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/services", response_model=ServicesResponse)
async def get_service_health(
	db_session: AsyncSession = Depends(get_db),
	_user=Depends(_require_admin),
) -> ServicesResponse:
	"""Parallel liveness probes for each service dependency."""
	import asyncio

	postgres_result = await _probe_postgres(db_session)

	# Run sync probes in the thread pool so they don't block the event loop
	loop = asyncio.get_event_loop()
	redis_result, litellm_result, storage_result = await asyncio.gather(
		loop.run_in_executor(None, _probe_redis),
		loop.run_in_executor(None, _probe_litellm),
		loop.run_in_executor(None, _probe_storage),
	)

	services = [postgres_result, redis_result, litellm_result, storage_result]
	degraded_count = sum(1 for s in services if s.status == "degraded")
	down_count = sum(1 for s in services if s.status == "down")

	return ServicesResponse(
		services=services,
		degraded_count=degraded_count,
		down_count=down_count,
		collected_at=datetime.now(timezone.utc),
	)


@router.get("/metrics", response_model=MetricsResponse)
async def get_health_metrics(
	db_session: AsyncSession = Depends(get_db),
	_user=Depends(_require_admin),
) -> MetricsResponse:
	"""Operational counters from the documents table."""
	from papermerge.core.features.document.db.orm import Document
	from papermerge.core.types import OCRStatusEnum

	today_start = datetime.now(timezone.utc).replace(
		hour=0, minute=0, second=0, microsecond=0
	)

	# documents_total
	total_result = await db_session.execute(
		select(func.count()).select_from(Document)
	)
	documents_total: int = total_result.scalar_one_or_none() or 0

	# documents_today — created_at lives on the nodes table (AuditColumns mixin),
	# but SQLAlchemy resolves it via the joined-table inheritance relationship.
	from papermerge.core.features.nodes.db.orm import Node
	today_result = await db_session.execute(
		select(func.count())
		.select_from(Document)
		.join(Node, Node.id == Document.id)  # explicit join for clarity
		.where(Node.created_at >= today_start)
	)
	documents_today: int = today_result.scalar_one_or_none() or 0

	# ocr_queue_depth — docs with OCR requested but not yet succeeded
	ocr_queue_result = await db_session.execute(
		select(func.count())
		.select_from(Document)
		.where(Document.ocr == True)  # noqa: E712
		.where(Document.ocr_status.in_([OCRStatusEnum.unknown, OCRStatusEnum.started]))
	)
	ocr_queue_depth: int = ocr_queue_result.scalar_one_or_none() or 0

	# failed_ocr — documents whose processing pipeline failed
	from papermerge.core.types import DocumentProcessingStatus
	failed_result = await db_session.execute(
		select(func.count())
		.select_from(Document)
		.where(Document.processing_status == DocumentProcessingStatus.failed)
	)
	failed_ocr: int = failed_result.scalar_one_or_none() or 0

	metrics = [
		MetricItem(name="documents_total", value=documents_total, unit="documents"),
		MetricItem(name="documents_today", value=documents_today, unit="documents"),
		MetricItem(name="ocr_queue_depth", value=ocr_queue_depth, unit="documents"),
		MetricItem(name="failed_ocr", value=failed_ocr, unit="documents"),
	]

	return MetricsResponse(
		metrics=metrics,
		collected_at=datetime.now(timezone.utc),
	)

# (c) Copyright Datacraft, 2026
"""Performance Analytics router — auto-discovered by router_loader.

Provides throughput trends, quality trends, operator performance,
capacity utilization, and a combined summary endpoint for the
dArchiva Performance Analytics Dashboard.
"""
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select, and_, case
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.auth import get_current_user
from papermerge.core.db.engine import get_db
from papermerge.core.features.users.schema import User
from papermerge.core.features.scanning_projects.models import (
	PageScanEventModel,
	ScanningBatchModel,
	OperatorDailyMetricsModel,
	ScanningSesssionModel,
)

router = APIRouter(prefix="/analytics", tags=["analytics"])


# ─────────────────────────── helpers ────────────────────────────


def _utc_now() -> datetime:
	return datetime.now(timezone.utc)


def _window_start(days: int) -> datetime:
	return _utc_now() - timedelta(days=days)


def _trunc_expr(col, granularity: str):
	"""Return a SQLAlchemy date_trunc expression for the given granularity."""
	return func.date_trunc(granularity, col)


# ─────────────────────────── schemas ────────────────────────────


class ThroughputPoint(BaseModel):
	timestamp: str
	pages_scanned: int
	batches_completed: int


class ThroughputResponse(BaseModel):
	data: list[ThroughputPoint]


class QualityPoint(BaseModel):
	timestamp: str
	avg_quality_score: float
	below_threshold_pct: float


class QualityTrendResponse(BaseModel):
	data: list[QualityPoint]


class OperatorPerf(BaseModel):
	user_id: str
	name: str
	pages_scanned: int
	avg_quality: float
	exceptions_caused: int
	on_time_rate: float


class OperatorPerformanceResponse(BaseModel):
	operators: list[OperatorPerf]


class CapacityResponse(BaseModel):
	current_queue_depth: int
	workers_active: int
	avg_processing_time_seconds: float
	estimated_throughput_pages_per_hour: float
	projected_backlog_hours: float


class SummaryResponse(BaseModel):
	throughput: ThroughputResponse
	quality_trend: QualityTrendResponse
	operator_performance: OperatorPerformanceResponse
	capacity: CapacityResponse


# ─────────────────────── throughput endpoint ────────────────────


@router.get("/throughput", response_model=ThroughputResponse)
async def get_throughput(
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
	days: int = Query(default=30, ge=1, le=365),
	granularity: Literal["hour", "day", "week", "month"] = Query(default="day"),
):
	"""Pages scanned and batches completed grouped by time bucket."""
	tenant_id = str(user.tenant_id)
	since = _window_start(days)
	trunc = _trunc_expr(PageScanEventModel.occurred_at, granularity)

	# Pages scanned — count "scanned" events
	pages_q = (
		select(
			trunc.label("bucket"),
			func.count(PageScanEventModel.id).label("pages_scanned"),
		)
		.where(
			and_(
				PageScanEventModel.tenant_id == tenant_id,
				PageScanEventModel.occurred_at >= since,
				PageScanEventModel.event_type == "scanned",
			)
		)
		.group_by("bucket")
		.order_by("bucket")
	)
	pages_result = await session.execute(pages_q)
	pages_by_bucket: dict[str, int] = {
		str(row.bucket): row.pages_scanned for row in pages_result
	}

	# Batches completed — use ScanningBatchModel.completed_at
	batches_q = (
		select(
			_trunc_expr(ScanningBatchModel.completed_at, granularity).label("bucket"),
			func.count(ScanningBatchModel.id).label("batches_completed"),
		)
		.where(
			and_(
				ScanningBatchModel.completed_at.isnot(None),
				ScanningBatchModel.completed_at >= since,
			)
		)
		.group_by("bucket")
		.order_by("bucket")
	)
	batches_result = await session.execute(batches_q)
	batches_by_bucket: dict[str, int] = {
		str(row.bucket): row.batches_completed for row in batches_result
	}

	# Merge by bucket
	all_buckets = sorted(set(pages_by_bucket) | set(batches_by_bucket))
	data = [
		ThroughputPoint(
			timestamp=bucket,
			pages_scanned=pages_by_bucket.get(bucket, 0),
			batches_completed=batches_by_bucket.get(bucket, 0),
		)
		for bucket in all_buckets
	]
	return ThroughputResponse(data=data)


# ─────────────────────── quality trend endpoint ─────────────────


@router.get("/quality-trend", response_model=QualityTrendResponse)
async def get_quality_trend(
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
	days: int = Query(default=30, ge=1, le=365),
	granularity: Literal["hour", "day", "week", "month"] = Query(default="day"),
	quality_threshold: float = Query(default=70.0, ge=0, le=100),
):
	"""Average quality score and % of pages below threshold per time bucket."""
	tenant_id = str(user.tenant_id)
	since = _window_start(days)
	trunc = _trunc_expr(PageScanEventModel.occurred_at, granularity)

	q = (
		select(
			trunc.label("bucket"),
			func.avg(PageScanEventModel.quality_score).label("avg_quality"),
			func.count(PageScanEventModel.id).label("total"),
			func.sum(
				case(
					(PageScanEventModel.quality_score < quality_threshold, 1),
					else_=0,
				)
			).label("below_threshold"),
		)
		.where(
			and_(
				PageScanEventModel.tenant_id == tenant_id,
				PageScanEventModel.occurred_at >= since,
				PageScanEventModel.quality_score.isnot(None),
			)
		)
		.group_by("bucket")
		.order_by("bucket")
	)
	result = await session.execute(q)

	data = []
	for row in result:
		total = row.total or 1
		below_pct = round((row.below_threshold or 0) / total * 100, 2)
		data.append(
			QualityPoint(
				timestamp=str(row.bucket),
				avg_quality_score=round(float(row.avg_quality or 0), 2),
				below_threshold_pct=below_pct,
			)
		)
	return QualityTrendResponse(data=data)


# ─────────────────── operator performance endpoint ──────────────


@router.get("/operator-performance", response_model=OperatorPerformanceResponse)
async def get_operator_performance(
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
	days: int = Query(default=30, ge=1, le=365),
):
	"""Per-operator aggregated metrics for the given window."""
	tenant_id = str(user.tenant_id)
	since = _window_start(days)

	q = (
		select(
			OperatorDailyMetricsModel.operator_id,
			OperatorDailyMetricsModel.operator_name,
			func.sum(OperatorDailyMetricsModel.pages_scanned).label("pages_scanned"),
			func.avg(OperatorDailyMetricsModel.quality_score).label("avg_quality"),
			func.sum(OperatorDailyMetricsModel.issues_caused).label("exceptions_caused"),
			func.sum(OperatorDailyMetricsModel.pages_scanned).label("total_scanned"),
			func.sum(OperatorDailyMetricsModel.pages_verified).label("total_verified"),
		)
		.where(
			and_(
				OperatorDailyMetricsModel.project_id.isnot(None),
				OperatorDailyMetricsModel.metric_date >= since,
			)
		)
		.group_by(
			OperatorDailyMetricsModel.operator_id,
			OperatorDailyMetricsModel.operator_name,
		)
		.order_by(func.sum(OperatorDailyMetricsModel.pages_scanned).desc())
	)
	result = await session.execute(q)

	operators = []
	for row in result:
		total = row.total_scanned or 1
		on_time_rate = round(min((row.total_verified or 0) / total, 1.0) * 100, 2)
		operators.append(
			OperatorPerf(
				user_id=row.operator_id,
				name=row.operator_name or row.operator_id,
				pages_scanned=int(row.pages_scanned or 0),
				avg_quality=round(float(row.avg_quality or 0), 2),
				exceptions_caused=int(row.exceptions_caused or 0),
				on_time_rate=on_time_rate,
			)
		)
	return OperatorPerformanceResponse(operators=operators)


# ─────────────────────── capacity endpoint ──────────────────────


@router.get("/capacity", response_model=CapacityResponse)
async def get_capacity(
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
):
	"""Real-time capacity snapshot using active sessions and recent event rates."""
	tenant_id = str(user.tenant_id)
	window_start = _utc_now() - timedelta(hours=1)

	# Active workers: sessions that started in the last hour and haven't ended
	active_workers_q = select(func.count(ScanningSesssionModel.id)).where(
		and_(
			ScanningSesssionModel.operator_id.isnot(None),
			ScanningSesssionModel.ended_at.is_(None),
			ScanningSesssionModel.started_at >= _utc_now() - timedelta(hours=8),
		)
	)
	active_workers_result = await session.execute(active_workers_q)
	workers_active = active_workers_result.scalar() or 0

	# Pages scanned in last hour
	recent_pages_q = select(func.count(PageScanEventModel.id)).where(
		and_(
			PageScanEventModel.tenant_id == tenant_id,
			PageScanEventModel.occurred_at >= window_start,
			PageScanEventModel.event_type == "scanned",
		)
	)
	recent_pages_result = await session.execute(recent_pages_q)
	pages_last_hour = recent_pages_result.scalar() or 0

	# Average processing time (duration_ms) over last hour
	avg_duration_q = select(func.avg(PageScanEventModel.duration_ms)).where(
		and_(
			PageScanEventModel.tenant_id == tenant_id,
			PageScanEventModel.occurred_at >= window_start,
			PageScanEventModel.duration_ms.isnot(None),
		)
	)
	avg_duration_result = await session.execute(avg_duration_q)
	avg_duration_ms = avg_duration_result.scalar() or 0
	avg_processing_seconds = round(float(avg_duration_ms) / 1000, 3)

	# Queue depth: scanning_batches in status "pending" or "in_progress"
	queue_q = select(func.count(ScanningBatchModel.id)).where(
		ScanningBatchModel.status.in_(["pending", "in_progress"])
	)
	queue_result = await session.execute(queue_q)
	queue_depth = queue_result.scalar() or 0

	# Projected throughput
	est_throughput = float(pages_last_hour)  # pages/hour based on last hour

	# Backlog hours: total pages in pending batches / throughput
	if est_throughput > 0:
		pending_pages_q = select(
			func.sum(ScanningBatchModel.estimated_pages - ScanningBatchModel.scanned_pages)
		).where(ScanningBatchModel.status.in_(["pending", "in_progress"]))
		pending_pages_result = await session.execute(pending_pages_q)
		pending_pages = pending_pages_result.scalar() or 0
		projected_backlog_hours = round(float(pending_pages) / est_throughput, 2)
	else:
		projected_backlog_hours = 0.0

	return CapacityResponse(
		current_queue_depth=int(queue_depth),
		workers_active=int(workers_active),
		avg_processing_time_seconds=avg_processing_seconds,
		estimated_throughput_pages_per_hour=est_throughput,
		projected_backlog_hours=projected_backlog_hours,
	)


# ─────────────────────── summary endpoint ───────────────────────


@router.get("/summary", response_model=SummaryResponse)
async def get_summary(
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
	days: int = Query(default=7, ge=1, le=365),
):
	"""Combined analytics summary — one call for the dashboard overview."""
	throughput = await get_throughput(user=user, session=session, days=days, granularity="day")
	quality = await get_quality_trend(user=user, session=session, days=days, granularity="day")
	operators = await get_operator_performance(user=user, session=session, days=days)
	capacity = await get_capacity(user=user, session=session)

	return SummaryResponse(
		throughput=throughput,
		quality_trend=quality,
		operator_performance=operators,
		capacity=capacity,
	)

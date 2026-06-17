# (c) Copyright Datacraft, 2026
"""Scanning Operator Gamification endpoints — auto-discovered by router_loader.

Provides leaderboard and per-operator targets for the gamification layer.
"""
from datetime import date, datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select, and_, text
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.auth import get_current_user
from papermerge.core.db.engine import get_db
from papermerge.core.features.users.schema import User
from papermerge.core.features.scanning_projects.models import (
	OperatorDailyMetricsModel,
)

router = APIRouter(prefix="/analytics", tags=["analytics"])


# ──────────────────────────── helpers ────────────────────────────


def _utc_now() -> datetime:
	return datetime.now(timezone.utc)


def _period_start(period: str) -> datetime:
	now = _utc_now()
	if period == "today":
		return now.replace(hour=0, minute=0, second=0, microsecond=0)
	if period == "week":
		# Monday of the current week
		return (now - timedelta(days=now.weekday())).replace(
			hour=0, minute=0, second=0, microsecond=0
		)
	# month
	return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _last_n_days(n: int) -> list[date]:
	today = _utc_now().date()
	return [(today - timedelta(days=i)) for i in range(n - 1, -1, -1)]


# ──────────────────────────── schemas ────────────────────────────


class LeaderboardEntry(BaseModel):
	rank: int
	user_id: str
	username: str
	pages_scanned: int
	batches_completed: int
	avg_quality_score: float
	# Last 7 daily page counts, oldest first
	trend_pages: list[int]


class LeaderboardResponse(BaseModel):
	period: str
	entries: list[LeaderboardEntry]


class OperatorTargets(BaseModel):
	user_id: str
	daily_page_target: int
	weekly_batch_target: int


class SetTargetsBody(BaseModel):
	user_id: str
	daily_page_target: int
	weekly_batch_target: int


# ── simple in-process store for targets (replace with DB table if desired) ──

_targets_store: dict[str, dict[str, int]] = {}

_DEFAULT_DAILY_TARGET = 500
_DEFAULT_WEEKLY_BATCH = 20


# ─────────────────────── leaderboard endpoint ────────────────────


@router.get("/scanning/leaderboard", response_model=LeaderboardResponse)
async def get_scanning_leaderboard(
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
	period: str = Query(default="today", pattern="^(today|week|month)$"),
):
	"""Ranked operator leaderboard for the given period."""
	since = _period_start(period)

	# ── aggregate per operator for the period ──
	agg_q = (
		select(
			OperatorDailyMetricsModel.operator_id,
			OperatorDailyMetricsModel.operator_name,
			func.sum(OperatorDailyMetricsModel.pages_scanned).label("total_pages"),
			func.sum(OperatorDailyMetricsModel.documents_completed).label("total_batches"),
			func.avg(OperatorDailyMetricsModel.quality_score).label("avg_quality"),
		)
		.where(OperatorDailyMetricsModel.metric_date >= since)
		.group_by(
			OperatorDailyMetricsModel.operator_id,
			OperatorDailyMetricsModel.operator_name,
		)
		.order_by(func.sum(OperatorDailyMetricsModel.pages_scanned).desc())
	)
	agg_result = await session.execute(agg_q)
	rows = agg_result.fetchall()

	if not rows:
		return LeaderboardResponse(period=period, entries=[])

	# ── build 7-day trend for each operator ──
	trend_days = _last_n_days(7)
	operator_ids = [row.operator_id for row in rows]

	trend_q = (
		select(
			OperatorDailyMetricsModel.operator_id,
			func.date(OperatorDailyMetricsModel.metric_date).label("day"),
			func.sum(OperatorDailyMetricsModel.pages_scanned).label("pages"),
		)
		.where(
			and_(
				OperatorDailyMetricsModel.operator_id.in_(operator_ids),
				OperatorDailyMetricsModel.metric_date >= _utc_now() - timedelta(days=7),
			)
		)
		.group_by(
			OperatorDailyMetricsModel.operator_id,
			text("day"),
		)
	)
	trend_result = await session.execute(trend_q)

	# Build lookup: {operator_id: {date: pages}}
	trend_map: dict[str, dict[date, int]] = {}
	for tr in trend_result:
		op_id = tr.operator_id
		if op_id not in trend_map:
			trend_map[op_id] = {}
		# date() may return datetime or date depending on DB
		day_val = tr.day if isinstance(tr.day, date) else tr.day.date()
		trend_map[op_id][day_val] = int(tr.pages or 0)

	entries: list[LeaderboardEntry] = []
	for rank, row in enumerate(rows, start=1):
		op_trend = trend_map.get(row.operator_id, {})
		trend_pages = [op_trend.get(d, 0) for d in trend_days]
		entries.append(
			LeaderboardEntry(
				rank=rank,
				user_id=row.operator_id,
				username=row.operator_name or row.operator_id,
				pages_scanned=int(row.total_pages or 0),
				batches_completed=int(row.total_batches or 0),
				avg_quality_score=round(float(row.avg_quality or 0.0), 2),
				trend_pages=trend_pages,
			)
		)

	return LeaderboardResponse(period=period, entries=entries)


# ─────────────────────── targets endpoints ───────────────────────


@router.get("/scanning/targets", response_model=OperatorTargets)
async def get_operator_targets(
	user: Annotated[User, Depends(get_current_user)],
	_session: Annotated[AsyncSession, Depends(get_db)],
	user_id: str | None = Query(default=None),
):
	"""Return daily page and weekly batch targets for the given operator."""
	target_user_id = user_id or str(user.id)
	stored = _targets_store.get(target_user_id, {})
	return OperatorTargets(
		user_id=target_user_id,
		daily_page_target=stored.get("daily_page_target", _DEFAULT_DAILY_TARGET),
		weekly_batch_target=stored.get("weekly_batch_target", _DEFAULT_WEEKLY_BATCH),
	)


@router.put("/scanning/targets", response_model=OperatorTargets)
async def set_operator_targets(
	user: Annotated[User, Depends(get_current_user)],
	_session: Annotated[AsyncSession, Depends(get_db)],
	body: SetTargetsBody,
):
	"""Store (upsert) targets for an operator."""
	_targets_store[body.user_id] = {
		"daily_page_target": body.daily_page_target,
		"weekly_batch_target": body.weekly_batch_target,
	}
	return OperatorTargets(
		user_id=body.user_id,
		daily_page_target=body.daily_page_target,
		weekly_batch_target=body.weekly_batch_target,
	)

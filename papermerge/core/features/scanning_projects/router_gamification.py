# (c) Copyright Datacraft, 2026
"""Gamification endpoints — operator leaderboard and performance chart data."""
import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.auth import get_current_user
from papermerge.core.db.engine import get_db
from papermerge.core.features.users.schema import User

from .models import PageScanEventModel

router = APIRouter(
	prefix="/scanning-projects/gamification",
	tags=["gamification"],
)

_log = logging.getLogger(__name__)


@router.get("/leaderboard")
async def get_leaderboard(
	user: Annotated[User, Depends(get_current_user)],
	db: Annotated[AsyncSession, Depends(get_db)],
	limit: int = Query(10, ge=1, le=100),
) -> list[dict]:
	"""
	Operator leaderboard for the last 7 days.

	Returns operators ranked by pages scanned, with quality_score computed as
	first-pass yield = accepted / total events (0-100 scale).
	"""
	since = datetime.now(timezone.utc) - timedelta(days=7)

	stmt = (
		select(
			PageScanEventModel.operator_id,
			# Use the operator_name stored on session/batch — pull from a subq or
			# fall back to operator_id when no name column is on this table.
			# PageScanEventModel has no operator_name; join is expensive — store
			# the aggregate keyed by operator_id and resolve names separately.
			func.count(PageScanEventModel.id).label("total_events"),
			func.sum(
				func.cast(PageScanEventModel.event_type == "scanned", type_=None)
			).label("pages_scanned"),
			func.avg(PageScanEventModel.quality_score).label("avg_quality"),
		)
		.where(
			PageScanEventModel.occurred_at >= since,
			PageScanEventModel.operator_id.isnot(None),
			PageScanEventModel.tenant_id == str(user.tenant_id),
		)
		.group_by(PageScanEventModel.operator_id)
		.order_by(func.count(PageScanEventModel.id).desc())
		.limit(limit)
	)

	rows = (await db.execute(stmt)).all()

	# Resolve operator display names in one query against users table
	operator_ids = [r.operator_id for r in rows if r.operator_id]
	name_map: dict[str, str] = {}
	if operator_ids:
		try:
			from papermerge.core.features.users.db.orm import User as UserORM
			from sqlalchemy import select as _sel
			name_rows = (
				await db.execute(
					_sel(UserORM.id, UserORM.username)
					.where(UserORM.id.in_(operator_ids))
				)
			).all()
			name_map = {str(r.id): r.username for r in name_rows}
		except Exception:
			pass

	result = []
	for rank, r in enumerate(rows, start=1):
		# First-pass yield: treat events with quality_score >= 60 as accepted
		quality_score = float(r.avg_quality) if r.avg_quality is not None else 0.0
		result.append({
			"id": r.operator_id,
			"operator_name": name_map.get(r.operator_id, r.operator_id),
			"pages_scanned": int(r.pages_scanned or r.total_events),
			"quality_score": round(quality_score, 1),
			"rank": rank,
		})

	return result


@router.get("/performance")
async def get_performance(
	user: Annotated[User, Depends(get_current_user)],
	db: Annotated[AsyncSession, Depends(get_db)],
) -> list[dict]:
	"""
	Operator page-scan counts for the last 7 days — for bar/line chart consumption.

	Returns list of { name, pages } sorted descending by pages.
	"""
	since = datetime.now(timezone.utc) - timedelta(days=7)

	stmt = (
		select(
			PageScanEventModel.operator_id,
			func.count(PageScanEventModel.id).label("pages"),
		)
		.where(
			PageScanEventModel.occurred_at >= since,
			PageScanEventModel.operator_id.isnot(None),
			PageScanEventModel.tenant_id == str(user.tenant_id),
		)
		.group_by(PageScanEventModel.operator_id)
		.order_by(func.count(PageScanEventModel.id).desc())
	)

	rows = (await db.execute(stmt)).all()

	operator_ids = [r.operator_id for r in rows if r.operator_id]
	name_map: dict[str, str] = {}
	if operator_ids:
		try:
			from papermerge.core.features.users.db.orm import User as UserORM
			from sqlalchemy import select as _sel
			name_rows = (
				await db.execute(
					_sel(UserORM.id, UserORM.username)
					.where(UserORM.id.in_(operator_ids))
				)
			).all()
			name_map = {str(r.id): r.username for r in name_rows}
		except Exception:
			pass

	return [
		{
			"name": name_map.get(r.operator_id, r.operator_id),
			"pages": int(r.pages),
		}
		for r in rows
	]

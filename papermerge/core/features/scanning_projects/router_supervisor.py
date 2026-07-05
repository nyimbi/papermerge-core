# (c) Copyright Datacraft, 2026
"""Supervisor dashboard router for Scanning Projects feature.

Provides real-time KPI endpoints computed directly from page_scan_events.
These endpoints are separate from the gamification/leaderboard endpoints in
router.py which use pre-aggregated OperatorDailyMetricsModel tables.
"""
from datetime import datetime, date, timedelta, timezone
from typing import Annotated

import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select, and_, case, literal_column
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.auth import get_current_user
from papermerge.core.db.engine import get_db
from papermerge.core.features.auth import scopes
from papermerge.core.features.auth.dependencies import require_scopes
from papermerge.core.features.users.schema import User
from papermerge.core.utils.uuid_compat import uuid7str

from .models import (
	PageScanEventModel,
	ScanningBatchModel,
	ScanningProjectModel,
	ShiftAssignmentModel,
)

router = APIRouter(prefix="/scanning-projects/supervisor", tags=["supervisor-dashboard"])


# =====================================================
# Request / Response schemas
# =====================================================


class PageEventCreate(BaseModel):
	scan_job_id: str | None = None
	batch_id: str | None = None
	operator_id: str | None = None
	project_id: str | None = None
	session_id: str | None = None
	event_type: str  # scanned, accepted, rejected, rescanned, blank_detected
	page_number: int | None = None
	quality_score: float | None = None
	defects: list[str] | None = None
	duration_ms: int | None = None


class PageEventOut(BaseModel):
	id: str
	scan_job_id: str | None
	batch_id: str | None
	operator_id: str | None
	project_id: str | None
	session_id: str | None
	event_type: str
	page_number: int | None
	quality_score: float | None
	defects: list[str] | None
	duration_ms: int | None
	occurred_at: datetime
	tenant_id: str | None

	model_config = {"from_attributes": True}


class ActiveOperator(BaseModel):
	operator_id: str
	operator_name: str = ""
	status: str = "scanning"   # scanning | idle | break | offline
	current_batch: str | None = None
	pages_this_session: int = 0
	last_activity_at: str = ""


class LiveOpsResponse(BaseModel):
	operators: list[ActiveOperator]
	pages_scanned_today: int
	active_batches: int
	queue_depth: int  # batches pending/unassigned


class SupervisorOperatorStatus(BaseModel):
	operator_id: str
	operator_name: str = ""
	status: str = "idle"
	pages_scanned_today: int = 0
	quality_score: float = 100.0
	last_activity: str | None = None
	project_name: str | None = None
	batch_id: str | None = None


class SupervisorLiveOpsResponse(BaseModel):
	operators: list[SupervisorOperatorStatus] = Field(default_factory=list)
	pages_scanned_today: int = 0
	active_batches: int = 0
	queue_depth: int = 0


class OperatorKPI(BaseModel):
	operator_id: str
	operator_name: str = ""
	project_name: str = ""
	shift_hours: float
	pages_scanned: int
	pages_accepted: int
	pages_rescanned: int
	pages_per_hour: float
	rescan_rate: float
	first_pass_yield: float
	idle_time_min: int = 0
	sla_compliance_rate: float = 100.0


class TeamSummaryResponse(BaseModel):
	project_id: str | None
	location_id: str | None
	total_pages: int
	total_operators: int
	avg_pages_per_hour: float
	team_rescan_rate: float
	team_first_pass_yield: float
	operator_kpis: list[OperatorKPI]


class BatchKanbanItem(BaseModel):
	batch_id: str
	batch_number: str
	status: str
	scanned_pages: int
	estimated_pages: int
	assigned_operator_id: str | None
	assigned_operator_name: str | None


class BatchPipelineResponse(BaseModel):
	project_id: str
	unassigned: list[BatchKanbanItem]
	in_progress: list[BatchKanbanItem]
	qc_review: list[BatchKanbanItem]
	complete: list[BatchKanbanItem]


class SupervisorMessageCreate(BaseModel):
	operator_id: str | None = None
	project_id: str | None = None
	message: str = Field(min_length=1, max_length=2000)
	priority: str = Field(default="normal", pattern="^(low|normal|high|urgent)$")


class SupervisorMessageOut(BaseModel):
	id: str
	operator_id: str | None
	project_id: str | None
	message: str
	priority: str
	sent_by_id: str
	sent_by_name: str | None = None
	created_at: str


# =====================================================
# Helpers
# =====================================================

def _today_utc_start() -> datetime:
	now = datetime.now(timezone.utc)
	return datetime(now.year, now.month, now.day, tzinfo=timezone.utc)


def _compute_operator_kpi(
	operator_id: str,
	rows: list[tuple],  # (event_type, count, sum_duration_ms, avg_quality)
	session_hours: float,
	operator_name: str = "",
) -> OperatorKPI:
	counts: dict[str, int] = {}
	total_duration_ms = 0

	for event_type, cnt, dur_sum, avg_q in rows:
		counts[event_type] = int(cnt)
		if dur_sum:
			total_duration_ms += int(dur_sum)

	pages_scanned = counts.get("scanned", 0)
	pages_accepted = counts.get("accepted", 0)
	pages_rescanned = counts.get("rescanned", 0)
	pages_rejected = counts.get("rejected", 0)
	total_pages = pages_scanned + pages_accepted + pages_rejected + pages_rescanned

	hours = session_hours if session_hours > 0 else (total_duration_ms / 3_600_000 if total_duration_ms else 1)
	pages_per_hour = total_pages / hours if hours > 0 else 0.0
	rescan_rate = pages_rescanned / total_pages if total_pages > 0 else 0.0
	denominator = pages_accepted + pages_rejected
	first_pass_yield = pages_accepted / denominator if denominator > 0 else 1.0

	return OperatorKPI(
		operator_id=operator_id,
		operator_name=operator_name,
		project_name="",
		shift_hours=round(hours, 2),
		pages_scanned=pages_scanned,
		pages_accepted=pages_accepted,
		pages_rescanned=pages_rescanned,
		pages_per_hour=round(pages_per_hour, 2),
		rescan_rate=round(rescan_rate, 4),
		first_pass_yield=round(first_pass_yield, 4),
		idle_time_min=0,
		sla_compliance_rate=100.0,
	)


async def _get_supervisor_operator_statuses(
	session: AsyncSession,
	tenant_id: object,
) -> list[SupervisorOperatorStatus]:
	now = datetime.now(timezone.utc).replace(tzinfo=None)
	today_start = datetime(now.year, now.month, now.day)
	active_cutoff = now - timedelta(minutes=60)

	try:
		stmt = (
			select(
				ScanningBatchModel.id,
				ScanningBatchModel.assigned_operator_id,
				ScanningBatchModel.assigned_operator_name,
				ScanningBatchModel.status,
				ScanningBatchModel.scanned_pages,
				ScanningBatchModel.actual_pages,
				ScanningBatchModel.completed_at,
				ScanningBatchModel.started_at,
				ScanningBatchModel.updated_at,
				ScanningBatchModel.created_at,
				ScanningProjectModel.name.label("project_name"),
			)
			.join(
				ScanningProjectModel,
				ScanningProjectModel.id == ScanningBatchModel.project_id,
			)
			.where(
				ScanningProjectModel.tenant_id == tenant_id,
				ScanningBatchModel.assigned_operator_id.isnot(None),
			)
		)
		rows = (await session.execute(stmt)).all()
	except SQLAlchemyError:
		return []

	by_operator: dict[str, dict] = {}
	for row in rows:
		operator_id = str(row.assigned_operator_id)
		last_activity = row.completed_at or row.updated_at or row.started_at or row.created_at
		status_value = getattr(row.status, "value", row.status) or "idle"
		pages = int(row.scanned_pages or row.actual_pages or 0)

		entry = by_operator.setdefault(
			operator_id,
			{
				"operator_id": operator_id,
				"operator_name": row.assigned_operator_name or "",
				"status": "idle",
				"pages_scanned_today": 0,
				"quality_score": 100.0,
				"last_activity": None,
				"project_name": None,
				"batch_id": None,
			},
		)
		if (row.completed_at and row.completed_at >= today_start) or (
			last_activity and last_activity >= today_start and status_value in {"in_progress", "scanning", "completed"}
		):
			entry["pages_scanned_today"] += pages
		if last_activity and (
			entry["last_activity"] is None or last_activity > entry["last_activity"]
		):
			entry["last_activity"] = last_activity
			entry["project_name"] = row.project_name
			entry["batch_id"] = str(row.id)
			entry["status"] = (
				"scanning"
				if last_activity >= active_cutoff and status_value in {"in_progress", "scanning"}
				else "idle"
			)

	return [
		SupervisorOperatorStatus(
			**{
				**entry,
				"last_activity": (
					entry["last_activity"].isoformat()
					if entry["last_activity"]
					else None
				),
			}
		)
		for entry in by_operator.values()
	]


# =====================================================
# Endpoints
# =====================================================


@router.get("/live-ops", response_model=SupervisorLiveOpsResponse)
async def get_live_ops(
	user: require_scopes(scopes.NODE_VIEW),
	session: Annotated[AsyncSession, Depends(get_db)],
) -> SupervisorLiveOpsResponse:
	"""Return supervisor live-ops operator rows for the frontend dashboard."""
	operators = await _get_supervisor_operator_statuses(session, user.tenant_id)
	active_batches_stmt = select(func.count(ScanningBatchModel.id)).where(
		ScanningBatchModel.status.in_(["in_progress", "scanning"])
	)
	queue_stmt = select(func.count(ScanningBatchModel.id)).where(
		ScanningBatchModel.status.in_(["pending", "unassigned"])
	)
	active_batches = await session.scalar(active_batches_stmt) or 0
	queue_depth = await session.scalar(queue_stmt) or 0
	return SupervisorLiveOpsResponse(
		operators=operators,
		pages_scanned_today=sum(op.pages_scanned_today for op in operators),
		active_batches=active_batches,
		queue_depth=queue_depth,
	)


@router.get("/operator-kpis", response_model=list[OperatorKPI])
async def get_operator_kpis(
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
	project_id: str | None = Query(None),
	period: str | None = Query(None),  # today | week | month (overrides date_from/date_to)
	date_from: date | None = Query(None),
	date_to: date | None = Query(None),
	operator_id: str | None = Query(None),
) -> list[OperatorKPI]:
	# Resolve period shorthand to date range
	if period:
		now = datetime.now(timezone.utc)
		if period == "today":
			date_from = now.date()
		elif period == "week":
			date_from = (now - timedelta(days=7)).date()
		elif period == "month":
			date_from = (now - timedelta(days=30)).date()
	"""Per-operator KPIs: pages/hour, rescan rate, first-pass yield, session hours."""
	tenant_id = str(user.tenant_id)

	filters = [PageScanEventModel.tenant_id == tenant_id]
	if project_id:
		filters.append(PageScanEventModel.project_id == project_id)
	if operator_id:
		filters.append(PageScanEventModel.operator_id == operator_id)
	if date_from:
		filters.append(PageScanEventModel.occurred_at >= datetime(date_from.year, date_from.month, date_from.day))
	if date_to:
		dt_to = datetime(date_to.year, date_to.month, date_to.day) + timedelta(days=1)
		filters.append(PageScanEventModel.occurred_at < dt_to)

	# Aggregate event counts per operator per event_type
	event_stmt = (
		select(
			PageScanEventModel.operator_id,
			PageScanEventModel.event_type,
			func.count(PageScanEventModel.id).label("cnt"),
			func.sum(PageScanEventModel.duration_ms).label("dur_sum"),
			func.avg(PageScanEventModel.quality_score).label("avg_quality"),
		)
		.where(and_(*filters))
		.where(PageScanEventModel.operator_id.isnot(None))
		.group_by(PageScanEventModel.operator_id, PageScanEventModel.event_type)
	)
	result = await session.execute(event_stmt)
	rows = result.all()

	# Group by operator
	by_operator: dict[str, list] = {}
	for row in rows:
		op_id = str(row.operator_id)
		by_operator.setdefault(op_id, []).append(
			(row.event_type, row.cnt, row.dur_sum, row.avg_quality)
		)

	# Get session hours from shift_assignments
	shift_filters = []
	if date_from:
		shift_filters.append(ShiftAssignmentModel.assignment_date >= datetime(date_from.year, date_from.month, date_from.day))
	if date_to:
		dt_to = datetime(date_to.year, date_to.month, date_to.day) + timedelta(days=1)
		shift_filters.append(ShiftAssignmentModel.assignment_date < dt_to)
	if operator_id:
		shift_filters.append(ShiftAssignmentModel.operator_id == operator_id)

	shift_stmt = select(
		ShiftAssignmentModel.operator_id,
		func.sum(
			func.extract("epoch", ShiftAssignmentModel.actual_end) -
			func.extract("epoch", ShiftAssignmentModel.actual_start)
		).label("total_seconds"),
	).where(
		and_(
			ShiftAssignmentModel.actual_start.isnot(None),
			ShiftAssignmentModel.actual_end.isnot(None),
			*shift_filters,
		)
	).group_by(ShiftAssignmentModel.operator_id)

	shift_result = await session.execute(shift_stmt)
	session_hours_map: dict[str, float] = {
		str(r.operator_id): (r.total_seconds or 0) / 3600
		for r in shift_result.all()
	}

	kpis = []
	for op_id, op_rows in by_operator.items():
		sh = session_hours_map.get(op_id, 0.0)
		kpis.append(_compute_operator_kpi(op_id, op_rows, sh))

	return kpis


@router.get("/kpis", response_model=list[SupervisorOperatorStatus])
async def get_kpis_alias(
	user: require_scopes(scopes.NODE_VIEW),
	session: AsyncSession = Depends(get_db),
	project_id: str | None = Query(None),
	period: str | None = Query(None),
	date_from: date | None = Query(None),
	date_to: date | None = Query(None),
	operator_id: str | None = Query(None),
) -> list[SupervisorOperatorStatus]:
	"""Compatibility KPI endpoint with the frontend supervisor field shape."""
	operators = await _get_supervisor_operator_statuses(session, user.tenant_id)
	if operator_id:
		operators = [item for item in operators if item.operator_id == operator_id]
	return operators


@router.get("/messages", response_model=list[SupervisorMessageOut])
async def list_supervisor_messages(
	user: require_scopes(scopes.NODE_VIEW),
	session: AsyncSession = Depends(get_db),
	operator_id: str | None = Query(None),
	project_id: str | None = Query(None),
	limit: int = Query(50, ge=1, le=200),
) -> list[SupervisorMessageOut]:
	"""List recent supervisor messages persisted in system settings."""
	from papermerge.core.features.settings.db import api as settings_api

	stored = await settings_api.get_settings(session, "supervisor_messages")
	messages = stored.get("items", [])
	filtered = [
		msg for msg in messages
		if (operator_id is None or msg.get("operator_id") == operator_id)
		and (project_id is None or msg.get("project_id") == project_id)
	]
	return [SupervisorMessageOut(**msg) for msg in filtered[:limit]]


@router.post("/messages", response_model=SupervisorMessageOut, status_code=status.HTTP_201_CREATED)
async def send_supervisor_message(
	body: SupervisorMessageCreate,
	user: require_scopes(scopes.NODE_VIEW),
	session: AsyncSession = Depends(get_db),
) -> SupervisorMessageOut:
	"""Send a supervisor message to an operator or project feed."""
	from papermerge.core.features.settings.db import api as settings_api

	stored = await settings_api.get_settings(session, "supervisor_messages")
	messages = stored.get("items", [])
	message = SupervisorMessageOut(
		id=uuid7str(),
		operator_id=body.operator_id,
		project_id=body.project_id,
		message=body.message,
		priority=body.priority,
		sent_by_id=str(user.id),
		sent_by_name=getattr(user, "username", None),
		created_at=datetime.now(timezone.utc).isoformat(),
	)
	await settings_api.upsert_settings(
		session,
		"supervisor_messages",
		{"items": [message.model_dump(), *messages][:500]},
		str(user.id),
	)
	return message





@router.get("/operator-kpis/export")
async def export_operator_kpis(
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
	format: str = Query("csv", pattern="^(csv|pdf)$"),
	days: int = Query(30, ge=1, le=365),
	project_id: str | None = Query(None),
	operator_id: str | None = Query(None),
) -> Response:
	"""Export operator KPIs as CSV or printable HTML.

	CSV: attachment download with standard KPI columns.
	PDF: HTML table with print stylesheet — open in new tab and use browser print.
	"""
	from datetime import date as date_type

	date_from = (datetime.now(timezone.utc) - timedelta(days=days)).date()
	tenant_id = str(user.tenant_id)

	filters = [PageScanEventModel.tenant_id == tenant_id]
	if project_id:
		filters.append(PageScanEventModel.project_id == project_id)
	if operator_id:
		filters.append(PageScanEventModel.operator_id == operator_id)
	filters.append(
		PageScanEventModel.occurred_at >= datetime(date_from.year, date_from.month, date_from.day)
	)

	event_stmt = (
		select(
			PageScanEventModel.operator_id,
			PageScanEventModel.event_type,
			func.count(PageScanEventModel.id).label("cnt"),
			func.sum(PageScanEventModel.duration_ms).label("dur_sum"),
			func.avg(PageScanEventModel.quality_score).label("avg_quality"),
		)
		.where(and_(*filters))
		.where(PageScanEventModel.operator_id.isnot(None))
		.group_by(PageScanEventModel.operator_id, PageScanEventModel.event_type)
	)
	result = await session.execute(event_stmt)
	rows = result.all()

	by_operator: dict[str, list] = {}
	for row in rows:
		op_id = str(row.operator_id)
		by_operator.setdefault(op_id, []).append(
			(row.event_type, row.cnt, row.dur_sum, row.avg_quality)
		)

	shift_stmt = select(
		ShiftAssignmentModel.operator_id,
		func.sum(
			func.extract("epoch", ShiftAssignmentModel.actual_end) -
			func.extract("epoch", ShiftAssignmentModel.actual_start)
		).label("total_seconds"),
	).where(
		and_(
			ShiftAssignmentModel.actual_start.isnot(None),
			ShiftAssignmentModel.actual_end.isnot(None),
			ShiftAssignmentModel.assignment_date >= datetime(date_from.year, date_from.month, date_from.day),
		)
	).group_by(ShiftAssignmentModel.operator_id)

	shift_result = await session.execute(shift_stmt)
	session_hours_map: dict[str, float] = {
		str(r.operator_id): (r.total_seconds or 0) / 3600
		for r in shift_result.all()
	}

	kpis = [
		_compute_operator_kpi(op_id, op_rows, session_hours_map.get(op_id, 0.0))
		for op_id, op_rows in by_operator.items()
	]

	today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

	if format == "csv":
		buf = io.StringIO()
		writer = csv.writer(buf)
		writer.writerow([
			"Operator", "Project", "Shift Hours", "Pages Scanned",
			"Pages Accepted", "Pages Rescanned", "Pages/hr",
			"Rescan%", "First-Pass Yield%", "SLA Compliance%",
		])
		for k in kpis:
			writer.writerow([
				k.operator_name or k.operator_id,
				k.project_name,
				f"{k.shift_hours:.2f}",
				k.pages_scanned,
				k.pages_accepted,
				k.pages_rescanned,
				f"{k.pages_per_hour:.1f}",
				f"{k.rescan_rate * 100:.1f}",
				f"{k.first_pass_yield * 100:.1f}",
				f"{k.sla_compliance_rate * 100:.1f}",
			])
		return Response(
			content=buf.getvalue(),
			media_type="text/csv",
			headers={
				"Content-Disposition": f"attachment; filename=operator-kpis-{today_str}.csv",
			},
		)

	# format == "pdf" — styled HTML table for browser print
	rows_html = ""
	for k in kpis:
		rows_html += f"""
		<tr>
			<td>{k.operator_name or k.operator_id}</td>
			<td>{k.project_name}</td>
			<td class="num">{k.shift_hours:.2f}</td>
			<td class="num">{k.pages_scanned}</td>
			<td class="num">{k.pages_accepted}</td>
			<td class="num">{k.pages_rescanned}</td>
			<td class="num">{k.pages_per_hour:.1f}</td>
			<td class="num">{k.rescan_rate * 100:.1f}%</td>
			<td class="num">{k.first_pass_yield * 100:.1f}%</td>
			<td class="num">{k.sla_compliance_rate * 100:.1f}%</td>
		</tr>"""

	html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Operator KPIs — {today_str}</title>
<style>
  body {{ font-family: Arial, sans-serif; font-size: 11px; color: #111; margin: 1.5cm; }}
  h1 {{ font-size: 16px; margin-bottom: 4px; }}
  p.meta {{ color: #555; font-size: 10px; margin-bottom: 16px; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ border: 1px solid #ccc; padding: 5px 8px; white-space: nowrap; }}
  th {{ background: #f0f0f0; font-weight: 600; text-align: left; }}
  td.num {{ text-align: right; }}
  tr:nth-child(even) {{ background: #fafafa; }}
  @media print {{
    body {{ margin: 1cm; }}
    button {{ display: none; }}
  }}
</style>
</head>
<body>
<h1>Operator KPIs Report</h1>
<p class="meta">Generated: {today_str} &nbsp;|&nbsp; Period: last {days} days</p>
<button onclick="window.print()" style="margin-bottom:12px;padding:6px 14px;cursor:pointer;">Print / Save as PDF</button>
<table>
<thead>
  <tr>
    <th>Operator</th><th>Project</th><th>Shift Hrs</th>
    <th>Scanned</th><th>Accepted</th><th>Rescanned</th>
    <th>Pages/hr</th><th>Rescan%</th><th>FPY%</th><th>SLA%</th>
  </tr>
</thead>
<tbody>{rows_html}
</tbody>
</table>
</body>
</html>"""

	return Response(
		content=html,
		media_type="text/html",
		headers={
			"Content-Disposition": f"inline; filename=operator-kpis-{today_str}.html",
		},
	)


@router.get("/team-summary", response_model=TeamSummaryResponse)
async def get_team_summary(
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
	project_id: str | None = Query(None),
	location_id: str | None = Query(None),
) -> TeamSummaryResponse:
	"""Aggregated team KPIs by project/location for today."""
	tenant_id = str(user.tenant_id)
	today_start = _today_utc_start()

	filters = [
		PageScanEventModel.tenant_id == tenant_id,
		PageScanEventModel.occurred_at >= today_start,
	]
	if project_id:
		filters.append(PageScanEventModel.project_id == project_id)

	# Reuse operator-kpi logic with today filter
	event_stmt = (
		select(
			PageScanEventModel.operator_id,
			PageScanEventModel.event_type,
			func.count(PageScanEventModel.id).label("cnt"),
			func.sum(PageScanEventModel.duration_ms).label("dur_sum"),
			func.avg(PageScanEventModel.quality_score).label("avg_quality"),
		)
		.where(and_(*filters))
		.where(PageScanEventModel.operator_id.isnot(None))
		.group_by(PageScanEventModel.operator_id, PageScanEventModel.event_type)
	)
	result = await session.execute(event_stmt)
	rows = result.all()

	by_operator: dict[str, list] = {}
	for row in rows:
		op_id = str(row.operator_id)
		by_operator.setdefault(op_id, []).append(
			(row.event_type, row.cnt, row.dur_sum, row.avg_quality)
		)

	operator_kpis = [
		_compute_operator_kpi(op_id, op_rows, 0.0)
		for op_id, op_rows in by_operator.items()
	]

	total_pages = sum(k.pages_scanned for k in operator_kpis)
	total_operators = len(operator_kpis)
	avg_pph = (
		sum(k.pages_per_hour for k in operator_kpis) / total_operators
		if total_operators > 0 else 0.0
	)
	team_rescan_rate = (
		sum(k.pages_rescanned for k in operator_kpis) / total_pages
		if total_pages > 0 else 0.0
	)
	total_accepted = sum(k.pages_accepted for k in operator_kpis)
	team_fpy = total_accepted / total_pages if total_pages > 0 else 1.0

	return TeamSummaryResponse(
		project_id=project_id,
		location_id=location_id,
		total_pages=total_pages,
		total_operators=total_operators,
		avg_pages_per_hour=round(avg_pph, 2),
		team_rescan_rate=round(team_rescan_rate, 4),
		team_first_pass_yield=round(team_fpy, 4),
		operator_kpis=operator_kpis,
	)


@router.post("/page-event", response_model=PageEventOut, status_code=status.HTTP_201_CREATED)
async def record_page_event(
	body: PageEventCreate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> PageEventOut:
	"""Record a single page scan event. Called by the Scan Agent for each page action."""
	valid_event_types = {"scanned", "accepted", "rejected", "rescanned", "blank_detected"}
	if body.event_type not in valid_event_types:
		raise HTTPException(
			status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
			detail=f"event_type must be one of {sorted(valid_event_types)}",
		)

	event = PageScanEventModel(
		id=uuid7str(),
		scan_job_id=body.scan_job_id,
		batch_id=body.batch_id,
		operator_id=body.operator_id,
		project_id=body.project_id,
		session_id=body.session_id,
		event_type=body.event_type,
		page_number=body.page_number,
		quality_score=body.quality_score,
		defects={"defects": body.defects} if body.defects else None,
		duration_ms=body.duration_ms,
		occurred_at=datetime.now(timezone.utc).replace(tzinfo=None),
		tenant_id=str(user.tenant_id),
	)
	session.add(event)
	await session.commit()
	await session.refresh(event)

	defects_list: list[str] | None = None
	if event.defects and isinstance(event.defects, dict):
		defects_list = event.defects.get("defects")

	return PageEventOut(
		id=event.id,
		scan_job_id=event.scan_job_id,
		batch_id=event.batch_id,
		operator_id=event.operator_id,
		project_id=event.project_id,
		session_id=event.session_id,
		event_type=event.event_type,
		page_number=event.page_number,
		quality_score=event.quality_score,
		defects=defects_list,
		duration_ms=event.duration_ms,
		occurred_at=event.occurred_at,
		tenant_id=event.tenant_id,
	)


# =====================================================
# Batch pipeline (Kanban) — lives under /{project_id}
# so it goes on a separate router to avoid prefix conflicts
# =====================================================

project_router = APIRouter(prefix="/scanning-projects", tags=["supervisor-dashboard"])


@project_router.get("/{project_id}/batch-pipeline", response_model=BatchPipelineResponse)
async def get_batch_pipeline(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> BatchPipelineResponse:
	"""Kanban view of batches for a project: unassigned / in_progress / qc_review / complete."""
	stmt = select(ScanningBatchModel).where(
		ScanningBatchModel.project_id == project_id
	)
	result = await session.execute(stmt)
	batches = result.scalars().all()

	kanban: dict[str, list[BatchKanbanItem]] = {
		"unassigned": [],
		"in_progress": [],
		"qc_review": [],
		"complete": [],
	}

	status_map = {
		"pending": "unassigned",
		"unassigned": "unassigned",
		"assigned": "unassigned",
		"in_progress": "in_progress",
		"scanning": "in_progress",
		"paused": "in_progress",
		"qc_review": "qc_review",
		"qc_in_progress": "qc_review",
		"completed": "complete",
		"complete": "complete",
		"verified": "complete",
	}

	for batch in batches:
		item = BatchKanbanItem(
			batch_id=str(batch.id),
			batch_number=batch.batch_number,
			status=str(batch.status.value) if hasattr(batch.status, "value") else str(batch.status),
			scanned_pages=batch.scanned_pages,
			estimated_pages=batch.estimated_pages,
			assigned_operator_id=str(batch.assigned_operator_id) if batch.assigned_operator_id else None,
			assigned_operator_name=batch.assigned_operator_name,
		)
		lane = status_map.get(
			str(batch.status.value if hasattr(batch.status, "value") else batch.status),
			"unassigned",
		)
		kanban[lane].append(item)

	return BatchPipelineResponse(
		project_id=project_id,
		unassigned=kanban["unassigned"],
		in_progress=kanban["in_progress"],
		qc_review=kanban["qc_review"],
		complete=kanban["complete"],
	)

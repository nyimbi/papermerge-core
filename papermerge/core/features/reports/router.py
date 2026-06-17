# (c) Copyright Datacraft, 2026
"""REST endpoints for weekly KPI reports.

POST /reports/weekly-kpi/send-now  — manually trigger the weekly report
GET  /reports/weekly-kpi/preview   — return HTML preview for the current tenant
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.engine import get_db
from papermerge.core.features.auth import scopes
from papermerge.core.features.auth.dependencies import require_scopes
from papermerge.core.features.users.schema import User

from papermerge.core.features.reports.weekly_kpi import (
	generate_weekly_kpi_report,
	render_weekly_kpi_html,
)

router = APIRouter(prefix="/reports", tags=["reports"])


@router.post(
	"/weekly-kpi/send-now",
	summary="Manually trigger the weekly KPI report for the current tenant",
)
async def send_weekly_kpi_now(
	user: Annotated[User, Depends(require_scopes(scopes.NODE_VIEW))],
	db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
	"""
	Enqueues (or runs synchronously) the weekly KPI task for the caller's
	tenant.  Useful for manual testing without waiting for the Monday schedule.
	"""
	from papermerge.core.features.reports.tasks import send_weekly_kpi_reports

	# Dispatch as a Celery task so it runs through the normal worker pipeline.
	# apply_async returns immediately; the task result can be polled via Flower.
	result = send_weekly_kpi_reports.apply_async()
	return {"queued": True, "task_id": result.id}


@router.get(
	"/weekly-kpi/preview",
	response_class=HTMLResponse,
	summary="HTML preview of the weekly KPI report for the current tenant",
)
async def preview_weekly_kpi(
	user: Annotated[User, Depends(require_scopes(scopes.NODE_VIEW))],
	db: Annotated[AsyncSession, Depends(get_db)],
) -> HTMLResponse:
	"""
	Generate and return the weekly KPI HTML email for the current user's
	tenant without sending it.  Lets supervisors inspect the report in a
	browser before the scheduled send.
	"""
	tenant_id = str(user.tenant_id)
	report = await generate_weekly_kpi_report(tenant_id, db)
	html = render_weekly_kpi_html(report, recipient_name=user.username)
	return HTMLResponse(content=html)

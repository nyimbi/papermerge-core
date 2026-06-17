# (c) Copyright Datacraft, 2026
"""Celery task: send weekly KPI reports to all tenant supervisors.

WIRING NEEDED: Add to celery_app.py task_routes and beat_schedule:

  task_routes["darchiva.reports.weekly_kpi"] = {"queue": prefixed("core")}

  beat_schedule["weekly-kpi-report"] = {
      "task": "darchiva.reports.weekly_kpi",
      "schedule": crontab(day_of_week=1, hour=8, minute=0),  # every Monday 08:00 UTC
  }
"""
from __future__ import annotations

import asyncio
import logging

from celery import shared_task

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Async helpers
# ---------------------------------------------------------------------------

async def _get_active_tenant_ids() -> list[str]:
	"""Return IDs of all tenants with status='active'."""
	from papermerge.core.db.engine import get_async_session_maker
	from papermerge.core.features.tenants.db.orm import Tenant, TenantStatus
	from sqlalchemy import select

	async_session = get_async_session_maker()
	async with async_session() as session:
		rows = await session.execute(
			select(Tenant.id).where(Tenant.status == TenantStatus.ACTIVE.value)
		)
		return [str(r[0]) for r in rows.all()]


async def _get_supervisor_emails(tenant_id: str, session) -> list[tuple[str, str]]:
	"""
	Return (email, username) pairs for active supervisors of tenant_id.

	Supervisors = active users in the tenant whose role name contains 'supervisor'.
	"""
	from papermerge.core.features.users.db.orm import User
	from papermerge.core.features.roles.db.orm import Role, UserRole
	from sqlalchemy import select
	import uuid

	tid = uuid.UUID(tenant_id)
	rows = await session.execute(
		select(User.email, User.username)
		.join(UserRole, UserRole.user_id == User.id)
		.join(Role, Role.id == UserRole.role_id)
		.where(
			User.tenant_id == tid,
			User.is_active.is_(True),
			Role.name.ilike("%supervisor%"),
		)
	)
	return [(r.email, r.username) for r in rows.all()]


async def _run_for_tenant(tenant_id: str) -> dict:
	"""Generate the KPI report and email all supervisors for one tenant."""
	from papermerge.core.db.engine import get_async_session_maker
	from papermerge.core.features.reports.weekly_kpi import (
		generate_weekly_kpi_report,
		render_weekly_kpi_html,
	)
	from papermerge.core.features.email_notifications.service import EmailService

	sent: list[str] = []
	failed: list[str] = []

	async_session = get_async_session_maker()
	async with async_session() as session:
		report = await generate_weekly_kpi_report(tenant_id, session)
		supervisors = await _get_supervisor_emails(tenant_id, session)

	if not supervisors:
		_log.warning("weekly_kpi: no supervisors found for tenant %s", tenant_id)
		return {"tenant_id": tenant_id, "sent": [], "failed": []}

	svc = EmailService()
	period = f"{report['period_start']} to {report['period_end']}"
	subject = f"dArchiva Weekly KPI Report — {period}"

	for email, username in supervisors:
		try:
			html = render_weekly_kpi_html(report, recipient_name=username)
			svc.send_sync(email, subject, html)
			sent.append(email)
			_log.info("weekly_kpi: sent to %s (tenant=%s)", email, tenant_id)
		except Exception as exc:
			failed.append(email)
			_log.error(
				"weekly_kpi: failed to send to %s (tenant=%s): %s",
				email, tenant_id, exc,
			)

	return {"tenant_id": tenant_id, "sent": sent, "failed": failed}


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------

@shared_task(
	bind=True,
	max_retries=2,
	default_retry_delay=300,
	name="darchiva.reports.weekly_kpi",
)
def send_weekly_kpi_reports(self) -> dict:
	"""
	Generate and dispatch weekly KPI email reports for all active tenants.

	For each tenant: queries KPI data for the last 7 days, renders an HTML
	email, and sends it to every user with a supervisor role.
	"""
	_log.info("weekly_kpi: task started")

	loop = asyncio.new_event_loop()
	try:
		tenant_ids = loop.run_until_complete(_get_active_tenant_ids())
		if not tenant_ids:
			_log.warning("weekly_kpi: no active tenants found — nothing to send")
			return {"tenants": []}

		results = []
		for tid in tenant_ids:
			try:
				result = loop.run_until_complete(_run_for_tenant(tid))
				results.append(result)
			except Exception as exc:
				_log.error("weekly_kpi: unhandled error for tenant %s: %s", tid, exc)
				results.append({"tenant_id": tid, "error": str(exc)})

		total_sent = sum(len(r.get("sent", [])) for r in results)
		total_failed = sum(len(r.get("failed", [])) for r in results)
		_log.info(
			"weekly_kpi: complete — tenants=%d sent=%d failed=%d",
			len(tenant_ids), total_sent, total_failed,
		)
		return {"tenants": results, "total_sent": total_sent, "total_failed": total_failed}
	finally:
		loop.close()

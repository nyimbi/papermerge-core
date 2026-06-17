# (c) Copyright Datacraft, 2026
"""
Scanning-project SLA breach detection.

Called from the workflow.deadline_monitor Celery beat task every 5 minutes.
Checks two independent breach surfaces:

1. Per-project SLAModel records (sla_type, threshold_warning/threshold_critical)
   — marks status, creates SLAAlertModel if not already present for this cycle.

2. Project-level deadline proximity on ScanningProjectModel.target_end_date
   — creates synthetic "deadline_approaching" / "deadline_missed" SLAAlertModel
     entries keyed to a sentinel SLAModel (sla_type="completion", auto-created
     if absent) so the front-end `/sla-alerts` endpoint surfaces them.

For each new alert a Notification row is created for the project creator
(acting as supervisor).  No duplicate alerts are raised if one already exists
for the same (sla_id, alert_type) that has not been acknowledged.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.features.scanning_projects.models import (
	ScanningProjectModel,
	SLAAlertModel,
	SLAModel,
)
from papermerge.core.features.notifications.db.orm import Notification
from papermerge.core.utils.tz import utc_now
from papermerge.core.utils.uuid_compat import uuid7str

logger = logging.getLogger(__name__)

# How far ahead of target_end_date to issue a "warning" alert.
DEADLINE_WARNING_HOURS = 2

# Terminal project statuses that should not trigger deadline alerts.
_TERMINAL_STATUSES = frozenset({"completed", "cancelled", "archived"})

# Terminal batch statuses — not directly used here but kept for reference.
_TERMINAL_BATCH_STATUSES = frozenset({"completed", "returned", "cancelled"})


def _now_utc() -> datetime:
	return datetime.now(timezone.utc)


def _strip_tz(dt: datetime) -> datetime:
	"""Normalise to naive UTC so comparisons with naive DB datetimes work."""
	if dt.tzinfo is not None:
		return dt.replace(tzinfo=None)
	return dt


async def _alert_exists(
	session: AsyncSession,
	sla_id: str,
	alert_type: str,
) -> bool:
	"""Return True if an unacknowledged alert of this type already exists."""
	stmt = select(SLAAlertModel).where(
		SLAAlertModel.sla_id == sla_id,
		SLAAlertModel.alert_type == alert_type,
		SLAAlertModel.acknowledged_at.is_(None),
	)
	result = await session.execute(stmt)
	return result.scalar_one_or_none() is not None


async def _create_alert(
	session: AsyncSession,
	sla_id: str,
	alert_type: str,
	message: str,
	current_value: float,
	target_value: float,
) -> SLAAlertModel:
	alert = SLAAlertModel(
		id=uuid7str(),
		sla_id=sla_id,
		alert_type=alert_type,
		message=message,
		current_value=current_value,
		target_value=target_value,
	)
	session.add(alert)
	return alert


async def _notify_project_creator(
	session: AsyncSession,
	project: ScanningProjectModel,
	title: str,
	message: str,
	alert_type: str,
) -> None:
	"""Create an in-app Notification for the project creator."""
	try:
		notif = Notification(
			id=uuid7str(),
			user_id=project.created_by,
			type="warning" if alert_type == "warning" else "error",
			title=title,
			message=message,
			read=False,
			link=f"/scanning-projects/{project.id}",
			extra={
				"project_id": str(project.id),
				"alert_type": alert_type,
				"source": "sla_monitor",
			},
		)
		session.add(notif)
	except Exception as exc:  # noqa: BLE001
		# Notification failure must not abort the alert transaction.
		logger.warning("sla_monitor: failed to create notification for project %s: %s", project.id, exc)


async def _email_sla_alert(
	session: AsyncSession,
	project: ScanningProjectModel,
	batch_name: str,
	deadline: str,
	breach_type: str,
) -> None:
	"""Dispatch a send_email_notification Celery task if the project creator wants SLA emails."""
	try:
		from papermerge.core.features.email_notifications.preferences import get_email_prefs
		from papermerge.core.features.email_notifications import service as email_svc
		from papermerge.core.features.email_notifications.tasks import send_email_notification

		user_id = str(project.created_by)
		prefs = await get_email_prefs(session, user_id)
		if not prefs.get("sla_breach"):
			return

		# Resolve recipient: prefer override address, else look up user.email
		recipient = prefs.get("notification_email", "")
		if not recipient:
			from papermerge.core.features.users.db.orm import User as UserORM
			from sqlalchemy import select as _select
			row = await session.execute(_select(UserORM).where(UserORM.id == user_id))
			u = row.scalar_one_or_none()
			recipient = u.email if u else ""

		if not recipient:
			return

		html = email_svc.sla_breach(
			project_name=project.name,
			batch_name=batch_name,
			deadline=deadline,
			breach_type=breach_type,
		)
		send_email_notification.delay(
			recipient,
			f"SLA {breach_type.capitalize()} Breach: {project.name}",
			html,
		)
	except Exception as exc:  # noqa: BLE001
		logger.warning("sla_monitor: failed to queue SLA email for project %s: %s", project.id, exc)


async def _get_or_create_completion_sla(
	session: AsyncSession,
	project: ScanningProjectModel,
) -> SLAModel:
	"""
	Return the completion SLA for this project, creating a sentinel one if absent.
	The sentinel SLA represents the project-level target_end_date contract.
	"""
	stmt = select(SLAModel).where(
		SLAModel.project_id == str(project.id),
		SLAModel.sla_type == "completion",
	).limit(1)
	result = await session.execute(stmt)
	existing = result.scalar_one_or_none()
	if existing:
		return existing

	end_date = project.target_end_date or _now_utc().replace(tzinfo=None)
	start_date = project.start_date or project.created_at or end_date

	sla = SLAModel(
		id=uuid7str(),
		project_id=str(project.id),
		name="Project Completion",
		description="Auto-generated SLA tracking project target end date.",
		sla_type="completion",
		target_value=100.0,   # 100% completion
		target_unit="percent",
		threshold_warning=90.0,
		threshold_critical=100.0,
		status="on_track",
		start_date=start_date,
		end_date=end_date,
	)
	session.add(sla)
	await session.flush()  # get the ID without committing
	return sla


async def check_project_sla_breaches(session: AsyncSession) -> dict[str, int]:
	"""
	Main entry point called by deadline_monitor.

	Returns a stats dict:
	  alerts_created, projects_checked, slas_evaluated
	"""
	stats = {"projects_checked": 0, "slas_evaluated": 0, "alerts_created": 0}
	now = _strip_tz(_now_utc())

	# ── 1. Evaluate existing SLAModel records ────────────────────────────────

	sla_stmt = select(SLAModel).where(
		SLAModel.status.in_(["on_track", "at_risk"]),
		SLAModel.end_date >= now,  # not yet past end — live SLAs only
	)
	sla_result = await session.execute(sla_stmt)
	slas = sla_result.scalars().all()

	for sla in slas:
		stats["slas_evaluated"] += 1

		# Skip if no thresholds configured
		if sla.threshold_warning is None and sla.threshold_critical is None:
			continue

		current = sla.current_value
		target = sla.target_value
		if target == 0:
			continue

		# For completion/quality SLAs higher-is-better; for turnaround lower-is-better.
		if sla.sla_type in ("completion", "quality"):
			pct = (current / target) * 100.0

			if sla.threshold_critical is not None and pct <= (100.0 - sla.threshold_critical):
				alert_type = "critical"
				msg = (
					f"SLA '{sla.name}' critical breach: "
					f"current={current:.1f} vs target={target:.1f} ({pct:.1f}%)"
				)
			elif sla.threshold_warning is not None and pct <= (100.0 - sla.threshold_warning):
				alert_type = "warning"
				msg = (
					f"SLA '{sla.name}' warning: "
					f"current={current:.1f} vs target={target:.1f} ({pct:.1f}%)"
				)
			else:
				continue
		else:
			# turnaround — lower current_value is better (e.g. days remaining)
			if sla.threshold_critical is not None and current >= sla.threshold_critical:
				alert_type = "critical"
				msg = (
					f"SLA '{sla.name}' critical: "
					f"current={current:.1f} exceeds critical threshold={sla.threshold_critical}"
				)
			elif sla.threshold_warning is not None and current >= sla.threshold_warning:
				alert_type = "warning"
				msg = (
					f"SLA '{sla.name}' warning: "
					f"current={current:.1f} approaching warning threshold={sla.threshold_warning}"
				)
			else:
				continue

		if await _alert_exists(session, sla.id, alert_type):
			continue

		await _create_alert(
			session,
			sla_id=sla.id,
			alert_type=alert_type,
			message=msg,
			current_value=current,
			target_value=target,
		)
		stats["alerts_created"] += 1

		# Notify creator
		project = await session.get(ScanningProjectModel, sla.project_id)
		if project:
			await _notify_project_creator(
				session,
				project,
				title=f"SLA Alert: {sla.name}",
				message=msg,
				alert_type=alert_type,
			)
			await _email_sla_alert(
				session,
				project=project,
				batch_name=sla.name,
				deadline=sla.end_date.strftime("%Y-%m-%d %H:%M UTC") if sla.end_date else "N/A",
				breach_type=alert_type,
			)

	# ── 2. Check project-level target_end_date deadlines ────────────────────

	proj_stmt = select(ScanningProjectModel).where(
		ScanningProjectModel.target_end_date.isnot(None),
		ScanningProjectModel.status.not_in(list(_TERMINAL_STATUSES)),
		ScanningProjectModel.deleted_at.is_(None),
	)
	proj_result = await session.execute(proj_stmt)
	projects = proj_result.scalars().all()

	for project in projects:
		stats["projects_checked"] += 1

		due = _strip_tz(project.target_end_date)  # type: ignore[arg-type]
		hours_remaining = (due - now).total_seconds() / 3600.0

		if hours_remaining > DEADLINE_WARNING_HOURS:
			continue  # not yet in warning window

		completion_sla = await _get_or_create_completion_sla(session, project)

		if hours_remaining <= 0:
			# Deadline missed
			alert_type = "critical"
			msg = (
				f"Project '{project.name}' (#{project.code}) deadline missed: "
				f"was due {due.strftime('%Y-%m-%d %H:%M')} UTC."
			)
			hours_overdue = abs(hours_remaining)
			current_val = round(hours_overdue, 2)
			target_val = 0.0
		else:
			# Approaching deadline
			alert_type = "warning"
			msg = (
				f"Project '{project.name}' (#{project.code}) deadline approaching: "
				f"{hours_remaining:.1f} h remaining (due {due.strftime('%Y-%m-%d %H:%M')} UTC)."
			)
			current_val = round(hours_remaining, 2)
			target_val = float(DEADLINE_WARNING_HOURS)

		if await _alert_exists(session, completion_sla.id, alert_type):
			continue

		await _create_alert(
			session,
			sla_id=completion_sla.id,
			alert_type=alert_type,
			message=msg,
			current_value=current_val,
			target_value=target_val,
		)
		stats["alerts_created"] += 1

		await _notify_project_creator(
			session,
			project,
			title=(
				"Deadline Missed" if alert_type == "critical"
				else "Deadline Approaching"
			),
			message=msg,
			alert_type=alert_type,
		)
		await _email_sla_alert(
			session,
			project=project,
			batch_name="Project Deadline",
			deadline=due.strftime("%Y-%m-%d %H:%M UTC"),
			breach_type=alert_type,
		)

		logger.info("sla_monitor: %s alert for project %s (%s)", alert_type, project.id, project.name)

	return stats

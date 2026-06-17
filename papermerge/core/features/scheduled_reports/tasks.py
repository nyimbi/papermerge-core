# (c) Copyright Datacraft, 2026
"""Celery task: run due scheduled reports and deliver via email.

WIRING NEEDED — add to celery_app.py:

  task_routes["darchiva.reports.run_scheduled"] = {"queue": prefixed("core")}

  beat_schedule["scheduled-reports-hourly"] = {
      "task": "darchiva.reports.run_scheduled",
      "schedule": crontab(minute=0),   # top of every hour
  }
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
from datetime import datetime, timedelta, timezone

from celery import shared_task

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Report generators (produce raw bytes in the requested format)
# ---------------------------------------------------------------------------

async def _generate_report_bytes(
	report_type: str,
	fmt: str,
	filters: dict,
	tenant_id: str,
	session,
) -> bytes:
	"""Dispatch to the correct analytics query and serialise to csv/xlsx."""
	rows, headers = await _fetch_report_data(report_type, filters, tenant_id, session)
	if fmt == "xlsx":
		return _to_xlsx(headers, rows)
	return _to_csv(headers, rows)


async def _fetch_report_data(
	report_type: str,
	filters: dict,
	tenant_id: str,
	session,
) -> tuple[list[list], list[str]]:
	"""Return (rows, headers) for the given report_type."""
	from sqlalchemy import func, select, text

	now = datetime.now(tz=timezone.utc)
	days = int(filters.get("days", 30))
	window_start = now - timedelta(days=days)

	if report_type == "document_summary":
		return await _report_document_summary(tenant_id, window_start, session)
	elif report_type == "ocr_quality":
		return await _report_ocr_quality(tenant_id, window_start, session)
	elif report_type == "scanning_productivity":
		return await _report_scanning_productivity(tenant_id, window_start, session)
	elif report_type == "expiry_upcoming":
		horizon_days = int(filters.get("horizon_days", 30))
		return await _report_expiry_upcoming(tenant_id, horizon_days, session)
	else:
		_log.warning("scheduled_reports: unknown report_type=%s", report_type)
		return [], ["note"]


async def _report_document_summary(tenant_id: str, window_start: datetime, session) -> tuple[list, list]:
	from sqlalchemy import func, select
	try:
		from papermerge.core.features.document.db.orm import Document
		rows = await session.execute(
			select(
				func.date_trunc("day", Document.created_at).label("day"),
				func.count(Document.id).label("documents_added"),
			)
			.where(
				Document.basetreenode.has(tenant_id=tenant_id),  # type: ignore[attr-defined]
				Document.created_at >= window_start,
			)
			.group_by("day")
			.order_by("day")
		)
		data = rows.fetchall()
		headers = ["day", "documents_added"]
		return [[str(r.day)[:10], r.documents_added] for r in data], headers
	except Exception as exc:
		_log.warning("document_summary query failed: %s", exc)
		return [], ["day", "documents_added"]


async def _report_ocr_quality(tenant_id: str, window_start: datetime, session) -> tuple[list, list]:
	from sqlalchemy import func, select
	try:
		from papermerge.core.features.scanning_projects.models import PageScanEventModel
		rows = await session.execute(
			select(
				func.date_trunc("day", PageScanEventModel.occurred_at).label("day"),
				func.count(PageScanEventModel.id).label("pages"),
				func.avg(PageScanEventModel.quality_score).label("avg_quality"),
				func.min(PageScanEventModel.quality_score).label("min_quality"),
			)
			.where(
				PageScanEventModel.tenant_id == tenant_id,
				PageScanEventModel.occurred_at >= window_start,
			)
			.group_by("day")
			.order_by("day")
		)
		data = rows.fetchall()
		headers = ["day", "pages", "avg_quality", "min_quality"]
		return [
			[str(r.day)[:10], r.pages, round(float(r.avg_quality or 0), 2), round(float(r.min_quality or 0), 2)]
			for r in data
		], headers
	except Exception as exc:
		_log.warning("ocr_quality query failed: %s", exc)
		return [], ["day", "pages", "avg_quality", "min_quality"]


async def _report_scanning_productivity(tenant_id: str, window_start: datetime, session) -> tuple[list, list]:
	from sqlalchemy import func, select
	try:
		from papermerge.core.features.scanning_projects.models import (
			PageScanEventModel,
			ScanningSesssionModel,
		)
		rows = await session.execute(
			select(
				ScanningSesssionModel.operator_id.label("operator_id"),
				func.count(PageScanEventModel.id).label("pages_scanned"),
				func.count(ScanningSesssionModel.id.distinct()).label("sessions"),
			)
			.join(
				PageScanEventModel,
				PageScanEventModel.session_id == ScanningSesssionModel.id,
				isouter=True,
			)
			.where(
				ScanningSesssionModel.tenant_id == tenant_id,
				ScanningSesssionModel.started_at >= window_start,
			)
			.group_by(ScanningSesssionModel.operator_id)
			.order_by(func.count(PageScanEventModel.id).desc())
		)
		data = rows.fetchall()
		headers = ["operator_id", "pages_scanned", "sessions"]
		return [[str(r.operator_id), r.pages_scanned, r.sessions] for r in data], headers
	except Exception as exc:
		_log.warning("scanning_productivity query failed: %s", exc)
		return [], ["operator_id", "pages_scanned", "sessions"]


async def _report_expiry_upcoming(tenant_id: str, horizon_days: int, session) -> tuple[list, list]:
	from sqlalchemy import select
	try:
		from papermerge.core.features.expiry.db.orm import DocumentExpiry
		horizon = datetime.now(tz=timezone.utc) + timedelta(days=horizon_days)
		rows = await session.execute(
			select(
				DocumentExpiry.document_id,
				DocumentExpiry.expiry_date,
				DocumentExpiry.policy,
			)
			.where(
				DocumentExpiry.tenant_id == tenant_id,
				DocumentExpiry.expiry_date <= horizon,
				DocumentExpiry.is_active.is_(True),
			)
			.order_by(DocumentExpiry.expiry_date)
		)
		data = rows.fetchall()
		headers = ["document_id", "expiry_date", "policy"]
		return [[str(r.document_id), str(r.expiry_date)[:10], r.policy] for r in data], headers
	except Exception as exc:
		_log.warning("expiry_upcoming query failed: %s", exc)
		return [], ["document_id", "expiry_date", "policy"]


def _to_csv(headers: list[str], rows: list[list]) -> bytes:
	buf = io.StringIO()
	writer = csv.writer(buf)
	writer.writerow(headers)
	writer.writerows(rows)
	return buf.getvalue().encode("utf-8")


def _to_xlsx(headers: list[str], rows: list[list]) -> bytes:
	try:
		import openpyxl
	except ImportError:
		_log.warning("openpyxl not installed; falling back to CSV bytes")
		return _to_csv(headers, rows)

	wb = openpyxl.Workbook()
	ws = wb.active
	ws.append(headers)
	for row in rows:
		ws.append(row)
	buf = io.BytesIO()
	wb.save(buf)
	return buf.getvalue()


# ---------------------------------------------------------------------------
# Due-report logic
# ---------------------------------------------------------------------------

def _is_due(report, now: datetime) -> bool:
	"""Return True if a ScheduledReport should fire at *now* (UTC, hour-granular)."""
	if not report.is_active:
		return False

	current_hour = now.hour

	if report.delivery_hour != current_hour:
		return False

	schedule = report.schedule
	last = report.last_sent_at

	if schedule == "daily":
		if last is None:
			return True
		# Sent already today?
		return last.date() < now.date()

	elif schedule == "weekly":
		dow = report.day_of_week if report.day_of_week is not None else 0
		if now.weekday() != dow:
			return False
		if last is None:
			return True
		return (now - last).days >= 7

	elif schedule == "monthly":
		day_of_month = 1  # send on the 1st
		if now.day != day_of_month:
			return False
		if last is None:
			return True
		return last.month != now.month or last.year != now.year

	return False


def _filename(report_name: str, fmt: str) -> str:
	safe = report_name.lower().replace(" ", "_")[:40]
	ext = "xlsx" if fmt == "xlsx" else "csv"
	stamp = datetime.utcnow().strftime("%Y%m%d")
	return f"darchiva_{safe}_{stamp}.{ext}"


# ---------------------------------------------------------------------------
# Async runner
# ---------------------------------------------------------------------------

async def _run_due_reports() -> dict:
	from sqlalchemy import select

	from papermerge.core.db.engine import get_async_session_maker
	from papermerge.core.features.scheduled_reports.db.orm import ScheduledReport
	from papermerge.core.features.scheduled_reports.email_service import send_report_email

	now = datetime.now(tz=timezone.utc)
	async_session = get_async_session_maker()

	sent_total = 0
	failed_total = 0

	async with async_session() as session:
		result = await session.execute(
			select(ScheduledReport).where(ScheduledReport.is_active.is_(True))
		)
		reports = result.scalars().all()

	for report in reports:
		if not _is_due(report, now):
			continue

		_log.info(
			"scheduled_reports: firing report '%s' (id=%s, type=%s)",
			report.name, report.id, report.report_type,
		)

		try:
			filters = json.loads(report.filters or "{}")
			recipients = [r.strip() for r in report.recipients.split(",") if r.strip()]
			if not recipients:
				_log.warning("scheduled_reports: no recipients for report %s", report.id)
				continue

			async with async_session() as session:
				file_bytes = await _generate_report_bytes(
					report.report_type,
					report.format,
					filters,
					str(report.tenant_id),
					session,
				)

			fname = _filename(report.name, report.format)
			await send_report_email(
				recipients=recipients,
				report_name=report.name,
				file_bytes=file_bytes,
				filename=fname,
				report_type=report.report_type,
			)

			# Update last_sent_at + send_count
			async with async_session() as session:
				obj = await session.get(ScheduledReport, report.id)
				if obj:
					obj.last_sent_at = now
					obj.send_count = (obj.send_count or 0) + 1
					await session.commit()

			sent_total += 1

		except Exception as exc:
			_log.error(
				"scheduled_reports: error processing report %s: %s",
				report.id, exc,
				exc_info=True,
			)
			failed_total += 1

	return {"sent": sent_total, "failed": failed_total}


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------

@shared_task(
	bind=True,
	max_retries=2,
	default_retry_delay=300,
	name="darchiva.reports.run_scheduled",
)
def run_scheduled_reports(self) -> dict:
	"""
	Hourly task: identify due ScheduledReport rows, generate the requested
	analytics export, and deliver it to the configured recipients.
	"""
	_log.info("scheduled_reports: task started")
	loop = asyncio.new_event_loop()
	try:
		result = loop.run_until_complete(_run_due_reports())
		_log.info(
			"scheduled_reports: complete — sent=%d failed=%d",
			result["sent"], result["failed"],
		)
		return result
	finally:
		loop.close()

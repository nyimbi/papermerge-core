# (c) Copyright Datacraft, 2026
"""Weekly KPI report: data aggregation + HTML rendering."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, case
from sqlalchemy.ext.asyncio import AsyncSession

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data aggregation
# ---------------------------------------------------------------------------

async def generate_weekly_kpi_report(tenant_id: str, session: AsyncSession) -> dict:
	"""
	Aggregate KPI data for *tenant_id* covering the last 7 calendar days.

	Returns a structured dict with keys:
	  tenant_id, period_start, period_end,
	  pages_total, avg_quality_score,
	  operators (list of {operator_id, operator_name, pages, avg_quality}),
	  batches_total, batches_completed, on_time_rate,
	  exceptions_total, exceptions_resolved, exceptions_open
	"""
	now = datetime.now(tz=timezone.utc)
	period_end = now
	period_start = now - timedelta(days=7)

	# -- import models lazily to avoid circular imports at module level ------
	from papermerge.core.features.scanning_projects.models import (
		PageScanEventModel,
		ScanningBatchModel,
		ScanningProjectModel,
	)
	from papermerge.core.features.exceptions.db.orm import ExceptionEvent

	# -----------------------------------------------------------------------
	# 1. Page scan events — total pages + avg quality in window
	# -----------------------------------------------------------------------
	page_agg = await session.execute(
		select(
			func.count(PageScanEventModel.id).label("total_pages"),
			func.avg(PageScanEventModel.quality_score).label("avg_quality"),
		).where(
			PageScanEventModel.tenant_id == tenant_id,
			PageScanEventModel.occurred_at >= period_start,
			PageScanEventModel.occurred_at < period_end,
			PageScanEventModel.event_type == "scanned",
		)
	)
	page_row = page_agg.one()
	pages_total: int = int(page_row.total_pages or 0)
	avg_quality_score: float = float(page_row.avg_quality or 0.0)

	# -----------------------------------------------------------------------
	# 2. Pages + quality per operator
	# -----------------------------------------------------------------------
	op_rows = await session.execute(
		select(
			PageScanEventModel.operator_id,
			func.count(PageScanEventModel.id).label("pages"),
			func.avg(PageScanEventModel.quality_score).label("avg_quality"),
		).where(
			PageScanEventModel.tenant_id == tenant_id,
			PageScanEventModel.occurred_at >= period_start,
			PageScanEventModel.occurred_at < period_end,
			PageScanEventModel.event_type == "scanned",
			PageScanEventModel.operator_id.isnot(None),
		).group_by(PageScanEventModel.operator_id)
		.order_by(func.count(PageScanEventModel.id).desc())
	)

	# Enrich with operator names via a users join
	from papermerge.core.features.users.db.orm import User
	operator_rows = op_rows.all()
	operator_ids = [r.operator_id for r in operator_rows]

	name_map: dict[str, str] = {}
	if operator_ids:
		name_rows = await session.execute(
			select(User.id, User.username).where(User.id.in_(operator_ids))
		)
		name_map = {str(r.id): r.username for r in name_rows.all()}

	operators = [
		{
			"operator_id": r.operator_id,
			"operator_name": name_map.get(r.operator_id, r.operator_id),
			"pages": int(r.pages),
			"avg_quality": round(float(r.avg_quality or 0.0), 1),
		}
		for r in operator_rows
	]

	# -----------------------------------------------------------------------
	# 3. Batches — total, completed, on-time rate
	#    on_time = completed_at <= due date; we use ScanningBatchModel which
	#    has no explicit due_date, so on_time = completed within window.
	# -----------------------------------------------------------------------
	batch_agg = await session.execute(
		select(
			func.count(ScanningBatchModel.id).label("total"),
			func.count(
				case(
					(ScanningBatchModel.status == "completed", 1),
					else_=None,
				)
			).label("completed"),
			func.count(
				case(
					(
						(ScanningBatchModel.status == "completed") &
						(ScanningBatchModel.completed_at >= period_start) &
						(ScanningBatchModel.completed_at < period_end),
						1,
					),
					else_=None,
				)
			).label("on_time"),
		).join(
			ScanningProjectModel,
			ScanningBatchModel.project_id == ScanningProjectModel.id,
		).where(
			ScanningProjectModel.tenant_id == tenant_id,
			ScanningBatchModel.created_at >= period_start,
			ScanningBatchModel.created_at < period_end,
		)
	)
	batch_row = batch_agg.one()
	batches_total = int(batch_row.total or 0)
	batches_completed = int(batch_row.completed or 0)
	on_time_count = int(batch_row.on_time or 0)
	on_time_rate: float = (
		round(on_time_count / batches_total * 100, 1) if batches_total else 0.0
	)

	# -----------------------------------------------------------------------
	# 4. Exception events
	# -----------------------------------------------------------------------
	exc_agg = await session.execute(
		select(
			func.count(ExceptionEvent.id).label("total"),
			func.count(
				case((ExceptionEvent.status == "resolved", 1), else_=None)
			).label("resolved"),
			func.count(
				case((ExceptionEvent.status.in_(["open", "pending"]), 1), else_=None)
			).label("open"),
		).where(
			ExceptionEvent.tenant_id == tenant_id,
			ExceptionEvent.created_at >= period_start,
			ExceptionEvent.created_at < period_end,
		)
	)
	exc_row = exc_agg.one()

	return {
		"tenant_id": tenant_id,
		"period_start": period_start.strftime("%Y-%m-%d"),
		"period_end": period_end.strftime("%Y-%m-%d"),
		"pages_total": pages_total,
		"avg_quality_score": round(avg_quality_score, 1),
		"operators": operators,
		"batches_total": batches_total,
		"batches_completed": batches_completed,
		"on_time_rate": on_time_rate,
		"exceptions_total": int(exc_row.total or 0),
		"exceptions_resolved": int(exc_row.resolved or 0),
		"exceptions_open": int(exc_row.open or 0),
	}


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

def render_weekly_kpi_html(report_data: dict, recipient_name: str) -> str:
	"""
	Return a dark-themed HTML email for the weekly KPI report.

	Uses the same base style palette as email_notifications/service.py.
	"""
	d = report_data
	period = f"{d['period_start']} — {d['period_end']}"

	# Quality badge colour
	aq = d["avg_quality_score"]
	q_cls = "badge-green" if aq >= 90 else ("badge-amber" if aq >= 70 else "badge-red")

	# On-time rate badge
	otr = d["on_time_rate"]
	otr_cls = "badge-green" if otr >= 95 else ("badge-amber" if otr >= 80 else "badge-red")

	# Top operators table rows (cap at 10)
	op_rows_html = ""
	for op in d["operators"][:10]:
		oq = op["avg_quality"]
		op_q_cls = "badge-green" if oq >= 90 else ("badge-amber" if oq >= 70 else "badge-red")
		op_rows_html += (
			f'<tr>'
			f'<td>{op["operator_name"]}</td>'
			f'<td style="text-align:right">{op["pages"]:,}</td>'
			f'<td><span class="badge {op_q_cls}">{oq:.1f}%</span></td>'
			f'</tr>'
		)
	if not op_rows_html:
		op_rows_html = '<tr><td colspan="3" style="color:#64748b">No activity recorded</td></tr>'

	exc_open = d["exceptions_open"]
	exc_cls = "badge-red" if exc_open > 0 else "badge-green"

	style = """
		body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
		       background: #0f172a; color: #e2e8f0; margin: 0; padding: 0; }
		.wrapper { max-width: 620px; margin: 32px auto; background: #1e293b;
		           border-radius: 8px; overflow: hidden; }
		.header  { padding: 24px 32px; background: #1e3a5f; }
		.section { padding: 20px 32px; border-bottom: 1px solid #334155; }
		.footer  { padding: 16px 32px; font-size: 12px; color: #64748b; }
		h1 { margin: 0; font-size: 20px; color: #60a5fa; }
		h2 { margin: 0 0 12px; font-size: 14px; color: #94a3b8;
		     text-transform: uppercase; letter-spacing: 0.05em; }
		table { border-collapse: collapse; width: 100%; }
		th, td { text-align: left; padding: 8px 12px; border-bottom: 1px solid #334155; }
		th { background: #0f172a; color: #94a3b8; font-size: 12px; text-transform: uppercase; }
		.stat-grid { display: grid; grid-template-columns: repeat(3,1fr); gap: 12px; }
		.stat-box  { background: #0f172a; border-radius: 6px; padding: 12px 16px; }
		.stat-val  { font-size: 24px; font-weight: 700; color: #f1f5f9; }
		.stat-lbl  { font-size: 11px; color: #64748b; margin-top: 2px; }
		.badge { display: inline-block; padding: 2px 10px; border-radius: 9999px;
		         font-size: 12px; font-weight: 600; }
		.badge-amber { background: #78350f; color: #fcd34d; }
		.badge-red   { background: #7f1d1d; color: #fca5a5; }
		.badge-green { background: #14532d; color: #86efac; }
	"""

	return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><style>{style}</style></head>
<body>
<div class="wrapper">
  <!-- Header -->
  <div class="header">
    <h1>Weekly KPI Report</h1>
    <p style="margin:4px 0 0;color:#93c5fd;font-size:13px;">
      Hello <strong>{recipient_name}</strong> &mdash; period {period}
    </p>
  </div>

  <!-- Summary stats -->
  <div class="section">
    <h2>Summary</h2>
    <div class="stat-grid">
      <div class="stat-box">
        <div class="stat-val">{d['pages_total']:,}</div>
        <div class="stat-lbl">Pages Scanned</div>
      </div>
      <div class="stat-box">
        <div class="stat-val">
          <span class="badge {q_cls}">{d['avg_quality_score']:.1f}%</span>
        </div>
        <div class="stat-lbl">Avg Quality</div>
      </div>
      <div class="stat-box">
        <div class="stat-val">
          <span class="badge {otr_cls}">{d['on_time_rate']:.1f}%</span>
        </div>
        <div class="stat-lbl">On-Time Batches</div>
      </div>
    </div>
  </div>

  <!-- Batch stats -->
  <div class="section">
    <h2>Batches</h2>
    <table>
      <tr><th>Metric</th><th>Value</th></tr>
      <tr><td>Total batches</td><td>{d['batches_total']}</td></tr>
      <tr><td>Completed</td><td>{d['batches_completed']}</td></tr>
      <tr>
        <td>On-time rate</td>
        <td><span class="badge {otr_cls}">{d['on_time_rate']:.1f}%</span></td>
      </tr>
    </table>
  </div>

  <!-- Top operators -->
  <div class="section">
    <h2>Top Operators</h2>
    <table>
      <tr><th>Operator</th><th style="text-align:right">Pages</th><th>Avg Quality</th></tr>
      {op_rows_html}
    </table>
  </div>

  <!-- Exceptions -->
  <div class="section">
    <h2>Exceptions</h2>
    <table>
      <tr><th>Metric</th><th>Value</th></tr>
      <tr><td>Total raised</td><td>{d['exceptions_total']}</td></tr>
      <tr><td>Resolved</td>
          <td><span class="badge badge-green">{d['exceptions_resolved']}</span></td></tr>
      <tr><td>Still open</td>
          <td><span class="badge {exc_cls}">{exc_open}</span></td></tr>
    </table>
  </div>

  <div class="footer">
    dArchiva &mdash; Document Management System &mdash;
    This report was generated automatically. Do not reply to this email.
  </div>
</div>
</body></html>"""

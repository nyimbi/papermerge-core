# (c) Copyright Datacraft, 2026
"""
Report generation for scanning projects.

Generates PDF and HTML reports for:
- Daily progress reports
- Weekly summaries
- Operator performance reports
- Quality metrics reports
- Project completion reports
"""
import logging
from datetime import datetime, timedelta, date
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
	ScanningProjectModel,
	ScanningBatchModel,
	ScanningMilestoneModel,
	QualityControlSampleModel,
	ScanningSesssionModel,
	DailyProjectMetricsModel,
	OperatorDailyMetricsModel,
	ProjectIssueModel,
)
from .views import (
	ScanningBatchStatus,
	QCReviewStatus,
	MilestoneStatus,
)

logger = logging.getLogger(__name__)


def _log_report(report_type: str, project_id: str) -> str:
	return f"Generating {report_type} report for project {project_id[:8]}..."


@dataclass
class ReportData:
	"""Container for report data."""
	project_id: str
	project_name: str
	report_type: str
	report_date: datetime
	period_start: datetime | None = None
	period_end: datetime | None = None

	# Summary metrics
	total_pages_target: int = 0
	total_pages_scanned: int = 0
	pages_verified: int = 0
	pages_rejected: int = 0
	completion_percentage: float = 0.0

	# Period metrics
	period_pages_scanned: int = 0
	period_pages_verified: int = 0
	period_pages_rejected: int = 0
	period_sessions: int = 0
	period_hours: float = 0.0
	average_pages_per_hour: float = 0.0

	# Quality metrics
	qc_pass_rate: float = 0.0
	average_quality_score: float = 0.0
	critical_issues: int = 0

	# Batch breakdown
	batches_pending: int = 0
	batches_in_progress: int = 0
	batches_completed: int = 0

	# Operator performance
	operator_metrics: list[dict] = field(default_factory=list)

	# Issues
	open_issues: list[dict] = field(default_factory=list)

	# Milestones
	milestones: list[dict] = field(default_factory=list)

	# Daily breakdown
	daily_breakdown: list[dict] = field(default_factory=list)

	# AI insights (if available)
	ai_summary: str = ""
	ai_recommendations: list[str] = field(default_factory=list)


class ReportGenerator:
	"""Generates various reports for scanning projects."""

	async def generate_daily_report(
		self,
		session: AsyncSession,
		project_id: str,
		report_date: date | None = None,
	) -> ReportData:
		"""Generate a daily progress report."""
		report_date = report_date or date.today()
		logger.info(_log_report("daily", project_id))

		# Get project
		project = await self._get_project(session, project_id)

		report = ReportData(
			project_id=project_id,
			project_name=project.name,
			report_type="daily",
			report_date=datetime.combine(report_date, datetime.min.time()),
			period_start=datetime.combine(report_date, datetime.min.time()),
			period_end=datetime.combine(report_date, datetime.max.time()),
			total_pages_target=project.total_estimated_pages,
			total_pages_scanned=project.scanned_pages,
			pages_verified=project.verified_pages,
			pages_rejected=project.rejected_pages,
		)

		if project.total_estimated_pages > 0:
			report.completion_percentage = (
				project.scanned_pages / project.total_estimated_pages * 100
			)

		# Get day's metrics
		await self._populate_period_metrics(session, report, project_id, report_date, report_date)
		await self._populate_batch_counts(session, report, project_id)
		await self._populate_operator_metrics(session, report, project_id, report_date, report_date)
		await self._populate_issues(session, report, project_id)
		await self._populate_milestones(session, report, project_id)

		return report

	async def generate_weekly_report(
		self,
		session: AsyncSession,
		project_id: str,
		week_ending: date | None = None,
	) -> ReportData:
		"""Generate a weekly summary report."""
		week_ending = week_ending or date.today()
		week_starting = week_ending - timedelta(days=6)
		logger.info(_log_report("weekly", project_id))

		project = await self._get_project(session, project_id)

		report = ReportData(
			project_id=project_id,
			project_name=project.name,
			report_type="weekly",
			report_date=datetime.combine(week_ending, datetime.min.time()),
			period_start=datetime.combine(week_starting, datetime.min.time()),
			period_end=datetime.combine(week_ending, datetime.max.time()),
			total_pages_target=project.total_estimated_pages,
			total_pages_scanned=project.scanned_pages,
			pages_verified=project.verified_pages,
			pages_rejected=project.rejected_pages,
		)

		if project.total_estimated_pages > 0:
			report.completion_percentage = (
				project.scanned_pages / project.total_estimated_pages * 100
			)

		await self._populate_period_metrics(session, report, project_id, week_starting, week_ending)
		await self._populate_batch_counts(session, report, project_id)
		await self._populate_operator_metrics(session, report, project_id, week_starting, week_ending)
		await self._populate_issues(session, report, project_id)
		await self._populate_milestones(session, report, project_id)
		await self._populate_daily_breakdown(session, report, project_id, week_starting, week_ending)

		return report

	async def generate_operator_report(
		self,
		session: AsyncSession,
		project_id: str,
		operator_id: str,
		start_date: date,
		end_date: date,
	) -> ReportData:
		"""Generate an operator performance report."""
		logger.info(_log_report("operator", project_id))

		project = await self._get_project(session, project_id)

		report = ReportData(
			project_id=project_id,
			project_name=project.name,
			report_type="operator",
			report_date=datetime.utcnow(),
			period_start=datetime.combine(start_date, datetime.min.time()),
			period_end=datetime.combine(end_date, datetime.max.time()),
		)

		# Get operator metrics
		stmt = select(OperatorDailyMetricsModel).where(
			and_(
				OperatorDailyMetricsModel.project_id == project_id,
				OperatorDailyMetricsModel.operator_id == operator_id,
				OperatorDailyMetricsModel.metric_date >= datetime.combine(start_date, datetime.min.time()),
				OperatorDailyMetricsModel.metric_date <= datetime.combine(end_date, datetime.max.time()),
			)
		).order_by(OperatorDailyMetricsModel.metric_date)
		result = await session.execute(stmt)
		metrics = result.scalars().all()

		total_pages = 0
		total_hours = 0.0
		total_quality = 0.0
		quality_count = 0

		for m in metrics:
			total_pages += m.pages_scanned
			total_hours += m.session_hours
			if m.quality_score:
				total_quality += m.quality_score
				quality_count += 1
			report.daily_breakdown.append({
				"date": m.metric_date.isoformat(),
				"pages_scanned": m.pages_scanned,
				"session_hours": m.session_hours,
				"pages_per_hour": m.pages_per_hour,
				"quality_score": m.quality_score,
			})

		report.period_pages_scanned = total_pages
		report.period_hours = total_hours
		if total_hours > 0:
			report.average_pages_per_hour = total_pages / total_hours
		if quality_count > 0:
			report.average_quality_score = total_quality / quality_count

		return report

	async def _get_project(
		self,
		session: AsyncSession,
		project_id: str,
	) -> ScanningProjectModel:
		"""Get project or raise error."""
		stmt = select(ScanningProjectModel).where(
			ScanningProjectModel.id == project_id
		)
		result = await session.execute(stmt)
		project = result.scalar_one_or_none()
		if not project:
			raise ValueError(f"Project not found: {project_id}")
		return project

	async def _populate_period_metrics(
		self,
		session: AsyncSession,
		report: ReportData,
		project_id: str,
		start_date: date,
		end_date: date,
	) -> None:
		"""Populate period metrics from daily metrics."""
		stmt = select(DailyProjectMetricsModel).where(
			and_(
				DailyProjectMetricsModel.project_id == project_id,
				DailyProjectMetricsModel.metric_date >= datetime.combine(start_date, datetime.min.time()),
				DailyProjectMetricsModel.metric_date <= datetime.combine(end_date, datetime.max.time()),
			)
		)
		result = await session.execute(stmt)
		metrics = result.scalars().all()

		for m in metrics:
			report.period_pages_scanned += m.pages_scanned
			report.period_pages_verified += m.pages_verified
			report.period_pages_rejected += m.pages_rejected
			report.period_hours += m.total_session_hours
			report.critical_issues += m.issues_found

		if report.period_hours > 0:
			report.average_pages_per_hour = report.period_pages_scanned / report.period_hours

	async def _populate_batch_counts(
		self,
		session: AsyncSession,
		report: ReportData,
		project_id: str,
	) -> None:
		"""Populate batch status counts."""
		stmt = select(
			ScanningBatchModel.status,
			func.count().label("count"),
		).where(
			ScanningBatchModel.project_id == project_id
		).group_by(ScanningBatchModel.status)
		result = await session.execute(stmt)

		for row in result.fetchall():
			status, count = row
			if status == ScanningBatchStatus.PENDING:
				report.batches_pending = count
			elif status == ScanningBatchStatus.COMPLETED:
				report.batches_completed = count
			else:
				report.batches_in_progress += count

	async def _populate_operator_metrics(
		self,
		session: AsyncSession,
		report: ReportData,
		project_id: str,
		start_date: date,
		end_date: date,
	) -> None:
		"""Populate operator performance metrics."""
		stmt = select(
			OperatorDailyMetricsModel.operator_id,
			OperatorDailyMetricsModel.operator_name,
			func.sum(OperatorDailyMetricsModel.pages_scanned).label("total_pages"),
			func.sum(OperatorDailyMetricsModel.session_hours).label("total_hours"),
			func.avg(OperatorDailyMetricsModel.quality_score).label("avg_quality"),
		).where(
			and_(
				OperatorDailyMetricsModel.project_id == project_id,
				OperatorDailyMetricsModel.metric_date >= datetime.combine(start_date, datetime.min.time()),
				OperatorDailyMetricsModel.metric_date <= datetime.combine(end_date, datetime.max.time()),
			)
		).group_by(
			OperatorDailyMetricsModel.operator_id,
			OperatorDailyMetricsModel.operator_name,
		)
		result = await session.execute(stmt)

		for row in result.fetchall():
			total_pages = row.total_pages or 0
			total_hours = row.total_hours or 0
			report.operator_metrics.append({
				"operator_id": row.operator_id,
				"operator_name": row.operator_name,
				"total_pages": total_pages,
				"total_hours": round(total_hours, 1),
				"pages_per_hour": round(total_pages / total_hours, 1) if total_hours > 0 else 0,
				"avg_quality": round(row.avg_quality, 1) if row.avg_quality else None,
			})

	async def _populate_issues(
		self,
		session: AsyncSession,
		report: ReportData,
		project_id: str,
	) -> None:
		"""Populate open issues."""
		stmt = select(ProjectIssueModel).where(
			and_(
				ProjectIssueModel.project_id == project_id,
				ProjectIssueModel.status.in_(["open", "in_progress"]),
			)
		).order_by(ProjectIssueModel.created_at.desc()).limit(10)
		result = await session.execute(stmt)

		for issue in result.scalars().all():
			report.open_issues.append({
				"id": issue.id,
				"title": issue.title,
				"type": issue.issue_type,
				"severity": issue.severity,
				"status": issue.status,
				"created_at": issue.created_at.isoformat(),
			})

	async def _populate_milestones(
		self,
		session: AsyncSession,
		report: ReportData,
		project_id: str,
	) -> None:
		"""Populate milestone status."""
		stmt = select(ScanningMilestoneModel).where(
			ScanningMilestoneModel.project_id == project_id
		).order_by(ScanningMilestoneModel.target_date)
		result = await session.execute(stmt)

		for m in result.scalars().all():
			progress = 0.0
			if m.target_pages > 0:
				progress = m.actual_pages / m.target_pages * 100

			report.milestones.append({
				"name": m.name,
				"target_date": m.target_date.isoformat() if m.target_date else None,
				"target_pages": m.target_pages,
				"actual_pages": m.actual_pages,
				"progress": round(progress, 1),
				"status": m.status.value,
			})

	async def _populate_daily_breakdown(
		self,
		session: AsyncSession,
		report: ReportData,
		project_id: str,
		start_date: date,
		end_date: date,
	) -> None:
		"""Populate daily breakdown for weekly reports."""
		stmt = select(DailyProjectMetricsModel).where(
			and_(
				DailyProjectMetricsModel.project_id == project_id,
				DailyProjectMetricsModel.metric_date >= datetime.combine(start_date, datetime.min.time()),
				DailyProjectMetricsModel.metric_date <= datetime.combine(end_date, datetime.max.time()),
			)
		).order_by(DailyProjectMetricsModel.metric_date)
		result = await session.execute(stmt)

		for m in result.scalars().all():
			report.daily_breakdown.append({
				"date": m.metric_date.date().isoformat(),
				"pages_scanned": m.pages_scanned,
				"pages_verified": m.pages_verified,
				"pages_rejected": m.pages_rejected,
				"operator_count": m.operator_count,
				"session_hours": m.total_session_hours,
				"issues_found": m.issues_found,
				"issues_resolved": m.issues_resolved,
			})


def render_report_html(report: ReportData) -> str:
	"""Render report data as HTML."""
	html = f"""
<!DOCTYPE html>
<html>
<head>
	<meta charset="UTF-8">
	<title>{report.project_name} - {report.report_type.title()} Report</title>
	<style>
		body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 40px; color: #333; }}
		h1 {{ color: #2563eb; margin-bottom: 5px; }}
		h2 {{ color: #1e40af; margin-top: 30px; }}
		.subtitle {{ color: #6b7280; margin-bottom: 30px; }}
		.metrics {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; margin: 20px 0; }}
		.metric {{ background: #f3f4f6; padding: 20px; border-radius: 8px; text-align: center; }}
		.metric-value {{ font-size: 32px; font-weight: bold; color: #1e40af; }}
		.metric-label {{ color: #6b7280; margin-top: 5px; }}
		table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
		th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #e5e7eb; }}
		th {{ background: #f3f4f6; font-weight: 600; }}
		.progress-bar {{ background: #e5e7eb; border-radius: 4px; height: 8px; }}
		.progress-fill {{ background: #2563eb; height: 100%; border-radius: 4px; }}
		.status-open {{ color: #dc2626; }}
		.status-completed {{ color: #16a34a; }}
		.status-pending {{ color: #ca8a04; }}
	</style>
</head>
<body>
	<h1>{report.project_name}</h1>
	<div class="subtitle">{report.report_type.title()} Report - {report.report_date.strftime('%B %d, %Y')}</div>

	<h2>Progress Summary</h2>
	<div class="metrics">
		<div class="metric">
			<div class="metric-value">{report.completion_percentage:.1f}%</div>
			<div class="metric-label">Completion</div>
		</div>
		<div class="metric">
			<div class="metric-value">{report.total_pages_scanned:,}</div>
			<div class="metric-label">Total Pages Scanned</div>
		</div>
		<div class="metric">
			<div class="metric-value">{report.period_pages_scanned:,}</div>
			<div class="metric-label">Pages This Period</div>
		</div>
		<div class="metric">
			<div class="metric-value">{report.average_pages_per_hour:.0f}</div>
			<div class="metric-label">Avg Pages/Hour</div>
		</div>
	</div>

	<h2>Batch Status</h2>
	<div class="metrics">
		<div class="metric">
			<div class="metric-value">{report.batches_pending}</div>
			<div class="metric-label">Pending</div>
		</div>
		<div class="metric">
			<div class="metric-value">{report.batches_in_progress}</div>
			<div class="metric-label">In Progress</div>
		</div>
		<div class="metric">
			<div class="metric-value">{report.batches_completed}</div>
			<div class="metric-label">Completed</div>
		</div>
	</div>
"""

	if report.operator_metrics:
		html += """
	<h2>Operator Performance</h2>
	<table>
		<tr>
			<th>Operator</th>
			<th>Pages Scanned</th>
			<th>Hours</th>
			<th>Pages/Hour</th>
			<th>Quality Score</th>
		</tr>
"""
		for op in report.operator_metrics:
			quality = f"{op['avg_quality']:.1f}" if op['avg_quality'] else "N/A"
			html += f"""
		<tr>
			<td>{op['operator_name'] or op['operator_id'][:8]}</td>
			<td>{op['total_pages']:,}</td>
			<td>{op['total_hours']:.1f}</td>
			<td>{op['pages_per_hour']:.0f}</td>
			<td>{quality}</td>
		</tr>
"""
		html += "</table>"

	if report.milestones:
		html += """
	<h2>Milestones</h2>
	<table>
		<tr>
			<th>Milestone</th>
			<th>Target Date</th>
			<th>Progress</th>
			<th>Status</th>
		</tr>
"""
		for m in report.milestones:
			status_class = f"status-{m['status']}"
			html += f"""
		<tr>
			<td>{m['name']}</td>
			<td>{m['target_date'][:10] if m['target_date'] else 'N/A'}</td>
			<td>
				<div class="progress-bar">
					<div class="progress-fill" style="width: {min(100, m['progress'])}%"></div>
				</div>
				{m['progress']:.1f}%
			</td>
			<td class="{status_class}">{m['status'].title()}</td>
		</tr>
"""
		html += "</table>"

	if report.open_issues:
		html += """
	<h2>Open Issues</h2>
	<table>
		<tr>
			<th>Title</th>
			<th>Type</th>
			<th>Severity</th>
			<th>Status</th>
		</tr>
"""
		for issue in report.open_issues:
			html += f"""
		<tr>
			<td>{issue['title']}</td>
			<td>{issue['type']}</td>
			<td>{issue['severity']}</td>
			<td>{issue['status']}</td>
		</tr>
"""
		html += "</table>"

	if report.ai_summary:
		html += f"""
	<h2>AI Insights</h2>
	<p>{report.ai_summary}</p>
"""
		if report.ai_recommendations:
			html += "<h3>Recommendations</h3><ul>"
			for rec in report.ai_recommendations:
				html += f"<li>{rec}</li>"
			html += "</ul>"

	html += """
	<div style="margin-top: 50px; padding-top: 20px; border-top: 1px solid #e5e7eb; color: #6b7280; font-size: 12px;">
		Generated by dArchiva Document Management System
	</div>
</body>
</html>
"""
	return html


async def render_report_pdf(report: ReportData) -> bytes:
	"""Render report data as PDF."""
	try:
		from weasyprint import HTML
	except ImportError:
		logger.warning("WeasyPrint not available, returning empty PDF")
		return b""

	html = render_report_html(report)
	pdf = HTML(string=html).write_pdf()
	return pdf


# Convenience functions
async def generate_daily_report(
	session: AsyncSession,
	project_id: str,
	report_date: date | None = None,
	format: str = "html",
) -> bytes | str:
	"""Generate a daily report in the specified format."""
	generator = ReportGenerator()
	report = await generator.generate_daily_report(session, project_id, report_date)

	if format == "pdf":
		return await render_report_pdf(report)
	return render_report_html(report)


async def generate_weekly_report(
	session: AsyncSession,
	project_id: str,
	week_ending: date | None = None,
	format: str = "html",
) -> bytes | str:
	"""Generate a weekly report in the specified format."""
	generator = ReportGenerator()
	report = await generator.generate_weekly_report(session, project_id, week_ending)

	if format == "pdf":
		return await render_report_pdf(report)
	return render_report_html(report)

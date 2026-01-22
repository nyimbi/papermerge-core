# (c) Copyright Datacraft, 2026
"""Metrics collection task for workflow SLA tracking."""
import logging
from datetime import datetime, timedelta

from celery import shared_task
from sqlalchemy import select, and_, or_
from sqlalchemy.orm import Session

from papermerge.core.db.engine import Session as DBSession
from papermerge.core.features.workflows.db.orm import (
	WorkflowStepExecution,
	WorkflowInstance,
	WorkflowStep,
	WorkflowTaskMetric,
	WorkflowTaskSLAConfig,
	SLAStatus,
)
from papermerge.core.utils.tz import utc_now

logger = logging.getLogger(__name__)


@shared_task(name="workflow.metrics_collector")
def collect_task_metrics() -> dict:
	"""
	Celery beat task to collect execution timing metrics.
	Runs every 15 minutes.

	Actions:
	- Create metrics for completed step executions
	- Update SLA status for in-progress executions
	- Calculate duration and breach status
	"""
	logger.info("Starting metrics collection")
	stats = {
		"metrics_created": 0,
		"metrics_updated": 0,
		"breaches_detected": 0,
		"warnings_detected": 0,
	}

	with DBSession() as session:
		# Process completed executions without metrics
		_process_completed_executions(session, stats)

		# Update in-progress metrics
		_update_in_progress_metrics(session, stats)

		session.commit()

	logger.info(f"Metrics collection complete: {stats}")
	return stats


def _process_completed_executions(session: Session, stats: dict) -> None:
	"""Create metrics for recently completed executions."""
	# Find completed executions from last 24 hours without metrics
	cutoff = utc_now() - timedelta(hours=24)

	completed_executions = session.execute(
		select(WorkflowStepExecution).where(
			and_(
				WorkflowStepExecution.status.in_(["approved", "rejected", "skipped"]),
				WorkflowStepExecution.completed_at.isnot(None),
				WorkflowStepExecution.completed_at >= cutoff,
			)
		)
	).scalars().all()

	for execution in completed_executions:
		# Check if metric already exists
		existing = session.execute(
			select(WorkflowTaskMetric).where(
				WorkflowTaskMetric.execution_id == execution.id
			)
		).scalar()

		if existing:
			continue

		metric = _create_metric_for_execution(session, execution)
		if metric:
			session.add(metric)
			stats["metrics_created"] += 1

			if metric.sla_status == SLAStatus.BREACHED.value:
				stats["breaches_detected"] += 1
			elif metric.sla_status == SLAStatus.WARNING.value:
				stats["warnings_detected"] += 1


def _create_metric_for_execution(
	session: Session,
	execution: WorkflowStepExecution,
) -> WorkflowTaskMetric | None:
	"""Create a metric record for a step execution."""
	instance = session.get(WorkflowInstance, execution.instance_id)
	if not instance:
		return None

	step = session.get(WorkflowStep, execution.step_id)
	if not step:
		return None

	# Get SLA config (from step or workflow default)
	sla_config = None
	if step.sla_config_id:
		sla_config = session.get(WorkflowTaskSLAConfig, step.sla_config_id)
	if not sla_config:
		# Try workflow-level default
		sla_config = session.execute(
			select(WorkflowTaskSLAConfig).where(
				and_(
					WorkflowTaskSLAConfig.workflow_id == instance.workflow_id,
					WorkflowTaskSLAConfig.step_id.is_(None),
					WorkflowTaskSLAConfig.is_active == True,
				)
			)
		).scalar()

	# Calculate timing
	started_at = execution.started_at or execution.created_at
	completed_at = execution.completed_at

	if not started_at or not completed_at:
		return None

	duration_seconds = int((completed_at - started_at).total_seconds())

	# Calculate target and SLA status
	target_seconds = None
	target_at = None
	sla_status = SLAStatus.ON_TRACK.value
	breached_at = None

	if sla_config:
		target_seconds = sla_config.target_hours * 3600
		target_at = started_at + timedelta(hours=sla_config.target_hours)

		# Determine SLA status
		if duration_seconds > target_seconds:
			sla_status = SLAStatus.BREACHED.value
			breached_at = target_at
		elif duration_seconds > (target_seconds * sla_config.warning_threshold_percent / 100):
			sla_status = SLAStatus.WARNING.value

	return WorkflowTaskMetric(
		tenant_id=instance.workflow.tenant_id,
		workflow_id=instance.workflow_id,
		instance_id=instance.id,
		step_id=step.id,
		execution_id=execution.id,
		step_type=step.step_type,
		sla_config_id=sla_config.id if sla_config else None,
		started_at=started_at,
		completed_at=completed_at,
		target_at=target_at,
		duration_seconds=duration_seconds,
		target_seconds=target_seconds,
		sla_status=sla_status,
		breached_at=breached_at,
	)


def _update_in_progress_metrics(session: Session, stats: dict) -> None:
	"""Update SLA status for in-progress executions."""
	now = utc_now()

	# Find in-progress metrics that may need status update
	in_progress_metrics = session.execute(
		select(WorkflowTaskMetric).where(
			and_(
				WorkflowTaskMetric.completed_at.is_(None),
				WorkflowTaskMetric.target_at.isnot(None),
				WorkflowTaskMetric.sla_status != SLAStatus.BREACHED.value,
			)
		)
	).scalars().all()

	for metric in in_progress_metrics:
		old_status = metric.sla_status

		if metric.target_at <= now:
			# Deadline passed
			metric.sla_status = SLAStatus.BREACHED.value
			metric.breached_at = metric.target_at
			if old_status != SLAStatus.BREACHED.value:
				stats["breaches_detected"] += 1
		elif metric.target_seconds:
			# Check warning threshold
			elapsed = (now - metric.started_at).total_seconds()
			config = session.get(WorkflowTaskSLAConfig, metric.sla_config_id) if metric.sla_config_id else None
			threshold = (config.warning_threshold_percent if config else 75) / 100

			if elapsed > (metric.target_seconds * threshold):
				if old_status == SLAStatus.ON_TRACK.value:
					metric.sla_status = SLAStatus.WARNING.value
					stats["warnings_detected"] += 1

		if metric.sla_status != old_status:
			stats["metrics_updated"] += 1


@shared_task(name="workflow.sla_dashboard_refresh")
def refresh_sla_dashboard_cache() -> dict:
	"""
	Celery beat task to refresh cached SLA dashboard data.
	Runs every hour.
	"""
	logger.info("Refreshing SLA dashboard cache")

	with DBSession() as session:
		# Calculate aggregate SLA statistics per tenant
		# This would populate a cache for fast dashboard loading
		# For now, this is a placeholder

		stats = _calculate_sla_statistics(session)

	logger.info(f"Dashboard cache refreshed: {stats}")
	return stats


def _calculate_sla_statistics(session: Session) -> dict:
	"""Calculate SLA compliance statistics."""
	from sqlalchemy import func

	# Count metrics by status in last 30 days
	cutoff = utc_now() - timedelta(days=30)

	status_counts = session.execute(
		select(
			WorkflowTaskMetric.sla_status,
			func.count(WorkflowTaskMetric.id).label("count"),
		).where(
			WorkflowTaskMetric.created_at >= cutoff
		).group_by(
			WorkflowTaskMetric.sla_status
		)
	).all()

	counts = {row.sla_status: row.count for row in status_counts}
	total = sum(counts.values())

	return {
		"total_metrics": total,
		"on_track": counts.get(SLAStatus.ON_TRACK.value, 0),
		"warning": counts.get(SLAStatus.WARNING.value, 0),
		"breached": counts.get(SLAStatus.BREACHED.value, 0),
		"compliance_rate": (
			counts.get(SLAStatus.ON_TRACK.value, 0) / total * 100
			if total > 0 else 100.0
		),
	}

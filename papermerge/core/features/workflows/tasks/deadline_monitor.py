# (c) Copyright Datacraft, 2026
"""Deadline monitoring task for workflow SLA enforcement."""
import logging
from datetime import datetime, timedelta
from uuid import UUID

from celery import shared_task
from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from papermerge.core.db.engine import Session as DBSession
from papermerge.core.features.workflows.db.orm import (
	WorkflowApprovalRequest,
	WorkflowApprovalReminder,
	WorkflowEscalationChain,
	WorkflowEscalationLevel,
	WorkflowSLAAlert,
	WorkflowInstance,
)
from papermerge.core.utils.tz import utc_now

logger = logging.getLogger(__name__)

# Reminder thresholds as percentage of deadline
DEFAULT_REMINDER_THRESHOLDS = [50, 75, 90]


@shared_task(name="workflow.deadline_monitor")
def check_approval_deadlines() -> dict:
	"""
	Celery beat task to check pending approvals approaching deadlines.
	Runs every 5 minutes.

	Actions:
	- Send reminders at configured thresholds (50%, 75%, 90%)
	- Trigger escalation when deadlines pass
	- Create SLA alerts for breached deadlines
	"""
	logger.info("Starting deadline monitor check")
	stats = {
		"checked": 0,
		"reminders_sent": 0,
		"escalations_triggered": 0,
		"alerts_created": 0,
	}

	with DBSession() as session:
		# Get all pending approval requests with deadlines
		pending_requests = session.execute(
			select(WorkflowApprovalRequest).where(
				and_(
					WorkflowApprovalRequest.status == "pending",
					WorkflowApprovalRequest.deadline_at.isnot(None),
				)
			)
		).scalars().all()

		now = utc_now()
		stats["checked"] = len(pending_requests)

		for request in pending_requests:
			# Check if deadline has passed
			if request.deadline_at <= now:
				_handle_deadline_breach(session, request, now, stats)
			else:
				_check_reminders(session, request, now, stats)

		session.commit()

	logger.info(f"Deadline monitor complete: {stats}")
	return stats


def _handle_deadline_breach(
	session: Session,
	request: WorkflowApprovalRequest,
	now: datetime,
	stats: dict,
) -> None:
	"""Handle a breached deadline - escalate or alert."""
	# Check if already escalated
	if request.escalated_at and request.current_escalation_level > 0:
		# Check if we should escalate to next level
		if request.escalation_chain_id:
			_escalate_to_next_level(session, request, now, stats)
		return

	# First breach - trigger initial escalation
	if request.escalation_chain_id:
		_escalate_to_next_level(session, request, now, stats)
	else:
		# No escalation chain - just create alert
		_create_sla_alert(
			session,
			request=request,
			alert_type="breach",
			severity="high",
			title=f"Deadline breached: {request.title}",
			message=f"Approval request '{request.title}' has missed its deadline.",
		)
		stats["alerts_created"] += 1


def _escalate_to_next_level(
	session: Session,
	request: WorkflowApprovalRequest,
	now: datetime,
	stats: dict,
) -> None:
	"""Escalate request to the next level in the chain."""
	# Get escalation chain and levels
	chain = session.get(WorkflowEscalationChain, request.escalation_chain_id)
	if not chain or not chain.is_active:
		return

	levels = sorted(chain.levels, key=lambda l: l.level_order)
	current_level = request.current_escalation_level

	# Check if we need to wait before next escalation
	if current_level > 0 and request.escalated_at:
		current_level_config = next(
			(l for l in levels if l.level_order == current_level - 1), None
		)
		if current_level_config:
			wait_until = request.escalated_at + timedelta(hours=current_level_config.wait_hours)
			if now < wait_until:
				return  # Wait period not elapsed

	# Get next level
	if current_level >= len(levels):
		# Max escalation reached - create critical alert
		_create_sla_alert(
			session,
			request=request,
			alert_type="escalation_max",
			severity="critical",
			title=f"Maximum escalation reached: {request.title}",
			message=f"All escalation levels exhausted for '{request.title}'.",
		)
		stats["alerts_created"] += 1
		return

	next_level = levels[current_level]

	# Determine escalation target
	target_user_id = _resolve_escalation_target(session, request, next_level)

	if target_user_id:
		# Update request with escalation
		request.escalated_to = target_user_id
		request.escalated_at = now
		request.current_escalation_level = current_level + 1

		# Create escalation alert
		if next_level.notify_on_escalation:
			_create_sla_alert(
				session,
				request=request,
				alert_type="escalation",
				severity="high",
				title=f"Escalation: {request.title}",
				message=f"Request escalated to level {current_level + 1}.",
				assignee_id=target_user_id,
			)
			stats["alerts_created"] += 1

		# Send notification to escalation target
		_send_escalation_notification(session, request, target_user_id)
		stats["escalations_triggered"] += 1

		logger.info(
			f"Escalated request {request.id} to level {current_level + 1}, "
			f"target user {target_user_id}"
		)


def _resolve_escalation_target(
	session: Session,
	request: WorkflowApprovalRequest,
	level: WorkflowEscalationLevel,
) -> UUID | None:
	"""Resolve the target user for an escalation level."""
	if level.target_type == "user":
		return level.target_id

	elif level.target_type == "role":
		# Get first user with the specified role
		from papermerge.core.db.models import UserRole
		role_user = session.execute(
			select(UserRole.user_id).where(UserRole.role_id == level.target_id).limit(1)
		).scalar()
		return role_user

	elif level.target_type == "manager":
		# Get manager of the current assignee
		if request.assignee_id:
			from papermerge.core.db.models import User
			user = session.get(User, request.assignee_id)
			# Assumes User has manager_id field - may need adjustment
			return getattr(user, "manager_id", None) if user else None

	return None


def _check_reminders(
	session: Session,
	request: WorkflowApprovalRequest,
	now: datetime,
	stats: dict,
) -> None:
	"""Check and send reminders based on deadline proximity."""
	if not request.deadline_at or not request.created_at:
		return

	# Calculate elapsed percentage
	total_duration = (request.deadline_at - request.created_at).total_seconds()
	if total_duration <= 0:
		return

	elapsed = (now - request.created_at).total_seconds()
	elapsed_percent = int((elapsed / total_duration) * 100)

	# Get sent reminder thresholds
	sent_thresholds = {
		r.threshold_percent
		for r in session.execute(
			select(WorkflowApprovalReminder).where(
				WorkflowApprovalReminder.approval_request_id == request.id
			)
		).scalars().all()
	}

	# Check each threshold
	for threshold in DEFAULT_REMINDER_THRESHOLDS:
		if elapsed_percent >= threshold and threshold not in sent_thresholds:
			_send_reminder(session, request, threshold, stats)


def _send_reminder(
	session: Session,
	request: WorkflowApprovalRequest,
	threshold: int,
	stats: dict,
) -> None:
	"""Send a reminder notification."""
	# Record reminder as sent
	reminder = WorkflowApprovalReminder(
		approval_request_id=request.id,
		threshold_percent=threshold,
		channel="in_app",
	)
	session.add(reminder)

	# Update request
	request.reminder_sent_at = utc_now()
	request.last_reminder_threshold = threshold

	# Create alert
	severity = "low" if threshold < 75 else ("medium" if threshold < 90 else "high")
	_create_sla_alert(
		session,
		request=request,
		alert_type="warning",
		severity=severity,
		title=f"Deadline reminder: {request.title}",
		message=f"{threshold}% of deadline time elapsed for '{request.title}'.",
		assignee_id=request.assignee_id,
	)

	stats["reminders_sent"] += 1
	stats["alerts_created"] += 1

	logger.info(f"Sent {threshold}% reminder for request {request.id}")


def _create_sla_alert(
	session: Session,
	request: WorkflowApprovalRequest,
	alert_type: str,
	severity: str,
	title: str,
	message: str,
	assignee_id: UUID | None = None,
) -> WorkflowSLAAlert:
	"""Create an SLA alert record."""
	# Get tenant_id from instance
	instance = session.get(WorkflowInstance, request.instance_id)
	tenant_id = instance.workflow.tenant_id if instance and instance.workflow else None

	alert = WorkflowSLAAlert(
		tenant_id=tenant_id,
		approval_request_id=request.id,
		alert_type=alert_type,
		severity=severity,
		title=title,
		message=message,
		instance_id=request.instance_id,
		step_id=request.step_id,
		assignee_id=assignee_id or request.assignee_id,
	)
	session.add(alert)
	return alert


def _send_escalation_notification(
	session: Session,
	request: WorkflowApprovalRequest,
	target_user_id: UUID,
) -> None:
	"""Send notification to escalation target."""
	# This would integrate with the notification system
	# For now, log the action
	logger.info(
		f"Would send escalation notification to user {target_user_id} "
		f"for request {request.id}"
	)

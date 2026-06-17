# (c) Copyright Datacraft, 2026
"""Business logic for multi-step document approval workflows."""
import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.features.notifications.db.orm import Notification
from papermerge.core.utils.tz import utc_now
from .db.orm import ApprovalStep, ApprovalWorkflow

_log = logging.getLogger(__name__)


def _uuid7str() -> str:
	from uuid6 import uuid7
	return str(uuid7())


async def advance_workflow(workflow_id: str, session: AsyncSession) -> None:
	"""Advance to next pending step; mark workflow approved if none remain."""
	# Load workflow with steps
	stmt = select(ApprovalWorkflow).where(ApprovalWorkflow.id == workflow_id)
	result = await session.execute(stmt)
	workflow = result.scalar_one_or_none()
	if workflow is None:
		_log.warning("advance_workflow: workflow %s not found", workflow_id)
		return

	# Find next pending step in order
	next_stmt = (
		select(ApprovalStep)
		.where(
			ApprovalStep.workflow_id == workflow_id,
			ApprovalStep.status == "pending",
		)
		.order_by(ApprovalStep.step_order)
		.limit(1)
	)
	next_result = await session.execute(next_stmt)
	next_step = next_result.scalar_one_or_none()

	if next_step is None:
		# No more pending steps — workflow is fully approved
		workflow.status = "approved"
		workflow.completed_at = utc_now()
		_log.info("Workflow %s fully approved", workflow_id)
	else:
		# Notify the next approver
		doc_title = f"document {workflow.document_id}"
		await notify_approver(next_step, doc_title, session)


async def notify_approver(
	step: ApprovalStep,
	doc_title: str,
	session: AsyncSession,
) -> None:
	"""Create a Notification record for the step's approver."""
	if step.approver_user_id is None:
		_log.debug(
			"Step %s has no user_id — skipping in-app notification (email-only approver)",
			step.id,
		)
		return

	try:
		user_uuid = UUID(step.approver_user_id)
	except ValueError:
		_log.warning("Invalid approver_user_id %r on step %s", step.approver_user_id, step.id)
		return

	notification = Notification(
		id=_uuid7str(),
		user_id=user_uuid,
		type="approval_request",
		title=f"Document awaiting your approval: {doc_title}",
		message=(
			f"You are step {step.step_order} approver for \"{doc_title}\". "
			"Please review and approve or reject."
		),
		link=f"/documents/{step.workflow.document_id if hasattr(step, 'workflow') and step.workflow else ''}",
	)
	session.add(notification)
	_log.info(
		"Notification queued for user %s (step %s of workflow %s)",
		step.approver_user_id,
		step.id,
		step.workflow_id,
	)

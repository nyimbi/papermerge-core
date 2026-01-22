# (c) Copyright Datacraft, 2026
"""Human-in-the-loop approval tasks for workflow engine."""
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Literal
from uuid import UUID

from prefect import task
from prefect.input import RunInput
from prefect.states import Paused

from papermerge.core.config.prefect import get_prefect_settings
from .base import TaskResult, log_task_start, log_task_complete

logger = logging.getLogger(__name__)
settings = get_prefect_settings()


class ApprovalInput(RunInput):
	"""Input model for approval decisions."""
	decision: Literal["approved", "rejected", "returned"]
	notes: str = ""
	reviewer_id: str = ""


@task(
	name="approval",
	description="Request human approval for document",
	retries=0,  # No retries for approval - handled by Prefect pause
	timeout_seconds=settings.approval_timeout_hours * 3600,
)
async def approval_task(ctx: dict, config: dict) -> dict:
	"""
	Request human approval for a document.

	This task pauses the workflow and waits for human input.
	The workflow resumes when:
	- User submits approval/rejection decision
	- Timeout is reached (escalation triggered)

	Config options:
		- approval_type: str - Type of approval (approval/review/signature)
		- title: str - Approval request title
		- description: str - Description for approver
		- assignee_id: UUID - Specific user to assign
		- assignee_role_id: UUID - Role to assign (any member)
		- assignee_group_id: UUID - Group to assign (any member)
		- deadline_hours: int - Hours until deadline
		- escalation_user_id: UUID - User to escalate to on timeout
		- require_notes: bool - Whether notes are required
		- allow_return: bool - Allow returning for revision

	Returns:
		Approval decision with notes
	"""
	log_task_start("approval", ctx, config)

	document_id = ctx["document_id"]
	instance_id = ctx["instance_id"]
	execution_id = ctx["execution_id"]

	approval_type = config.get("approval_type", "approval")
	title = config.get("title", "Document Approval Required")
	description = config.get("description", "")
	assignee_id = config.get("assignee_id")
	assignee_role_id = config.get("assignee_role_id")
	assignee_group_id = config.get("assignee_group_id")
	deadline_hours = config.get("deadline_hours", settings.approval_timeout_hours)
	require_notes = config.get("require_notes", False)
	allow_return = config.get("allow_return", True)

	try:
		# Create approval request record
		await _create_approval_request(
			ctx=ctx,
			config=config,
			approval_type=approval_type,
			title=title,
			description=description,
			assignee_id=assignee_id,
			assignee_role_id=assignee_role_id,
			assignee_group_id=assignee_group_id,
			deadline_hours=deadline_hours,
		)

		# Send notification to assignee
		await _notify_assignee(
			assignee_id=assignee_id,
			assignee_role_id=assignee_role_id,
			assignee_group_id=assignee_group_id,
			title=title,
			document_id=document_id,
		)

		# Pause flow and wait for input
		# This uses Prefect's built-in pause_flow_run
		from prefect.runtime import flow_run
		from prefect import pause_flow_run

		logger.info(f"Pausing workflow for approval on document {document_id}")

		# Pause and wait for ApprovalInput
		approval_result = await pause_flow_run(
			wait_for_input=ApprovalInput,
			timeout=deadline_hours * 3600,
		)

		# Process the approval result
		decision = approval_result.decision
		notes = approval_result.notes
		reviewer_id = approval_result.reviewer_id

		# Update approval request record
		await _update_approval_request(
			execution_id=execution_id,
			decision=decision,
			notes=notes,
			reviewer_id=reviewer_id,
		)

		# Validate notes if required
		if require_notes and not notes and decision == "rejected":
			logger.warning("Notes required for rejection but not provided")

		approval_output = {
			"document_id": document_id,
			"decision": decision,
			"approved": decision == "approved",
			"rejected": decision == "rejected",
			"returned": decision == "returned",
			"notes": notes,
			"reviewer_id": reviewer_id,
			"decided_at": datetime.now(timezone.utc).isoformat(),
		}

		# Determine next branch based on decision
		if decision == "approved":
			next_branch = "approved"
		elif decision == "returned" and allow_return:
			next_branch = "returned"
		else:
			next_branch = "rejected"

		result = TaskResult.success_result(
			f"Approval {decision}",
			approval=approval_output,
			next_branch=next_branch,
		)
		log_task_complete("approval", ctx, result)
		return result.model_dump()

	except TimeoutError:
		# Handle timeout - escalate if configured
		logger.warning(f"Approval timeout for document {document_id}")

		escalation_user_id = config.get("escalation_user_id")
		if escalation_user_id and settings.escalation_enabled:
			await _escalate_approval(
				execution_id=execution_id,
				escalation_user_id=escalation_user_id,
			)

		result = TaskResult.failure_result(
			"Approval timed out",
			error_code="APPROVAL_TIMEOUT",
			escalated_to=escalation_user_id,
		)
		log_task_complete("approval", ctx, result)
		return result.model_dump()

	except Exception as e:
		logger.exception(f"Approval task failed for document {document_id}")
		result = TaskResult.failure_result(
			f"Approval failed: {str(e)}",
			error_code="APPROVAL_ERROR",
		)
		log_task_complete("approval", ctx, result)
		return result.model_dump()


async def _create_approval_request(
	ctx: dict,
	config: dict,
	approval_type: str,
	title: str,
	description: str,
	assignee_id: str | None,
	assignee_role_id: str | None,
	assignee_group_id: str | None,
	deadline_hours: int,
) -> None:
	"""Create approval request record in database."""
	try:
		from papermerge.core.db.engine import get_session
		from papermerge.core.features.workflows.db.orm import WorkflowApprovalRequest

		deadline_at = datetime.now(timezone.utc) + timedelta(hours=deadline_hours)

		async with get_session() as db:
			approval_request = WorkflowApprovalRequest(
				instance_id=UUID(ctx["instance_id"]),
				step_id=UUID(ctx["step_id"]),
				execution_id=UUID(ctx["execution_id"]),
				prefect_flow_run_id=ctx.get("prefect_flow_run_id"),
				approval_type=approval_type,
				title=title,
				description=description,
				document_id=UUID(ctx["document_id"]),
				requester_id=UUID(ctx["initiated_by"]) if ctx.get("initiated_by") else None,
				assignee_id=UUID(assignee_id) if assignee_id else None,
				assignee_role_id=UUID(assignee_role_id) if assignee_role_id else None,
				assignee_group_id=UUID(assignee_group_id) if assignee_group_id else None,
				status="pending",
				priority=config.get("priority", "normal"),
				deadline_at=deadline_at,
				context_data=ctx.get("previous_results", {}),
			)
			db.add(approval_request)
			await db.commit()

		logger.info(f"Created approval request for execution {ctx['execution_id']}")

	except Exception as e:
		logger.exception("Failed to create approval request record")
		raise


async def _update_approval_request(
	execution_id: str,
	decision: str,
	notes: str,
	reviewer_id: str,
) -> None:
	"""Update approval request with decision."""
	try:
		from sqlalchemy import select
		from papermerge.core.db.engine import get_session
		from papermerge.core.features.workflows.db.orm import WorkflowApprovalRequest

		async with get_session() as db:
			stmt = select(WorkflowApprovalRequest).where(
				WorkflowApprovalRequest.execution_id == UUID(execution_id)
			)
			result = await db.execute(stmt)
			approval_request = result.scalar_one_or_none()

			if approval_request:
				approval_request.status = decision
				approval_request.decision = decision
				approval_request.decision_notes = notes
				approval_request.decided_by = UUID(reviewer_id) if reviewer_id else None
				approval_request.decided_at = datetime.now(timezone.utc)
				await db.commit()

		logger.info(f"Updated approval request {execution_id} with decision: {decision}")

	except Exception as e:
		logger.exception("Failed to update approval request")


async def _notify_assignee(
	assignee_id: str | None,
	assignee_role_id: str | None,
	assignee_group_id: str | None,
	title: str,
	document_id: str,
) -> None:
	"""Send notification to assignee about pending approval."""
	# TODO: Integrate with notification service
	logger.info(
		f"Notification: Approval '{title}' required for document {document_id}. "
		f"Assignee: user={assignee_id}, role={assignee_role_id}, group={assignee_group_id}"
	)


async def _escalate_approval(
	execution_id: str,
	escalation_user_id: str,
) -> None:
	"""Escalate approval to another user."""
	try:
		from sqlalchemy import select
		from papermerge.core.db.engine import get_session
		from papermerge.core.features.workflows.db.orm import WorkflowApprovalRequest

		async with get_session() as db:
			stmt = select(WorkflowApprovalRequest).where(
				WorkflowApprovalRequest.execution_id == UUID(execution_id)
			)
			result = await db.execute(stmt)
			approval_request = result.scalar_one_or_none()

			if approval_request:
				approval_request.escalated_at = datetime.now(timezone.utc)
				approval_request.escalated_to = UUID(escalation_user_id)
				approval_request.assignee_id = UUID(escalation_user_id)
				await db.commit()

		logger.info(f"Escalated approval {execution_id} to user {escalation_user_id}")

		# Notify escalation user
		await _notify_assignee(
			assignee_id=escalation_user_id,
			assignee_role_id=None,
			assignee_group_id=None,
			title="[ESCALATED] Approval Required",
			document_id=str(approval_request.document_id) if approval_request else "",
		)

	except Exception as e:
		logger.exception("Failed to escalate approval")

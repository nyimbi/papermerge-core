# (c) Copyright Datacraft, 2026
"""Workflow engine for document approval and routing."""
import logging
from uuid import UUID
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from papermerge.core.features.workflows.db.orm import (
	Workflow,
	WorkflowStep,
	WorkflowInstance,
	WorkflowStepExecution,
	WorkflowStatus,
	StepStatus,
)

logger = logging.getLogger(__name__)


class WorkflowEngine:
	"""Workflow execution engine."""

	def __init__(self, db: Session):
		self.db = db

	async def start_workflow(
		self,
		workflow_id: UUID,
		document_id: UUID,
		initiated_by: UUID | None = None,
		context: dict | None = None,
	) -> WorkflowInstance:
		"""Start a new workflow instance."""
		workflow = self.db.get(Workflow, workflow_id)
		if not workflow:
			raise ValueError(f"Workflow not found: {workflow_id}")

		if not workflow.is_active:
			raise ValueError(f"Workflow is not active: {workflow_id}")

		first_step = await self._get_first_step(workflow_id)
		if not first_step:
			raise ValueError(f"Workflow has no steps: {workflow_id}")

		instance = WorkflowInstance(
			workflow_id=workflow_id,
			document_id=document_id,
			current_step_id=first_step.id,
			status=WorkflowStatus.IN_PROGRESS.value,
			initiated_by=initiated_by,
			context=context or {},
		)
		self.db.add(instance)
		self.db.flush()

		# Create first step execution
		await self._create_step_execution(instance.id, first_step)

		self.db.commit()
		self.db.refresh(instance)

		logger.info(f"Started workflow {workflow_id} for document {document_id}")
		return instance

	async def process_step_action(
		self,
		execution_id: UUID,
		action: str,
		user_id: UUID,
		comments: str | None = None,
	) -> WorkflowInstance:
		"""Process user action on a workflow step."""
		execution = self.db.get(WorkflowStepExecution, execution_id)
		if not execution:
			raise ValueError(f"Execution not found: {execution_id}")

		if execution.status != StepStatus.PENDING.value:
			raise ValueError(f"Execution is not pending: {execution_id}")

		step = self.db.get(WorkflowStep, execution.step_id)
		instance = self.db.get(WorkflowInstance, execution.instance_id)

		# Verify assignment
		if execution.assigned_to and execution.assigned_to != user_id:
			raise ValueError("User is not assigned to this step")

		# Update execution
		execution.status = action
		execution.action_taken = action
		execution.comments = comments
		execution.completed_at = datetime.now(timezone.utc)

		# Determine next step
		if action == "approved":
			next_step = await self._get_next_step(step)
			if next_step:
				await self._advance_to_step(instance, next_step)
			else:
				await self._complete_workflow(instance)

		elif action == "rejected":
			await self._reject_workflow(instance, comments)

		elif action == "returned":
			prev_step = await self._get_previous_step(step)
			if prev_step:
				await self._return_to_step(instance, prev_step, comments)
			else:
				raise ValueError("Cannot return from first step")

		elif action == "forwarded":
			# Forward to another user - create new execution
			pass

		self.db.commit()
		self.db.refresh(instance)

		logger.info(f"Processed action {action} on execution {execution_id}")
		return instance

	async def check_deadlines(self) -> list[WorkflowStepExecution]:
		"""Check for overdue steps and escalate."""
		now = datetime.now(timezone.utc)
		stmt = select(WorkflowStepExecution).where(
			and_(
				WorkflowStepExecution.status == StepStatus.PENDING.value,
				WorkflowStepExecution.deadline_at < now,
			)
		)
		overdue = list(self.db.scalars(stmt))

		escalated = []
		for execution in overdue:
			step = self.db.get(WorkflowStep, execution.step_id)
			if step.escalation_step_id:
				await self._escalate_step(execution, step)
				escalated.append(execution)

		if escalated:
			self.db.commit()
			logger.info(f"Escalated {len(escalated)} overdue workflow steps")

		return escalated

	async def get_pending_tasks(
		self,
		user_id: UUID,
		tenant_id: UUID | None = None,
	) -> list[WorkflowStepExecution]:
		"""Get pending tasks for a user."""
		stmt = select(WorkflowStepExecution).where(
			and_(
				WorkflowStepExecution.status == StepStatus.PENDING.value,
				WorkflowStepExecution.assigned_to == user_id,
			)
		)
		return list(self.db.scalars(stmt))

	async def cancel_workflow(
		self,
		instance_id: UUID,
		user_id: UUID,
		reason: str | None = None,
	) -> WorkflowInstance:
		"""Cancel a running workflow."""
		instance = self.db.get(WorkflowInstance, instance_id)
		if not instance:
			raise ValueError(f"Workflow instance not found: {instance_id}")

		if instance.status in [WorkflowStatus.COMPLETED.value, WorkflowStatus.CANCELLED.value]:
			raise ValueError("Workflow already finished")

		instance.status = WorkflowStatus.CANCELLED.value
		instance.completed_at = datetime.now(timezone.utc)
		instance.context = instance.context or {}
		instance.context["cancellation_reason"] = reason
		instance.context["cancelled_by"] = str(user_id)

		# Mark pending executions as skipped
		stmt = select(WorkflowStepExecution).where(
			and_(
				WorkflowStepExecution.instance_id == instance_id,
				WorkflowStepExecution.status == StepStatus.PENDING.value,
			)
		)
		for execution in self.db.scalars(stmt):
			execution.status = StepStatus.SKIPPED.value

		self.db.commit()
		self.db.refresh(instance)

		logger.info(f"Cancelled workflow instance {instance_id}")
		return instance

	async def _get_first_step(self, workflow_id: UUID) -> WorkflowStep | None:
		"""Get the first step of a workflow."""
		stmt = select(WorkflowStep).where(
			WorkflowStep.workflow_id == workflow_id
		).order_by(WorkflowStep.step_order)
		return self.db.scalar(stmt)

	async def _get_next_step(self, step: WorkflowStep) -> WorkflowStep | None:
		"""Get the next step after the current one."""
		stmt = select(WorkflowStep).where(
			and_(
				WorkflowStep.workflow_id == step.workflow_id,
				WorkflowStep.step_order > step.step_order,
			)
		).order_by(WorkflowStep.step_order)
		return self.db.scalar(stmt)

	async def _get_previous_step(self, step: WorkflowStep) -> WorkflowStep | None:
		"""Get the previous step."""
		stmt = select(WorkflowStep).where(
			and_(
				WorkflowStep.workflow_id == step.workflow_id,
				WorkflowStep.step_order < step.step_order,
			)
		).order_by(WorkflowStep.step_order.desc())
		return self.db.scalar(stmt)

	async def _create_step_execution(
		self,
		instance_id: UUID,
		step: WorkflowStep,
	) -> WorkflowStepExecution:
		"""Create execution record for a step."""
		deadline_at = None
		if step.deadline_hours:
			deadline_at = datetime.now(timezone.utc) + timedelta(hours=step.deadline_hours)

		# Determine assignee
		assigned_to = None
		if step.assignee_type == "user" and step.assignee_id:
			assigned_to = step.assignee_id
		# TODO: Handle role/group/dynamic assignment

		execution = WorkflowStepExecution(
			instance_id=instance_id,
			step_id=step.id,
			status=StepStatus.PENDING.value,
			assigned_to=assigned_to,
			started_at=datetime.now(timezone.utc),
			deadline_at=deadline_at,
		)
		self.db.add(execution)
		self.db.flush()

		# TODO: Send notification to assignee

		return execution

	async def _advance_to_step(
		self,
		instance: WorkflowInstance,
		step: WorkflowStep,
	) -> None:
		"""Advance workflow to a new step."""
		instance.current_step_id = step.id
		await self._create_step_execution(instance.id, step)

	async def _complete_workflow(self, instance: WorkflowInstance) -> None:
		"""Mark workflow as completed."""
		instance.status = WorkflowStatus.COMPLETED.value
		instance.completed_at = datetime.now(timezone.utc)
		instance.current_step_id = None

		logger.info(f"Completed workflow instance {instance.id}")

	async def _reject_workflow(
		self,
		instance: WorkflowInstance,
		reason: str | None,
	) -> None:
		"""Mark workflow as rejected."""
		instance.status = WorkflowStatus.REJECTED.value
		instance.completed_at = datetime.now(timezone.utc)
		instance.context = instance.context or {}
		instance.context["rejection_reason"] = reason

		logger.info(f"Rejected workflow instance {instance.id}")

	async def _return_to_step(
		self,
		instance: WorkflowInstance,
		step: WorkflowStep,
		comments: str | None,
	) -> None:
		"""Return workflow to a previous step."""
		instance.current_step_id = step.id
		await self._create_step_execution(instance.id, step)
		# Add return comments to context
		instance.context = instance.context or {}
		if "returns" not in instance.context:
			instance.context["returns"] = []
		instance.context["returns"].append({
			"step_id": str(step.id),
			"comments": comments,
			"timestamp": datetime.now(timezone.utc).isoformat(),
		})

	async def _escalate_step(
		self,
		execution: WorkflowStepExecution,
		step: WorkflowStep,
	) -> None:
		"""Escalate an overdue step."""
		execution.status = StepStatus.ESCALATED.value

		# Create execution for escalation step
		escalation_step = self.db.get(WorkflowStep, step.escalation_step_id)
		if escalation_step:
			instance = self.db.get(WorkflowInstance, execution.instance_id)
			instance.current_step_id = escalation_step.id
			await self._create_step_execution(instance.id, escalation_step)

		logger.info(f"Escalated step execution {execution.id}")

# (c) Copyright Datacraft, 2026
"""Prefect workflow engine - main integration class."""
import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from prefect import get_client
from prefect.deployments import run_deployment

from papermerge.core.config.prefect import get_prefect_settings
from .db.orm import Workflow, WorkflowInstance, WorkflowStepExecution, WorkflowStatus, StepStatus
from .translator import WorkflowTranslator, translate_workflow
from .state_sync import StateSyncService

logger = logging.getLogger(__name__)
settings = get_prefect_settings()


class PrefectWorkflowEngine:
	"""Main Prefect workflow engine for dArchiva."""

	def __init__(self, db: AsyncSession):
		self.db = db
		self.sync_service = StateSyncService(db)

	async def start_workflow(
		self,
		workflow_id: UUID,
		document_id: UUID,
		initiated_by: UUID | None = None,
		context: dict | None = None,
	) -> WorkflowInstance:
		"""Start a workflow for a document via Prefect."""
		workflow = await self.db.get(Workflow, workflow_id)
		if not workflow:
			raise ValueError(f"Workflow not found: {workflow_id}")
		if not workflow.is_active:
			raise ValueError(f"Workflow is not active: {workflow_id}")
		if not workflow.nodes:
			raise ValueError(f"Workflow has no nodes defined")

		# Create instance record
		instance = WorkflowInstance(
			workflow_id=workflow_id,
			document_id=document_id,
			status=WorkflowStatus.PENDING.value,
			initiated_by=initiated_by,
			context=context or {},
		)
		self.db.add(instance)
		await self.db.flush()

		# Translate and run
		flow_fn = translate_workflow(
			str(workflow_id), workflow.name, workflow.nodes, workflow.edges or []
		)

		try:
			deployment = await flow_fn.to_deployment(
				name=f"doc-{document_id}",
				work_pool_name=settings.work_pool,
			)
			await deployment.apply()

			flow_run = await run_deployment(
				deployment.name,
				parameters={
					"document_id": str(document_id),
					"instance_id": str(instance.id),
					"tenant_id": str(workflow.tenant_id),
					"initiated_by": str(initiated_by) if initiated_by else None,
					"initial_context": context,
				},
				timeout=0,  # Don't wait
			)

			instance.prefect_flow_run_id = flow_run.id
			instance.status = WorkflowStatus.IN_PROGRESS.value
			await self.db.commit()
			await self.db.refresh(instance)

			logger.info(f"Started workflow {workflow_id} for document {document_id}")
			return instance

		except Exception as e:
			logger.exception(f"Failed to start workflow: {e}")
			instance.status = WorkflowStatus.REJECTED.value
			await self.db.commit()
			raise

	async def resume_workflow(
		self,
		instance_id: UUID,
		input_data: dict,
	) -> WorkflowInstance:
		"""Resume a paused workflow with approval/input data."""
		instance = await self.db.get(WorkflowInstance, instance_id)
		if not instance:
			raise ValueError(f"Instance not found: {instance_id}")
		if instance.status != WorkflowStatus.ON_HOLD.value:
			raise ValueError(f"Instance is not paused: {instance.status}")

		success = await self.sync_service.resume_flow(instance_id, input_data)
		if not success:
			raise ValueError("Failed to resume workflow")

		await self.db.refresh(instance)
		return instance

	async def cancel_workflow(
		self,
		instance_id: UUID,
		user_id: UUID | None = None,
		reason: str | None = None,
	) -> WorkflowInstance:
		"""Cancel a running workflow."""
		instance = await self.db.get(WorkflowInstance, instance_id)
		if not instance:
			raise ValueError(f"Instance not found: {instance_id}")

		if instance.prefect_flow_run_id:
			try:
				async with get_client() as client:
					await client.cancel_flow_run(instance.prefect_flow_run_id)
			except Exception as e:
				logger.warning(f"Failed to cancel Prefect flow: {e}")

		instance.status = WorkflowStatus.CANCELLED.value
		instance.context = instance.context or {}
		instance.context["cancellation_reason"] = reason
		instance.context["cancelled_by"] = str(user_id) if user_id else None
		await self.db.commit()
		await self.db.refresh(instance)

		return instance

	async def get_instance_status(self, instance_id: UUID) -> dict:
		"""Get workflow instance status including Prefect state."""
		instance = await self.db.get(WorkflowInstance, instance_id)
		if not instance:
			raise ValueError(f"Instance not found: {instance_id}")

		# Sync with Prefect
		await self.sync_service.sync_instance_state(instance_id)
		await self.db.refresh(instance)

		return {
			"id": str(instance.id),
			"workflow_id": str(instance.workflow_id),
			"document_id": str(instance.document_id),
			"status": instance.status,
			"prefect_flow_run_id": str(instance.prefect_flow_run_id) if instance.prefect_flow_run_id else None,
			"started_at": instance.started_at.isoformat() if instance.started_at else None,
			"completed_at": instance.completed_at.isoformat() if instance.completed_at else None,
		}

	async def get_pending_tasks(
		self,
		user_id: UUID,
		tenant_id: UUID | None = None,
	) -> list[WorkflowStepExecution]:
		"""Get pending workflow tasks for a user."""
		stmt = select(WorkflowStepExecution).where(
			and_(
				WorkflowStepExecution.status == StepStatus.PENDING.value,
				WorkflowStepExecution.assigned_to == user_id,
			)
		)
		result = await self.db.execute(stmt)
		return list(result.scalars().all())

	async def process_step_action(
		self,
		execution_id: UUID,
		action: str,
		user_id: UUID,
		comments: str | None = None,
	) -> WorkflowInstance:
		"""Process user action on a workflow step via Prefect resume."""
		execution = await self.db.get(WorkflowStepExecution, execution_id)
		if not execution:
			raise ValueError(f"Execution not found: {execution_id}")

		if execution.status != StepStatus.PENDING.value:
			raise ValueError(f"Execution is not pending: {execution_id}")

		# Verify assignment
		if execution.assigned_to and execution.assigned_to != user_id:
			raise ValueError("User is not assigned to this step")

		instance = await self.db.get(WorkflowInstance, execution.instance_id)
		if not instance:
			raise ValueError(f"Instance not found: {execution.instance_id}")

		# Update execution record
		execution.action_taken = action
		execution.comments = comments
		execution.completed_at = datetime.now(timezone.utc)

		if action == "approved":
			execution.status = StepStatus.APPROVED.value
		elif action == "rejected":
			execution.status = StepStatus.REJECTED.value
		elif action == "returned":
			execution.status = StepStatus.RETURNED.value
		else:
			execution.status = action

		await self.db.flush()

		# Resume Prefect flow with the decision
		if instance.prefect_flow_run_id:
			input_data = {
				"decision": action,
				"notes": comments or "",
				"reviewer_id": str(user_id),
			}
			try:
				await self.sync_service.resume_flow(instance.id, input_data)
			except Exception as e:
				logger.warning(f"Failed to resume Prefect flow: {e}")
				# Flow may have completed/cancelled - sync state
				await self.sync_service.sync_instance_state(instance.id)

		await self.db.commit()
		await self.db.refresh(instance)
		return instance

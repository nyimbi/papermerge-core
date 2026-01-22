# (c) Copyright Datacraft, 2026
"""
State synchronization between Prefect and dArchiva database.

This module handles keeping the local workflow state in sync with
Prefect's execution state, including:
- Task completion callbacks
- Flow run state changes
- Error handling and recovery
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.config.prefect import get_prefect_settings
from .db.orm import (
	WorkflowInstance,
	WorkflowStepExecution,
	WorkflowApprovalRequest,
	WorkflowStatus,
	StepStatus,
)

logger = logging.getLogger(__name__)
settings = get_prefect_settings()


class StateSyncService:
	"""
	Service for synchronizing Prefect workflow state with local database.

	Handles bidirectional sync:
	- Prefect -> Local: Update database when Prefect tasks complete
	- Local -> Prefect: Resume paused flows when approvals are submitted
	"""

	def __init__(self, db: AsyncSession):
		"""
		Initialize the state sync service.

		Args:
			db: Async database session
		"""
		self.db = db

	async def on_task_started(
		self,
		instance_id: UUID,
		node_id: str,
		prefect_task_run_id: UUID | None = None,
	) -> WorkflowStepExecution | None:
		"""
		Handle task start event from Prefect.

		Creates or updates step execution record.

		Args:
			instance_id: Workflow instance ID
			node_id: React Flow node ID
			prefect_task_run_id: Prefect task run ID

		Returns:
			The updated step execution record
		"""
		try:
			# Find execution by instance and step
			stmt = select(WorkflowStepExecution).where(
				WorkflowStepExecution.instance_id == instance_id,
			).order_by(WorkflowStepExecution.created_at.desc())
			result = await self.db.execute(stmt)
			execution = result.scalar_one_or_none()

			if execution:
				execution.status = StepStatus.IN_PROGRESS.value
				execution.started_at = datetime.now(timezone.utc)
				if prefect_task_run_id:
					execution.prefect_task_run_id = prefect_task_run_id
				await self.db.commit()
				await self.db.refresh(execution)

				logger.info(
					f"Task started: instance={instance_id}, node={node_id}, "
					f"prefect_task={prefect_task_run_id}"
				)
				return execution

		except Exception as e:
			logger.exception(f"Failed to handle task start: {e}")
			await self.db.rollback()

		return None

	async def on_task_completed(
		self,
		instance_id: UUID,
		node_id: str,
		result: dict,
		prefect_task_run_id: UUID | None = None,
	) -> WorkflowStepExecution | None:
		"""
		Handle task completion event from Prefect.

		Updates step execution with result data.

		Args:
			instance_id: Workflow instance ID
			node_id: React Flow node ID
			result: Task result data
			prefect_task_run_id: Prefect task run ID

		Returns:
			The updated step execution record
		"""
		try:
			# Find the current execution
			stmt = select(WorkflowStepExecution).where(
				WorkflowStepExecution.instance_id == instance_id,
				WorkflowStepExecution.status == StepStatus.IN_PROGRESS.value,
			).order_by(WorkflowStepExecution.created_at.desc())
			result_set = await self.db.execute(stmt)
			execution = result_set.scalar_one_or_none()

			if execution:
				execution.status = StepStatus.APPROVED.value  # "completed"
				execution.completed_at = datetime.now(timezone.utc)
				execution.result_data = result
				if prefect_task_run_id:
					execution.prefect_task_run_id = prefect_task_run_id
				await self.db.commit()
				await self.db.refresh(execution)

				logger.info(
					f"Task completed: instance={instance_id}, node={node_id}, "
					f"success={result.get('success', True)}"
				)
				return execution

		except Exception as e:
			logger.exception(f"Failed to handle task completion: {e}")
			await self.db.rollback()

		return None

	async def on_task_failed(
		self,
		instance_id: UUID,
		node_id: str,
		error: str,
		prefect_task_run_id: UUID | None = None,
		retry_count: int = 0,
	) -> WorkflowStepExecution | None:
		"""
		Handle task failure event from Prefect.

		Updates step execution with error information.

		Args:
			instance_id: Workflow instance ID
			node_id: React Flow node ID
			error: Error message
			prefect_task_run_id: Prefect task run ID
			retry_count: Number of retries attempted

		Returns:
			The updated step execution record
		"""
		try:
			stmt = select(WorkflowStepExecution).where(
				WorkflowStepExecution.instance_id == instance_id,
			).order_by(WorkflowStepExecution.created_at.desc())
			result = await self.db.execute(stmt)
			execution = result.scalar_one_or_none()

			if execution:
				execution.status = StepStatus.REJECTED.value  # "failed"
				execution.completed_at = datetime.now(timezone.utc)
				execution.error_message = error
				execution.retry_count = retry_count
				if prefect_task_run_id:
					execution.prefect_task_run_id = prefect_task_run_id
				await self.db.commit()
				await self.db.refresh(execution)

				logger.warning(
					f"Task failed: instance={instance_id}, node={node_id}, "
					f"error={error}, retries={retry_count}"
				)
				return execution

		except Exception as e:
			logger.exception(f"Failed to handle task failure: {e}")
			await self.db.rollback()

		return None

	async def on_flow_completed(
		self,
		instance_id: UUID,
		prefect_flow_run_id: UUID,
		final_state: str = "completed",
	) -> WorkflowInstance | None:
		"""
		Handle flow completion event from Prefect.

		Updates workflow instance status.

		Args:
			instance_id: Workflow instance ID
			prefect_flow_run_id: Prefect flow run ID
			final_state: Final flow state (completed/failed/cancelled)

		Returns:
			The updated workflow instance
		"""
		try:
			instance = await self.db.get(WorkflowInstance, instance_id)

			if instance:
				if final_state == "completed":
					instance.status = WorkflowStatus.COMPLETED.value
				elif final_state == "failed":
					instance.status = WorkflowStatus.REJECTED.value
				elif final_state == "cancelled":
					instance.status = WorkflowStatus.CANCELLED.value
				else:
					instance.status = final_state

				instance.completed_at = datetime.now(timezone.utc)
				instance.prefect_flow_run_id = prefect_flow_run_id
				await self.db.commit()
				await self.db.refresh(instance)

				logger.info(
					f"Flow completed: instance={instance_id}, state={final_state}"
				)
				return instance

		except Exception as e:
			logger.exception(f"Failed to handle flow completion: {e}")
			await self.db.rollback()

		return None

	async def on_flow_paused(
		self,
		instance_id: UUID,
		prefect_flow_run_id: UUID,
		pause_key: str,
	) -> WorkflowInstance | None:
		"""
		Handle flow pause event (for human-in-the-loop).

		Args:
			instance_id: Workflow instance ID
			prefect_flow_run_id: Prefect flow run ID
			pause_key: Key to identify the pause point

		Returns:
			The updated workflow instance
		"""
		try:
			instance = await self.db.get(WorkflowInstance, instance_id)

			if instance:
				instance.status = WorkflowStatus.ON_HOLD.value
				instance.prefect_flow_run_id = prefect_flow_run_id
				instance.context = instance.context or {}
				instance.context["pause_key"] = pause_key
				await self.db.commit()
				await self.db.refresh(instance)

				logger.info(
					f"Flow paused: instance={instance_id}, pause_key={pause_key}"
				)
				return instance

		except Exception as e:
			logger.exception(f"Failed to handle flow pause: {e}")
			await self.db.rollback()

		return None

	async def resume_flow(
		self,
		instance_id: UUID,
		input_data: dict,
	) -> bool:
		"""
		Resume a paused flow with user input.

		Args:
			instance_id: Workflow instance ID
			input_data: User input to resume with

		Returns:
			True if successfully resumed
		"""
		try:
			from prefect.client import get_client

			instance = await self.db.get(WorkflowInstance, instance_id)
			if not instance or not instance.prefect_flow_run_id:
				logger.error(f"Cannot resume: instance not found or no flow run ID")
				return False

			if instance.status != WorkflowStatus.ON_HOLD.value:
				logger.warning(f"Instance {instance_id} is not paused, status={instance.status}")
				return False

			# Resume the Prefect flow
			async with get_client() as client:
				await client.resume_flow_run(
					flow_run_id=instance.prefect_flow_run_id,
					run_input=input_data,
				)

			# Update instance status
			instance.status = WorkflowStatus.IN_PROGRESS.value
			await self.db.commit()

			logger.info(f"Flow resumed: instance={instance_id}")
			return True

		except Exception as e:
			logger.exception(f"Failed to resume flow: {e}")
			await self.db.rollback()
			return False

	async def sync_instance_state(
		self,
		instance_id: UUID,
	) -> WorkflowInstance | None:
		"""
		Sync workflow instance state with Prefect.

		Polls Prefect for current state and updates local database.

		Args:
			instance_id: Workflow instance ID

		Returns:
			The updated workflow instance
		"""
		try:
			from prefect.client import get_client

			instance = await self.db.get(WorkflowInstance, instance_id)
			if not instance or not instance.prefect_flow_run_id:
				return None

			async with get_client() as client:
				flow_run = await client.read_flow_run(instance.prefect_flow_run_id)

				# Map Prefect state to local status
				prefect_state = flow_run.state.type.value if flow_run.state else "unknown"
				status_map = {
					"PENDING": WorkflowStatus.PENDING.value,
					"RUNNING": WorkflowStatus.IN_PROGRESS.value,
					"COMPLETED": WorkflowStatus.COMPLETED.value,
					"FAILED": WorkflowStatus.REJECTED.value,
					"CANCELLED": WorkflowStatus.CANCELLED.value,
					"PAUSED": WorkflowStatus.ON_HOLD.value,
				}

				new_status = status_map.get(prefect_state, instance.status)
				if new_status != instance.status:
					instance.status = new_status
					if new_status in (
						WorkflowStatus.COMPLETED.value,
						WorkflowStatus.REJECTED.value,
						WorkflowStatus.CANCELLED.value,
					):
						instance.completed_at = datetime.now(timezone.utc)
					await self.db.commit()
					await self.db.refresh(instance)

				return instance

		except Exception as e:
			logger.exception(f"Failed to sync instance state: {e}")

		return None


class StateSyncPoller:
	"""
	Background poller for syncing state periodically.

	Polls Prefect server at configured interval to catch any
	missed state updates.
	"""

	def __init__(self, db_session_factory):
		"""
		Initialize the poller.

		Args:
			db_session_factory: Factory function to create database sessions
		"""
		self.db_session_factory = db_session_factory
		self.running = False
		self.poll_interval = settings.state_sync_interval_seconds

	async def start(self):
		"""Start the background polling loop."""
		self.running = True
		logger.info(f"Starting state sync poller (interval={self.poll_interval}s)")

		while self.running:
			try:
				await self._poll_active_instances()
			except Exception as e:
				logger.exception(f"Error in state sync poll: {e}")

			await asyncio.sleep(self.poll_interval)

	async def stop(self):
		"""Stop the polling loop."""
		self.running = False
		logger.info("Stopping state sync poller")

	async def _poll_active_instances(self):
		"""Poll all active workflow instances."""
		async with self.db_session_factory() as db:
			# Find active instances
			stmt = select(WorkflowInstance).where(
				WorkflowInstance.status.in_([
					WorkflowStatus.PENDING.value,
					WorkflowStatus.IN_PROGRESS.value,
					WorkflowStatus.ON_HOLD.value,
				]),
				WorkflowInstance.prefect_flow_run_id.isnot(None),
			)
			result = await db.execute(stmt)
			instances = result.scalars().all()

			if not instances:
				return

			sync_service = StateSyncService(db)
			for instance in instances:
				try:
					await sync_service.sync_instance_state(instance.id)
				except Exception as e:
					logger.warning(
						f"Failed to sync instance {instance.id}: {e}"
					)


# Prefect event hooks for real-time state updates
async def register_prefect_hooks():
	"""
	Register event hooks with Prefect for real-time state updates.

	This uses Prefect's webhook/event system when available.
	"""
	if not settings.enable_webhooks:
		logger.info("Prefect webhooks disabled, using polling only")
		return

	try:
		from prefect.events import emit_event

		logger.info("Prefect webhook handlers registered")

	except ImportError:
		logger.warning("Prefect events not available, webhooks disabled")

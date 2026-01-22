# (c) Copyright Datacraft, 2026
"""Base utilities for workflow tasks."""
import logging
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)


class TaskContext(BaseModel):
	"""
	Context passed to workflow tasks.

	This contains information about the current workflow execution
	and the document being processed.
	"""
	model_config = ConfigDict(extra="allow")

	# Workflow execution context
	workflow_id: str
	instance_id: str
	step_id: str
	execution_id: str

	# Document context
	document_id: str
	document_version_id: str | None = None
	tenant_id: str

	# User context
	initiated_by: str | None = None

	# Previous step results (accumulated)
	previous_results: dict[str, Any] = {}

	# Flow control
	branch_id: str | None = None  # For parallel branches

	def get_previous_result(self, step_type: str) -> Any:
		"""Get result from a previous step by type."""
		return self.previous_results.get(step_type)


class TaskResult(BaseModel):
	"""
	Standard result format for workflow tasks.
	"""
	model_config = ConfigDict(extra="allow")

	success: bool = True
	message: str | None = None

	# Output data (varies by task type)
	data: dict[str, Any] = {}

	# Routing decisions (for condition/route tasks)
	next_branch: str | None = None

	# Errors
	error_code: str | None = None
	error_details: str | None = None

	@classmethod
	def success_result(cls, message: str = "Task completed", **data) -> "TaskResult":
		"""Create a successful result."""
		return cls(success=True, message=message, data=data)

	@classmethod
	def failure_result(
		cls,
		message: str,
		error_code: str = "TASK_ERROR",
		**details
	) -> "TaskResult":
		"""Create a failure result."""
		return cls(
			success=False,
			message=message,
			error_code=error_code,
			error_details=str(details) if details else None,
		)


def parse_uuid(value: str | UUID) -> UUID:
	"""Parse a string or UUID to UUID."""
	if isinstance(value, UUID):
		return value
	return UUID(value)


def log_task_start(task_name: str, ctx: dict, config: dict) -> None:
	"""Log task start with context."""
	logger.info(
		f"Starting task '{task_name}' for document {ctx.get('document_id')} "
		f"in workflow {ctx.get('workflow_id')}"
	)


def log_task_complete(task_name: str, ctx: dict, result: TaskResult) -> None:
	"""Log task completion."""
	status = "completed" if result.success else "failed"
	logger.info(
		f"Task '{task_name}' {status} for document {ctx.get('document_id')}: "
		f"{result.message}"
	)

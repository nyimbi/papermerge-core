# (c) Copyright Datacraft, 2026
"""
Prefect task registry for dArchiva workflow engine.

This module provides a registry of all available Prefect tasks that can be
used in workflow definitions. Tasks are mapped by their step_type from the
React Flow designer.
"""
from typing import Callable, Any

from .document import source_task, preprocess_task, store_task, index_task
from .ai import ocr_task, nlp_task, classify_task
from .tagging import tag_task
from .routing import route_task, condition_task, split_task, merge_task
from .validation import validate_task, transform_task
from .notification import notify_task
from .approval import approval_task

# Type alias for task functions
TaskFunction = Callable[[dict, dict], Any]

# Registry mapping step types to Prefect tasks
TASK_REGISTRY: dict[str, TaskFunction] = {
	# Document lifecycle tasks
	"source": source_task,
	"preprocess": preprocess_task,
	"store": store_task,
	"index": index_task,

	# AI/ML processing tasks
	"ocr": ocr_task,
	"nlp": nlp_task,
	"classify": classify_task,
	"tag": tag_task,

	# Flow control tasks
	"route": route_task,
	"condition": condition_task,
	"split": split_task,
	"merge": merge_task,

	# Validation tasks
	"validate": validate_task,
	"transform": transform_task,

	# Notification and approval tasks
	"notify": notify_task,
	"approval": approval_task,
}


def get_task(step_type: str) -> TaskFunction | None:
	"""
	Get a task function by step type.

	Args:
		step_type: The type of step/node from the workflow definition

	Returns:
		The corresponding Prefect task function, or None if not found
	"""
	return TASK_REGISTRY.get(step_type)


def list_available_tasks() -> list[str]:
	"""Return list of available task types."""
	return list(TASK_REGISTRY.keys())


def is_task_type_valid(step_type: str) -> bool:
	"""Check if a step type corresponds to a valid task."""
	return step_type in TASK_REGISTRY


__all__ = [
	"TASK_REGISTRY",
	"get_task",
	"list_available_tasks",
	"is_task_type_valid",
	# Document tasks
	"source_task",
	"preprocess_task",
	"store_task",
	"index_task",
	# AI tasks
	"ocr_task",
	"nlp_task",
	"classify_task",
	# Routing tasks
	"route_task",
	"condition_task",
	"split_task",
	"merge_task",
	# Validation tasks
	"validate_task",
	"transform_task",
	# Notification tasks
	"notify_task",
	"approval_task",
]

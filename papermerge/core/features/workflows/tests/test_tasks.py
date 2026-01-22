# (c) Copyright Datacraft, 2026
"""Tests for workflow tasks."""
import pytest
from papermerge.core.features.workflows.tasks import (
	TASK_REGISTRY,
	get_task,
	list_available_tasks,
	is_task_type_valid,
)
from papermerge.core.features.workflows.tasks.base import TaskResult


class TestTaskRegistry:
	"""Tests for task registry."""

	def test_all_tasks_registered(self):
		"""Verify all expected task types are registered."""
		expected = {
			"source", "preprocess", "store", "index",
			"ocr", "nlp", "classify",
			"route", "condition", "split", "merge",
			"validate", "transform",
			"notify", "approval",
		}
		assert set(TASK_REGISTRY.keys()) == expected

	def test_get_task(self):
		"""Test getting task by type."""
		task = get_task("ocr")
		assert task is not None
		assert callable(task)

	def test_get_unknown_task(self):
		"""Test getting unknown task returns None."""
		assert get_task("unknown_task_type") is None

	def test_list_available_tasks(self):
		"""Test listing available tasks."""
		tasks = list_available_tasks()
		assert len(tasks) == 15
		assert "ocr" in tasks
		assert "approval" in tasks

	def test_is_task_type_valid(self):
		"""Test task type validation."""
		assert is_task_type_valid("ocr")
		assert is_task_type_valid("approval")
		assert not is_task_type_valid("invalid")


class TestTaskResult:
	"""Tests for TaskResult model."""

	def test_success_result(self):
		"""Test creating success result."""
		result = TaskResult.success_result("Done", key="value")
		assert result.success
		assert result.message == "Done"
		assert result.data["key"] == "value"

	def test_failure_result(self):
		"""Test creating failure result."""
		result = TaskResult.failure_result("Failed", error_code="ERR001")
		assert not result.success
		assert result.message == "Failed"
		assert result.error_code == "ERR001"

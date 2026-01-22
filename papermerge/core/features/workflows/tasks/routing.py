# (c) Copyright Datacraft, 2026
"""Flow control tasks for workflow engine."""
import logging
from typing import Any

from prefect import task

from papermerge.core.config.prefect import get_prefect_settings
from .base import TaskResult, log_task_start, log_task_complete

logger = logging.getLogger(__name__)
settings = get_prefect_settings()


@task(
	name="route",
	description="Route document to next step based on rules",
	retries=1,
	retry_delay_seconds=5,
)
async def route_task(ctx: dict, config: dict) -> dict:
	"""
	Route a document based on its properties.

	Routes can be determined by:
	- Document type
	- Custom field values
	- Classification results
	- User assignment

	Config options:
		- routes: list[dict] - Routing rules
		- default_route: str - Default route if no match
		- route_by: str - Property to route by (type/field/classification)

	Returns:
		Routing decision with target
	"""
	log_task_start("route", ctx, config)

	document_id = ctx["document_id"]
	routes = config.get("routes", [])
	default_route = config.get("default_route", "default")
	route_by = config.get("route_by", "type")

	try:
		# Get context for routing decision
		classify_result = ctx.get("previous_results", {}).get("classify", {})
		doc_type = classify_result.get("data", {}).get(
			"classification", {}
		).get("assigned_type", "unknown")

		routing_result = {
			"document_id": document_id,
			"route_by": route_by,
			"evaluated_value": None,
			"matched_rule": None,
			"selected_route": default_route,
		}

		if route_by == "type":
			routing_result["evaluated_value"] = doc_type

			# Find matching route
			for route in routes:
				if route.get("match") == doc_type:
					routing_result["matched_rule"] = route
					routing_result["selected_route"] = route.get("target", default_route)
					break

		elif route_by == "field":
			# Route by custom field value
			field_name = config.get("field_name")
			field_value = ctx.get("previous_results", {}).get("validate", {}).get(
				"data", {}
			).get("fields", {}).get(field_name)

			routing_result["evaluated_value"] = field_value

			for route in routes:
				if route.get("match") == field_value:
					routing_result["matched_rule"] = route
					routing_result["selected_route"] = route.get("target", default_route)
					break

		result = TaskResult.success_result(
			f"Routed to '{routing_result['selected_route']}'",
			routing=routing_result,
			next_branch=routing_result["selected_route"],
		)
		log_task_complete("route", ctx, result)
		return result.model_dump()

	except Exception as e:
		logger.exception(f"Routing failed for document {document_id}")
		result = TaskResult.failure_result(
			f"Routing failed: {str(e)}",
			error_code="ROUTE_ERROR",
		)
		log_task_complete("route", ctx, result)
		return result.model_dump()


@task(
	name="condition",
	description="Evaluate condition and branch accordingly",
	retries=1,
	retry_delay_seconds=5,
)
async def condition_task(ctx: dict, config: dict) -> dict:
	"""
	Evaluate a condition expression and determine branch.

	Supports expressions like:
	- classification.confidence > 0.8
	- nlp.entities.contains("DATE")
	- document.page_count <= 10

	Config options:
		- expression: str - Condition expression to evaluate
		- true_branch: str - Branch if condition is true
		- false_branch: str - Branch if condition is false

	Returns:
		Condition evaluation result with branch selection
	"""
	log_task_start("condition", ctx, config)

	document_id = ctx["document_id"]
	expression = config.get("expression", "true")
	true_branch = config.get("true_branch", "true")
	false_branch = config.get("false_branch", "false")

	try:
		# Import expression evaluator
		from papermerge.core.features.workflows.expressions import evaluate_condition

		# Build evaluation context from previous results
		eval_context = {
			"document_id": document_id,
			"previous_results": ctx.get("previous_results", {}),
		}

		# Flatten common results for easy access
		for step_type, step_result in ctx.get("previous_results", {}).items():
			eval_context[step_type] = step_result.get("data", {})

		# Evaluate the condition
		condition_result = evaluate_condition(expression, eval_context)

		selected_branch = true_branch if condition_result else false_branch

		result = TaskResult.success_result(
			f"Condition '{expression}' evaluated to {condition_result}",
			condition={
				"expression": expression,
				"result": condition_result,
				"selected_branch": selected_branch,
			},
			next_branch=selected_branch,
		)
		log_task_complete("condition", ctx, result)
		return result.model_dump()

	except Exception as e:
		logger.exception(f"Condition evaluation failed for document {document_id}")
		result = TaskResult.failure_result(
			f"Condition evaluation failed: {str(e)}",
			error_code="CONDITION_ERROR",
		)
		log_task_complete("condition", ctx, result)
		return result.model_dump()


@task(
	name="split",
	description="Split workflow into parallel branches",
	retries=1,
	retry_delay_seconds=5,
)
async def split_task(ctx: dict, config: dict) -> dict:
	"""
	Split workflow execution into parallel branches.

	Each branch executes independently and can be merged later.

	Config options:
		- branches: list[str] - Branch identifiers
		- wait_for_all: bool - Whether to wait for all branches

	Returns:
		Split point information
	"""
	log_task_start("split", ctx, config)

	document_id = ctx["document_id"]
	branches = config.get("branches", ["branch_a", "branch_b"])
	wait_for_all = config.get("wait_for_all", True)

	try:
		split_result = {
			"document_id": document_id,
			"split_point": ctx.get("step_id"),
			"branches": branches,
			"branch_count": len(branches),
			"wait_for_all": wait_for_all,
		}

		result = TaskResult.success_result(
			f"Split into {len(branches)} parallel branches",
			split=split_result,
			branches=branches,
		)
		log_task_complete("split", ctx, result)
		return result.model_dump()

	except Exception as e:
		logger.exception(f"Split failed for document {document_id}")
		result = TaskResult.failure_result(
			f"Split failed: {str(e)}",
			error_code="SPLIT_ERROR",
		)
		log_task_complete("split", ctx, result)
		return result.model_dump()


@task(
	name="merge",
	description="Merge parallel branches back together",
	retries=1,
	retry_delay_seconds=5,
)
async def merge_task(ctx: dict, config: dict) -> dict:
	"""
	Merge results from parallel branches.

	Combines results from split branches back into a single execution path.

	Config options:
		- merge_strategy: str - How to combine results (all/any/custom)
		- expected_branches: list[str] - Branches expected to merge

	Returns:
		Merged results from all branches
	"""
	log_task_start("merge", ctx, config)

	document_id = ctx["document_id"]
	merge_strategy = config.get("merge_strategy", "all")
	expected_branches = config.get("expected_branches", [])

	try:
		# Collect results from all branches
		branch_results = ctx.get("branch_results", {})

		merge_result = {
			"document_id": document_id,
			"merge_point": ctx.get("step_id"),
			"strategy": merge_strategy,
			"branches_received": list(branch_results.keys()),
			"branches_expected": expected_branches,
			"all_complete": len(branch_results) >= len(expected_branches),
			"combined_data": {},
		}

		# Merge branch data based on strategy
		if merge_strategy == "all":
			# Combine all branch results
			for branch_id, branch_data in branch_results.items():
				merge_result["combined_data"][branch_id] = branch_data
		elif merge_strategy == "any":
			# Take first successful branch
			for branch_id, branch_data in branch_results.items():
				if branch_data.get("success", False):
					merge_result["combined_data"] = branch_data
					break

		result = TaskResult.success_result(
			f"Merged {len(branch_results)} branches",
			merge=merge_result,
		)
		log_task_complete("merge", ctx, result)
		return result.model_dump()

	except Exception as e:
		logger.exception(f"Merge failed for document {document_id}")
		result = TaskResult.failure_result(
			f"Merge failed: {str(e)}",
			error_code="MERGE_ERROR",
		)
		log_task_complete("merge", ctx, result)
		return result.model_dump()

# (c) Copyright Datacraft, 2026
"""Tagging tasks for workflow engine."""
import logging
from uuid import UUID

from prefect import task

from papermerge.core.config.prefect import get_prefect_settings
from .base import TaskResult, log_task_start, log_task_complete

logger = logging.getLogger(__name__)
settings = get_prefect_settings()


@task(
	name="tag",
	description="Assign tags to document based on AI results",
	retries=settings.default_retries,
	retry_delay_seconds=settings.retry_delay_seconds,
)
async def tag_task(ctx: dict, config: dict) -> dict:
	"""
	Automatically tag a document based on previous AI analysis.

	Tags are extracted from:
	- Classification (document type)
	- NLP (vendor names, dates)
	- Validation/Transformation (line items, specific fields)

	Config options:
		- include_type: bool - Include document type as tag
		- include_vendor: bool - Include vendor names as tags
		- include_date: bool - Include dates as tags
		- custom_tags: list[str] - Additional static tags to apply
		- tag_prefix: str - Optional prefix for auto-generated tags

	Returns:
		Tagging results with applied tags
	"""
	log_task_start("tag", ctx, config)

	document_id = ctx["document_id"]
	initiated_by = ctx.get("initiated_by")
	include_type = config.get("include_type", True)
	include_vendor = config.get("include_vendor", True)
	include_date = config.get("include_date", True)
	custom_tags = config.get("custom_tags", [])
	prefix = config.get("tag_prefix", "")

	try:
		from papermerge.core.db.engine import get_session
		from papermerge.core.features.nodes.db import api as nodes_api

		tags_to_apply = set(custom_tags)

		# 1. Extract type from classification
		if include_type:
			classify_result = ctx.get("previous_results", {}).get("classify", {})
			doc_type = classify_result.get("data", {}).get("classification", {}).get("assigned_type")
			if doc_type:
				tags_to_apply.add(f"{prefix}{doc_type}")

		# 2. Extract vendor/date from NLP
		nlp_result = ctx.get("previous_results", {}).get("nlp", {})
		entities = nlp_result.get("data", {}).get("entities", [])
		
		for entity in entities:
			label = entity.get("label", "").upper()
			text = entity.get("text", "")
			
			if include_vendor and label == "ORG":
				tags_to_apply.add(f"{prefix}{text}")
			elif include_date and label == "DATE":
				tags_to_apply.add(f"{prefix}{text}")

		# 3. Extract fields from validation/transform
		validate_result = ctx.get("previous_results", {}).get("validate", {})
		fields = validate_result.get("data", {}).get("fields", {})
		for key, value in fields.items():
			if isinstance(value, str):
				tags_to_apply.add(f"{prefix}{value}")
			elif isinstance(value, list):
				for item in value:
					if isinstance(item, str):
						tags_to_apply.add(f"{prefix}{item}")

		# Apply tags to node
		async with get_session() as db:
			if tags_to_apply:
				await nodes_api.assign_node_tags(
					db_session=db,
					node_id=UUID(document_id),
					tags=list(tags_to_apply),
					created_by=UUID(initiated_by) if initiated_by else None
				)

		result = TaskResult.success_result(
			f"Applied {len(tags_to_apply)} tags to document",
			tagging={
				"document_id": document_id,
				"applied_tags": list(tags_to_apply),
				"count": len(tags_to_apply)
			}
		)
		log_task_complete("tag", ctx, result)
		return result.model_dump()

	except Exception as e:
		logger.exception(f"Tagging failed for document {document_id}")
		result = TaskResult.failure_result(
			f"Tagging failed: {str(e)}",
			error_code="TAG_ERROR",
		)
		log_task_complete("tag", ctx, result)
		return result.model_dump()

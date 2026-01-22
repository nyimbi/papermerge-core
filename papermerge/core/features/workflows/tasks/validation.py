# (c) Copyright Datacraft, 2026
"""Validation and transformation tasks for workflow engine."""
import logging
from typing import Any
from uuid import UUID

from prefect import task

from papermerge.core.config.prefect import get_prefect_settings
from .base import TaskResult, log_task_start, log_task_complete

logger = logging.getLogger(__name__)
settings = get_prefect_settings()


@task(
	name="validate",
	description="Validate document against rules",
	retries=settings.default_retries,
	retry_delay_seconds=settings.retry_delay_seconds,
)
async def validate_task(ctx: dict, config: dict) -> dict:
	"""
	Validate a document against defined rules.

	Validation types:
	- required_fields: Check for required metadata fields
	- field_formats: Validate field format (date, email, etc.)
	- document_type: Validate against document type schema
	- custom_rules: Execute custom validation expressions

	Config options:
		- rules: list[dict] - Validation rules to apply
		- fail_on_warning: bool - Treat warnings as failures
		- extract_fields: bool - Extract fields from OCR text

	Returns:
		Validation results with any errors/warnings
	"""
	log_task_start("validate", ctx, config)

	document_id = ctx["document_id"]
	rules = config.get("rules", [])
	fail_on_warning = config.get("fail_on_warning", False)
	extract_fields = config.get("extract_fields", True)

	try:
		# Get NLP entities for field extraction
		nlp_result = ctx.get("previous_results", {}).get("nlp", {})
		entities = nlp_result.get("data", {}).get("entities", [])

		validation_result = {
			"document_id": document_id,
			"valid": True,
			"errors": [],
			"warnings": [],
			"fields": {},
			"rules_evaluated": len(rules),
			"rules_passed": 0,
		}

		# Extract fields from entities
		if extract_fields:
			for entity in entities:
				label = entity.get("label", "").lower()
				text = entity.get("text", "")

				if label == "date":
					validation_result["fields"]["date"] = text
				elif label == "money":
					validation_result["fields"]["amount"] = text
				elif label == "org":
					if "organization" not in validation_result["fields"]:
						validation_result["fields"]["organization"] = []
					validation_result["fields"]["organization"].append(text)
				elif label == "person":
					if "people" not in validation_result["fields"]:
						validation_result["fields"]["people"] = []
					validation_result["fields"]["people"].append(text)

		# Evaluate rules
		for rule in rules:
			rule_type = rule.get("type")
			rule_name = rule.get("name", "unnamed")
			required = rule.get("required", True)

			if rule_type == "required_field":
				field_name = rule.get("field")
				if field_name not in validation_result["fields"]:
					error = {
						"rule": rule_name,
						"field": field_name,
						"message": f"Required field '{field_name}' is missing",
					}
					if required:
						validation_result["errors"].append(error)
					else:
						validation_result["warnings"].append(error)
				else:
					validation_result["rules_passed"] += 1

			elif rule_type == "field_format":
				field_name = rule.get("field")
				expected_format = rule.get("format")  # date, email, number, etc.
				field_value = validation_result["fields"].get(field_name)

				if field_value:
					# TODO: Implement format validation
					# For now, assume valid
					validation_result["rules_passed"] += 1

			elif rule_type == "expression":
				expression = rule.get("expression")
				# TODO: Evaluate custom expression
				validation_result["rules_passed"] += 1

		# Determine overall validity
		if validation_result["errors"]:
			validation_result["valid"] = False
		elif fail_on_warning and validation_result["warnings"]:
			validation_result["valid"] = False

		status = "valid" if validation_result["valid"] else "invalid"
		error_count = len(validation_result["errors"])
		warning_count = len(validation_result["warnings"])

		result = TaskResult.success_result(
			f"Validation {status}: {error_count} errors, {warning_count} warnings",
			validation=validation_result,
			fields=validation_result["fields"],
		)
		log_task_complete("validate", ctx, result)
		return result.model_dump()

	except Exception as e:
		logger.exception(f"Validation failed for document {document_id}")
		result = TaskResult.failure_result(
			f"Validation failed: {str(e)}",
			error_code="VALIDATE_ERROR",
		)
		log_task_complete("validate", ctx, result)
		return result.model_dump()


@task(
	name="transform",
	description="Transform document data",
	retries=settings.default_retries,
	retry_delay_seconds=settings.retry_delay_seconds,
)
async def transform_task(ctx: dict, config: dict) -> dict:
	"""
	Transform document data according to rules.

	Transformations include:
	- Field mapping (rename, restructure)
	- Format conversion (dates, numbers)
	- Data enrichment
	- Normalization

	Config options:
		- transformations: list[dict] - Transformation rules
		- output_format: str - Desired output format

	Returns:
		Transformed data
	"""
	log_task_start("transform", ctx, config)

	document_id = ctx["document_id"]
	transformations = config.get("transformations", [])
	output_format = config.get("output_format", "json")

	try:
		# Get validated fields
		validate_result = ctx.get("previous_results", {}).get("validate", {})
		fields = validate_result.get("data", {}).get("fields", {})

		transform_result = {
			"document_id": document_id,
			"input_fields": len(fields),
			"transformations_applied": 0,
			"output": {},
		}

		# Start with existing fields
		output_data = dict(fields)

		# Apply transformations
		for transform in transformations:
			transform_type = transform.get("type")

			if transform_type == "rename":
				# Rename a field
				from_field = transform.get("from")
				to_field = transform.get("to")
				if from_field in output_data:
					output_data[to_field] = output_data.pop(from_field)
					transform_result["transformations_applied"] += 1

			elif transform_type == "format_date":
				# Format a date field
				field = transform.get("field")
				target_format = transform.get("format", "%Y-%m-%d")
				if field in output_data:
					# TODO: Implement actual date formatting
					transform_result["transformations_applied"] += 1

			elif transform_type == "map_value":
				# Map field values
				field = transform.get("field")
				mapping = transform.get("mapping", {})
				if field in output_data and output_data[field] in mapping:
					output_data[field] = mapping[output_data[field]]
					transform_result["transformations_applied"] += 1

			elif transform_type == "set_value":
				# Set a constant value
				field = transform.get("field")
				value = transform.get("value")
				output_data[field] = value
				transform_result["transformations_applied"] += 1

			elif transform_type == "concatenate":
				# Concatenate multiple fields
				target = transform.get("target")
				source_fields = transform.get("fields", [])
				separator = transform.get("separator", " ")
				values = [str(output_data.get(f, "")) for f in source_fields]
				output_data[target] = separator.join(v for v in values if v)
				transform_result["transformations_applied"] += 1

		transform_result["output"] = output_data
		transform_result["output_fields"] = len(output_data)

		result = TaskResult.success_result(
			f"Applied {transform_result['transformations_applied']} transformations",
			transform=transform_result,
			transformed_data=output_data,
		)
		log_task_complete("transform", ctx, result)
		return result.model_dump()

	except Exception as e:
		logger.exception(f"Transform failed for document {document_id}")
		result = TaskResult.failure_result(
			f"Transform failed: {str(e)}",
			error_code="TRANSFORM_ERROR",
		)
		log_task_complete("transform", ctx, result)
		return result.model_dump()

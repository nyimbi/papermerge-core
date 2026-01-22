# (c) Copyright Datacraft, 2026
"""
Safe expression evaluation for workflow conditions.

Uses simpleeval for secure expression evaluation without exposing
arbitrary Python code execution.
"""
import logging
import operator
import re
from typing import Any

from simpleeval import SimpleEval, DEFAULT_OPERATORS, DEFAULT_FUNCTIONS

logger = logging.getLogger(__name__)


# Custom operators available in expressions
CUSTOM_OPERATORS = {
	**DEFAULT_OPERATORS,
	# Add more operators as needed
}

# Safe functions available in expressions
SAFE_FUNCTIONS = {
	**DEFAULT_FUNCTIONS,
	# String functions
	"len": len,
	"str": str,
	"int": int,
	"float": float,
	"bool": bool,
	"lower": lambda s: s.lower() if isinstance(s, str) else s,
	"upper": lambda s: s.upper() if isinstance(s, str) else s,
	"strip": lambda s: s.strip() if isinstance(s, str) else s,
	"contains": lambda s, sub: sub in s if isinstance(s, (str, list, dict)) else False,
	"startswith": lambda s, prefix: s.startswith(prefix) if isinstance(s, str) else False,
	"endswith": lambda s, suffix: s.endswith(suffix) if isinstance(s, str) else False,

	# List functions
	"count": lambda lst: len(lst) if isinstance(lst, (list, tuple)) else 0,
	"any_of": lambda lst, values: any(v in values for v in lst) if isinstance(lst, list) else False,
	"all_of": lambda lst, values: all(v in values for v in lst) if isinstance(lst, list) else True,

	# Dict functions
	"get": lambda d, key, default=None: d.get(key, default) if isinstance(d, dict) else default,
	"has_key": lambda d, key: key in d if isinstance(d, dict) else False,

	# Math functions
	"abs": abs,
	"min": min,
	"max": max,
	"round": round,
	"sum": sum,

	# Type checks
	"is_none": lambda x: x is None,
	"is_empty": lambda x: not x if x is not None else True,
	"is_string": lambda x: isinstance(x, str),
	"is_number": lambda x: isinstance(x, (int, float)),
	"is_list": lambda x: isinstance(x, list),
	"is_dict": lambda x: isinstance(x, dict),
}


def evaluate_condition(expression: str, context: dict) -> bool:
	"""
	Safely evaluate a condition expression.

	Args:
		expression: The condition expression to evaluate
		context: Dictionary of variables available in the expression

	Returns:
		Boolean result of the expression evaluation

	Raises:
		ValueError: If expression is invalid or evaluation fails

	Examples:
		>>> evaluate_condition("classification.confidence > 0.8", {"classification": {"confidence": 0.85}})
		True

		>>> evaluate_condition("contains(entities, 'DATE')", {"entities": ["DATE", "ORG"]})
		True

		>>> evaluate_condition("page_count <= 10 and is_valid", {"page_count": 5, "is_valid": True})
		True
	"""
	if not expression or not expression.strip():
		return True  # Empty expression evaluates to True

	try:
		# Create evaluator with safe functions and operators
		evaluator = SimpleEval(
			operators=CUSTOM_OPERATORS,
			functions=SAFE_FUNCTIONS,
			names=_flatten_context(context),
		)

		# Evaluate the expression
		result = evaluator.eval(expression)

		# Coerce to boolean
		return bool(result)

	except Exception as e:
		logger.error(f"Expression evaluation failed: {expression!r} - {e}")
		raise ValueError(f"Invalid expression: {expression} - {str(e)}") from e


def evaluate_expression(expression: str, context: dict) -> Any:
	"""
	Evaluate an expression and return its value (not just boolean).

	Useful for dynamic routing or value extraction.

	Args:
		expression: The expression to evaluate
		context: Dictionary of variables available in the expression

	Returns:
		The result of the expression evaluation
	"""
	if not expression or not expression.strip():
		return None

	try:
		evaluator = SimpleEval(
			operators=CUSTOM_OPERATORS,
			functions=SAFE_FUNCTIONS,
			names=_flatten_context(context),
		)
		return evaluator.eval(expression)

	except Exception as e:
		logger.error(f"Expression evaluation failed: {expression!r} - {e}")
		raise ValueError(f"Invalid expression: {expression} - {str(e)}") from e


def _flatten_context(context: dict, prefix: str = "") -> dict:
	"""
	Flatten nested context into dot-notation accessible names.

	{"a": {"b": {"c": 1}}} -> {"a": {...}, "a_b": {...}, "a_b_c": 1}

	This allows expressions like:
		classification_confidence > 0.8
	Instead of:
		classification["confidence"] > 0.8
	"""
	flattened = {}

	for key, value in context.items():
		full_key = f"{prefix}_{key}" if prefix else key
		flattened[full_key] = value

		# Also add with original key for direct access
		if not prefix:
			flattened[key] = value

		# Recursively flatten nested dicts
		if isinstance(value, dict):
			nested = _flatten_context(value, full_key)
			flattened.update(nested)

	return flattened


def validate_expression(expression: str) -> tuple[bool, str | None]:
	"""
	Validate an expression without evaluating it.

	Args:
		expression: The expression to validate

	Returns:
		Tuple of (is_valid, error_message)
	"""
	if not expression or not expression.strip():
		return True, None

	try:
		# Try to evaluate with empty context to check syntax
		evaluator = SimpleEval(
			operators=CUSTOM_OPERATORS,
			functions=SAFE_FUNCTIONS,
			names={},
		)

		# Parse without evaluating to check syntax
		# This will catch syntax errors but not undefined names
		import ast
		ast.parse(expression, mode="eval")

		return True, None

	except SyntaxError as e:
		return False, f"Syntax error: {str(e)}"
	except Exception as e:
		return False, f"Validation error: {str(e)}"


def extract_variables(expression: str) -> set[str]:
	"""
	Extract variable names used in an expression.

	Useful for checking if all required context variables are available.

	Args:
		expression: The expression to analyze

	Returns:
		Set of variable names found in the expression
	"""
	if not expression:
		return set()

	try:
		import ast

		tree = ast.parse(expression, mode="eval")
		variables = set()

		for node in ast.walk(tree):
			if isinstance(node, ast.Name):
				variables.add(node.id)

		# Filter out function names
		variables -= set(SAFE_FUNCTIONS.keys())

		return variables

	except Exception as e:
		logger.warning(f"Could not extract variables from expression: {e}")
		return set()


# Pre-compiled patterns for common expressions
COMPARISON_PATTERN = re.compile(
	r"(\w+(?:\.\w+)*)\s*(==|!=|>=|<=|>|<)\s*(.+)"
)


def parse_simple_condition(expression: str) -> tuple[str, str, str] | None:
	"""
	Parse a simple comparison expression into components.

	Args:
		expression: Expression like "confidence >= 0.8"

	Returns:
		Tuple of (left_operand, operator, right_operand) or None if not simple
	"""
	match = COMPARISON_PATTERN.match(expression.strip())
	if match:
		return match.group(1), match.group(2), match.group(3).strip()
	return None


# Common condition templates for UI
CONDITION_TEMPLATES = {
	"confidence_threshold": {
		"template": "{field}_confidence >= {threshold}",
		"description": "Check if confidence score meets threshold",
		"parameters": ["field", "threshold"],
	},
	"document_type_is": {
		"template": "classification_assigned_type == '{type}'",
		"description": "Check if document is of specific type",
		"parameters": ["type"],
	},
	"has_entity": {
		"template": "any_of([e['label'] for e in nlp_entities], ['{entity}'])",
		"description": "Check if document contains specific entity type",
		"parameters": ["entity"],
	},
	"page_count_max": {
		"template": "source_document_page_count <= {max_pages}",
		"description": "Check if document has at most N pages",
		"parameters": ["max_pages"],
	},
	"validation_passed": {
		"template": "validate_validation_valid == True",
		"description": "Check if validation passed",
		"parameters": [],
	},
	"custom": {
		"template": "{expression}",
		"description": "Custom expression",
		"parameters": ["expression"],
	},
}


def build_condition_from_template(template_name: str, **params) -> str:
	"""
	Build a condition expression from a template.

	Args:
		template_name: Name of the template to use
		**params: Template parameters

	Returns:
		The formatted condition expression
	"""
	if template_name not in CONDITION_TEMPLATES:
		raise ValueError(f"Unknown condition template: {template_name}")

	template = CONDITION_TEMPLATES[template_name]["template"]
	return template.format(**params)

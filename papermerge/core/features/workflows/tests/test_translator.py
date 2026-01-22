# (c) Copyright Datacraft, 2026
"""Tests for workflow translator."""
import pytest
from papermerge.core.features.workflows.translator import (
	WorkflowTranslator,
	validate_workflow_graph,
)
from papermerge.core.features.workflows.expressions import (
	evaluate_condition,
	validate_expression,
	extract_variables,
)


class TestWorkflowTranslator:
	"""Tests for WorkflowTranslator."""

	def test_topological_sort_linear(self):
		"""Test topological sort with linear workflow."""
		nodes = [
			{"id": "1", "type": "source", "data": {}},
			{"id": "2", "type": "ocr", "data": {}},
			{"id": "3", "type": "store", "data": {}},
		]
		edges = [
			{"source": "1", "target": "2"},
			{"source": "2", "target": "3"},
		]

		translator = WorkflowTranslator("test", "Test", nodes, edges)
		order = translator._topological_sort()

		assert order.index("1") < order.index("2")
		assert order.index("2") < order.index("3")

	def test_topological_sort_branching(self):
		"""Test topological sort with branching workflow."""
		nodes = [
			{"id": "1", "type": "source", "data": {}},
			{"id": "2", "type": "split", "data": {}},
			{"id": "3", "type": "ocr", "data": {}},
			{"id": "4", "type": "nlp", "data": {}},
			{"id": "5", "type": "merge", "data": {}},
		]
		edges = [
			{"source": "1", "target": "2"},
			{"source": "2", "target": "3"},
			{"source": "2", "target": "4"},
			{"source": "3", "target": "5"},
			{"source": "4", "target": "5"},
		]

		translator = WorkflowTranslator("test", "Test", nodes, edges)
		order = translator._topological_sort()

		assert order.index("1") < order.index("2")
		assert order.index("2") < order.index("3")
		assert order.index("2") < order.index("4")
		assert order.index("3") < order.index("5")
		assert order.index("4") < order.index("5")

	def test_find_start_nodes(self):
		"""Test finding start nodes."""
		nodes = [{"id": "1"}, {"id": "2"}, {"id": "3"}]
		edges = [{"source": "1", "target": "2"}, {"source": "2", "target": "3"}]

		translator = WorkflowTranslator("test", "Test", nodes, edges)
		assert translator._find_start_nodes() == ["1"]

	def test_find_end_nodes(self):
		"""Test finding end nodes."""
		nodes = [{"id": "1"}, {"id": "2"}, {"id": "3"}]
		edges = [{"source": "1", "target": "2"}, {"source": "2", "target": "3"}]

		translator = WorkflowTranslator("test", "Test", nodes, edges)
		assert translator._find_end_nodes() == ["3"]


class TestValidateWorkflowGraph:
	"""Tests for workflow graph validation."""

	def test_valid_linear_workflow(self):
		"""Test validation of valid linear workflow."""
		nodes = [
			{"id": "1", "type": "source", "data": {}},
			{"id": "2", "type": "ocr", "data": {}},
		]
		edges = [{"source": "1", "target": "2"}]

		is_valid, errors = validate_workflow_graph(nodes, edges)
		assert is_valid
		assert len(errors) == 0

	def test_empty_workflow(self):
		"""Test validation of empty workflow."""
		is_valid, errors = validate_workflow_graph([], [])
		assert not is_valid
		assert "no nodes" in errors[0].lower()

	def test_disconnected_nodes(self):
		"""Test detection of disconnected nodes."""
		nodes = [{"id": "1", "type": "source"}, {"id": "2", "type": "ocr"}, {"id": "3", "type": "store"}]
		edges = [{"source": "1", "target": "2"}]  # Node 3 disconnected

		is_valid, errors = validate_workflow_graph(nodes, edges)
		assert not is_valid
		assert any("disconnected" in e.lower() for e in errors)


class TestExpressions:
	"""Tests for expression evaluation."""

	def test_simple_comparison(self):
		"""Test simple comparison expressions."""
		assert evaluate_condition("x > 5", {"x": 10})
		assert not evaluate_condition("x > 5", {"x": 3})
		assert evaluate_condition("name == 'test'", {"name": "test"})

	def test_nested_context(self):
		"""Test expressions with nested context."""
		ctx = {"classification": {"confidence": 0.85}}
		assert evaluate_condition("classification_confidence > 0.8", ctx)

	def test_functions_in_expressions(self):
		"""Test built-in functions."""
		assert evaluate_condition("len(items) > 2", {"items": [1, 2, 3]})
		assert evaluate_condition("contains(text, 'hello')", {"text": "hello world"})
		assert evaluate_condition("is_empty(value)", {"value": ""})

	def test_validate_expression(self):
		"""Test expression validation."""
		is_valid, error = validate_expression("x > 5")
		assert is_valid

		is_valid, error = validate_expression("x >>>> 5")
		assert not is_valid

	def test_extract_variables(self):
		"""Test variable extraction."""
		variables = extract_variables("x > 5 and y < 10")
		assert "x" in variables
		assert "y" in variables

# (c) Copyright Datacraft, 2026
"""Pytest fixtures for workflow tests."""
import pytest


@pytest.fixture
def sample_linear_workflow():
	"""Sample linear workflow definition."""
	return {
		"nodes": [
			{"id": "n1", "type": "source", "data": {"label": "Source", "config": {}}},
			{"id": "n2", "type": "ocr", "data": {"label": "OCR", "config": {"engine": "tesseract"}}},
			{"id": "n3", "type": "classify", "data": {"label": "Classify", "config": {}}},
			{"id": "n4", "type": "store", "data": {"label": "Store", "config": {}}},
		],
		"edges": [
			{"source": "n1", "target": "n2"},
			{"source": "n2", "target": "n3"},
			{"source": "n3", "target": "n4"},
		],
	}


@pytest.fixture
def sample_branching_workflow():
	"""Sample workflow with parallel branches."""
	return {
		"nodes": [
			{"id": "n1", "type": "source", "data": {}},
			{"id": "n2", "type": "split", "data": {"config": {"branches": ["ocr", "nlp"]}}},
			{"id": "n3", "type": "ocr", "data": {}},
			{"id": "n4", "type": "nlp", "data": {}},
			{"id": "n5", "type": "merge", "data": {}},
			{"id": "n6", "type": "store", "data": {}},
		],
		"edges": [
			{"source": "n1", "target": "n2"},
			{"source": "n2", "target": "n3"},
			{"source": "n2", "target": "n4"},
			{"source": "n3", "target": "n5"},
			{"source": "n4", "target": "n5"},
			{"source": "n5", "target": "n6"},
		],
	}


@pytest.fixture
def sample_conditional_workflow():
	"""Sample workflow with condition node."""
	return {
		"nodes": [
			{"id": "n1", "type": "source", "data": {}},
			{"id": "n2", "type": "classify", "data": {}},
			{"id": "n3", "type": "condition", "data": {
				"config": {
					"expression": "classification_confidence >= 0.8",
					"true_branch": "auto",
					"false_branch": "manual",
				}
			}},
			{"id": "n4", "type": "store", "data": {}},
			{"id": "n5", "type": "approval", "data": {}},
		],
		"edges": [
			{"source": "n1", "target": "n2"},
			{"source": "n2", "target": "n3"},
			{"source": "n3", "target": "n4", "sourceHandle": "auto"},
			{"source": "n3", "target": "n5", "sourceHandle": "manual"},
		],
	}


@pytest.fixture
def sample_task_context():
	"""Sample task execution context."""
	return {
		"workflow_id": "wf-123",
		"instance_id": "inst-456",
		"step_id": "step-789",
		"execution_id": "exec-abc",
		"document_id": "doc-xyz",
		"tenant_id": "tenant-001",
		"initiated_by": "user-001",
		"previous_results": {},
	}

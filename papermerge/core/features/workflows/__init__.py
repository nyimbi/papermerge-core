# (c) Copyright Datacraft, 2026
"""Workflow management with Prefect integration."""
import logging

logger = logging.getLogger(__name__)

# Make Prefect-related imports optional
try:
	from .prefect_engine import PrefectWorkflowEngine
	from .translator import WorkflowTranslator, translate_workflow, validate_workflow_graph
	from .expressions import evaluate_condition, evaluate_expression
	from .state_sync import StateSyncService
	from .tasks import TASK_REGISTRY, get_task, list_available_tasks
	from .inputs import INPUT_MODEL_REGISTRY, get_input_model

	__all__ = [
		"PrefectWorkflowEngine",
		"WorkflowTranslator",
		"translate_workflow",
		"validate_workflow_graph",
		"evaluate_condition",
		"evaluate_expression",
		"StateSyncService",
		"TASK_REGISTRY",
		"get_task",
		"list_available_tasks",
		"INPUT_MODEL_REGISTRY",
		"get_input_model",
	]
except ImportError as e:
	logger.debug(f"Prefect workflow features not available: {e}")
	# Provide stub implementations
	PrefectWorkflowEngine = None
	WorkflowTranslator = None
	translate_workflow = None
	validate_workflow_graph = None
	evaluate_condition = None
	evaluate_expression = None
	StateSyncService = None
	TASK_REGISTRY = {}
	get_task = lambda x: None
	list_available_tasks = lambda: []
	INPUT_MODEL_REGISTRY = {}
	get_input_model = lambda x: None
	__all__ = []

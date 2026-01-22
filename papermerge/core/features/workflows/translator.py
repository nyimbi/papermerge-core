# (c) Copyright Datacraft, 2026
"""
Workflow translator: converts React Flow graphs to Prefect flows.

This module handles the translation of visual workflow definitions
(stored as React Flow nodes and edges) into executable Prefect flows.
"""
import logging
from collections import defaultdict
from typing import Any, Callable
from uuid import UUID

from prefect import flow, task, unmapped
from prefect.futures import PrefectFuture

from .tasks import TASK_REGISTRY, get_task
from .expressions import evaluate_condition

logger = logging.getLogger(__name__)


class WorkflowTranslator:
	"""
	Translates React Flow workflow definitions into executable Prefect flows.

	The translator handles:
	- Linear workflows (sequential task execution)
	- Parallel branches (split/merge nodes)
	- Conditional routing (condition nodes)
	- Human-in-the-loop (approval nodes)
	"""

	def __init__(
		self,
		workflow_id: str,
		workflow_name: str,
		nodes: list[dict],
		edges: list[dict],
	):
		"""
		Initialize the translator.

		Args:
			workflow_id: UUID of the workflow definition
			workflow_name: Human-readable workflow name
			nodes: List of React Flow node objects
			edges: List of React Flow edge objects
		"""
		self.workflow_id = workflow_id
		self.workflow_name = workflow_name
		self.nodes = {node["id"]: node for node in nodes}
		self.edges = edges
		self.adjacency = self._build_adjacency()
		self.reverse_adjacency = self._build_reverse_adjacency()

	def _build_adjacency(self) -> dict[str, list[str]]:
		"""Build forward adjacency list from edges."""
		adj = defaultdict(list)
		for edge in self.edges:
			source = edge["source"]
			target = edge["target"]
			adj[source].append(target)
		return dict(adj)

	def _build_reverse_adjacency(self) -> dict[str, list[str]]:
		"""Build reverse adjacency list (for finding predecessors)."""
		adj = defaultdict(list)
		for edge in self.edges:
			source = edge["source"]
			target = edge["target"]
			adj[target].append(source)
		return dict(adj)

	def _get_edge_label(self, source: str, target: str) -> str | None:
		"""Get the label/handle ID of an edge (for conditional routing)."""
		for edge in self.edges:
			if edge["source"] == source and edge["target"] == target:
				return edge.get("sourceHandle") or edge.get("label")
		return None

	def _find_start_nodes(self) -> list[str]:
		"""Find nodes with no incoming edges (start nodes)."""
		all_nodes = set(self.nodes.keys())
		nodes_with_incoming = set()
		for edge in self.edges:
			nodes_with_incoming.add(edge["target"])
		return list(all_nodes - nodes_with_incoming)

	def _find_end_nodes(self) -> list[str]:
		"""Find nodes with no outgoing edges (end nodes)."""
		all_nodes = set(self.nodes.keys())
		nodes_with_outgoing = set()
		for edge in self.edges:
			nodes_with_outgoing.add(edge["source"])
		return list(all_nodes - nodes_with_outgoing)

	def _topological_sort(self) -> list[str]:
		"""
		Sort nodes in topological order.

		Returns nodes in an order where all dependencies are satisfied.
		Handles cycles by detecting and raising an error.
		"""
		in_degree = defaultdict(int)
		for node_id in self.nodes:
			in_degree[node_id] = 0

		for edge in self.edges:
			in_degree[edge["target"]] += 1

		# Start with nodes that have no incoming edges
		queue = [node_id for node_id, degree in in_degree.items() if degree == 0]
		result = []

		while queue:
			node_id = queue.pop(0)
			result.append(node_id)

			for successor in self.adjacency.get(node_id, []):
				in_degree[successor] -= 1
				if in_degree[successor] == 0:
					queue.append(successor)

		if len(result) != len(self.nodes):
			raise ValueError("Workflow contains a cycle - cannot execute")

		return result

	def _find_parallel_branches(self, split_node_id: str) -> list[list[str]]:
		"""
		Identify nodes in each parallel branch after a split node.

		Returns a list of branches, where each branch is a list of node IDs.
		"""
		branches = []
		successors = self.adjacency.get(split_node_id, [])

		for successor in successors:
			branch = self._collect_branch_nodes(successor, split_node_id)
			branches.append(branch)

		return branches

	def _collect_branch_nodes(
		self,
		start_node: str,
		split_node: str,
	) -> list[str]:
		"""
		Collect all nodes in a branch until reaching a merge node.
		"""
		branch = []
		visited = set()
		queue = [start_node]

		while queue:
			node_id = queue.pop(0)
			if node_id in visited:
				continue

			visited.add(node_id)
			node = self.nodes.get(node_id, {})
			node_type = node.get("type", node.get("data", {}).get("type", ""))

			# Stop at merge nodes
			if node_type == "merge":
				continue

			branch.append(node_id)

			# Continue to successors
			for successor in self.adjacency.get(node_id, []):
				if successor not in visited:
					queue.append(successor)

		return branch

	def _find_merge_node(self, split_node_id: str) -> str | None:
		"""Find the merge node that corresponds to a split node."""
		# BFS to find merge node
		visited = set()
		queue = list(self.adjacency.get(split_node_id, []))

		while queue:
			node_id = queue.pop(0)
			if node_id in visited:
				continue

			visited.add(node_id)
			node = self.nodes.get(node_id, {})
			node_type = node.get("type", node.get("data", {}).get("type", ""))

			if node_type == "merge":
				return node_id

			for successor in self.adjacency.get(node_id, []):
				queue.append(successor)

		return None

	def build_flow(self) -> Callable:
		"""
		Generate an executable Prefect flow from the workflow definition.

		Returns:
			A Prefect flow function that can be executed
		"""
		workflow_id = self.workflow_id
		workflow_name = self.workflow_name
		nodes = self.nodes
		adjacency = self.adjacency
		translator = self

		@flow(name=f"workflow_{workflow_id}", description=workflow_name)
		async def dynamic_workflow(
			document_id: str,
			instance_id: str,
			tenant_id: str,
			initiated_by: str | None = None,
			initial_context: dict | None = None,
		) -> dict:
			"""
			Dynamically generated Prefect flow for workflow execution.

			Args:
				document_id: ID of the document being processed
				instance_id: ID of the workflow instance
				tenant_id: Tenant ID for multi-tenant context
				initiated_by: User ID who initiated the workflow
				initial_context: Additional context data

			Returns:
				Dictionary of results from all executed tasks
			"""
			from prefect.runtime import flow_run

			# Build execution context
			context = {
				"workflow_id": workflow_id,
				"instance_id": instance_id,
				"document_id": document_id,
				"tenant_id": tenant_id,
				"initiated_by": initiated_by,
				"prefect_flow_run_id": str(flow_run.id) if flow_run else None,
				"previous_results": {},
				**(initial_context or {}),
			}

			results = {}
			execution_order = translator._topological_sort()

			for node_id in execution_order:
				node = nodes.get(node_id)
				if not node:
					continue

				# Extract node type and config
				node_data = node.get("data", {})
				node_type = node.get("type") or node_data.get("type", "unknown")
				node_config = node_data.get("config", {})
				node_label = node_data.get("label", node_type)

				# Skip special nodes handled differently
				if node_type in ("start", "end"):
					continue

				# Update context with step info
				step_context = {
					**context,
					"step_id": node_id,
					"execution_id": f"{instance_id}_{node_id}",
				}

				# Get the task function
				task_fn = get_task(node_type)
				if not task_fn:
					logger.warning(f"No task found for type: {node_type}")
					results[node_id] = {
						"success": False,
						"error": f"Unknown task type: {node_type}",
					}
					continue

				# Handle special node types
				if node_type == "condition":
					# Evaluate condition and determine branch
					result = await task_fn(step_context, node_config)
					results[node_id] = result

					# Route based on condition result
					next_branch = result.get("data", {}).get("next_branch")
					if next_branch:
						context["active_branch"] = next_branch

				elif node_type == "split":
					# Execute split and mark branch starts
					result = await task_fn(step_context, node_config)
					results[node_id] = result

					# Get branches to execute
					branches = result.get("data", {}).get("branches", [])
					context["active_branches"] = branches

				elif node_type == "merge":
					# Collect results from all branches
					branch_results = {}
					predecessors = translator.reverse_adjacency.get(node_id, [])
					for pred_id in predecessors:
						if pred_id in results:
							branch_results[pred_id] = results[pred_id]

					step_context["branch_results"] = branch_results
					result = await task_fn(step_context, node_config)
					results[node_id] = result

				elif node_type == "route":
					# Route based on document properties
					result = await task_fn(step_context, node_config)
					results[node_id] = result

					next_branch = result.get("data", {}).get("next_branch")
					if next_branch:
						context["active_branch"] = next_branch

				else:
					# Standard task execution
					try:
						result = await task_fn(step_context, node_config)
						results[node_id] = result

						# Store result for downstream tasks
						if result.get("success", False):
							context["previous_results"][node_type] = result

					except Exception as e:
						logger.exception(f"Task {node_type} failed for node {node_id}")
						results[node_id] = {
							"success": False,
							"error": str(e),
						}
						# Optionally halt execution on failure
						if node_config.get("halt_on_failure", True):
							break

			return {
				"workflow_id": workflow_id,
				"instance_id": instance_id,
				"document_id": document_id,
				"results": results,
				"completed": True,
			}

		return dynamic_workflow


def translate_workflow(
	workflow_id: str,
	workflow_name: str,
	nodes: list[dict],
	edges: list[dict],
) -> Callable:
	"""
	Convenience function to translate a workflow.

	Args:
		workflow_id: UUID of the workflow
		workflow_name: Name of the workflow
		nodes: React Flow nodes
		edges: React Flow edges

	Returns:
		Executable Prefect flow function
	"""
	translator = WorkflowTranslator(
		workflow_id=workflow_id,
		workflow_name=workflow_name,
		nodes=nodes,
		edges=edges,
	)
	return translator.build_flow()


def validate_workflow_graph(
	nodes: list[dict],
	edges: list[dict],
) -> tuple[bool, list[str]]:
	"""
	Validate a workflow graph for correctness.

	Checks:
	- At least one start node
	- At least one end node
	- No cycles
	- All nodes are connected
	- Valid node types
	- Split/merge pairs match

	Args:
		nodes: React Flow nodes
		edges: React Flow edges

	Returns:
		Tuple of (is_valid, list of error messages)
	"""
	errors = []

	if not nodes:
		errors.append("Workflow has no nodes")
		return False, errors

	# Build node map
	node_map = {node["id"]: node for node in nodes}

	# Check for start/end nodes
	nodes_with_incoming = {edge["target"] for edge in edges}
	nodes_with_outgoing = {edge["source"] for edge in edges}
	all_node_ids = set(node_map.keys())

	start_nodes = all_node_ids - nodes_with_incoming
	end_nodes = all_node_ids - nodes_with_outgoing

	if not start_nodes:
		errors.append("Workflow has no start node (no node without incoming edges)")

	if not end_nodes:
		errors.append("Workflow has no end node (no node without outgoing edges)")

	# Check for valid node types
	for node in nodes:
		node_data = node.get("data", {})
		node_type = node.get("type") or node_data.get("type")

		if not node_type:
			errors.append(f"Node {node['id']} has no type specified")
		elif node_type not in TASK_REGISTRY and node_type not in ("start", "end"):
			errors.append(f"Node {node['id']} has unknown type: {node_type}")

	# Check for cycles using topological sort
	try:
		translator = WorkflowTranslator(
			workflow_id="validation",
			workflow_name="Validation",
			nodes=nodes,
			edges=edges,
		)
		translator._topological_sort()
	except ValueError as e:
		errors.append(str(e))

	# Check for disconnected nodes
	connected = set()
	if start_nodes:
		queue = list(start_nodes)
		while queue:
			node_id = queue.pop(0)
			if node_id in connected:
				continue
			connected.add(node_id)
			for edge in edges:
				if edge["source"] == node_id:
					queue.append(edge["target"])

	disconnected = all_node_ids - connected
	if disconnected:
		errors.append(f"Disconnected nodes found: {disconnected}")

	# Check split/merge pairing
	split_nodes = [
		node["id"] for node in nodes
		if (node.get("type") or node.get("data", {}).get("type")) == "split"
	]
	merge_nodes = [
		node["id"] for node in nodes
		if (node.get("type") or node.get("data", {}).get("type")) == "merge"
	]

	if len(split_nodes) != len(merge_nodes):
		errors.append(
			f"Mismatched split/merge nodes: {len(split_nodes)} splits, {len(merge_nodes)} merges"
		)

	return len(errors) == 0, errors

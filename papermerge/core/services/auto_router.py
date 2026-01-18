# (c) Copyright Datacraft, 2026
"""Auto-routing service for document processing."""
import logging
import re
from uuid import UUID
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from papermerge.core.features.routing.db.orm import RoutingRule, RoutingLog

logger = logging.getLogger(__name__)


class RoutingResult:
	"""Result of routing decision."""

	def __init__(
		self,
		routed: bool,
		destination_type: str | None = None,
		destination_id: UUID | None = None,
		rule_id: UUID | None = None,
		workflow_instance_id: UUID | None = None,
		message: str | None = None,
	):
		self.routed = routed
		self.destination_type = destination_type
		self.destination_id = destination_id
		self.rule_id = rule_id
		self.workflow_instance_id = workflow_instance_id
		self.message = message


class AutoRouterService:
	"""Route documents based on metadata and rules."""

	def __init__(self, db: Session):
		self.db = db

	async def route_document(
		self,
		document_id: UUID,
		tenant_id: UUID,
		mode: str = "operational",
		document_data: dict | None = None,
	) -> RoutingResult:
		"""Route a document based on matching rules."""
		if document_data is None:
			document_data = await self._get_document_data(document_id)

		# Get applicable rules ordered by priority
		stmt = select(RoutingRule).where(
			and_(
				RoutingRule.tenant_id == tenant_id,
				RoutingRule.is_active == True,
				RoutingRule.mode.in_([mode, "both"]),
			)
		).order_by(RoutingRule.priority)

		rules = list(self.db.scalars(stmt))

		for rule in rules:
			if self._matches_conditions(document_data, rule.conditions):
				result = await self._apply_rule(document_id, tenant_id, rule)
				await self._log_routing(
					tenant_id, document_id, rule.id, True,
					result.destination_type, result.destination_id, mode, rule.conditions
				)
				return result

		# No matching rule
		await self._log_routing(
			tenant_id, document_id, None, False, None, None, mode, None
		)
		return RoutingResult(routed=False, message="No matching routing rule found")

	def _matches_conditions(
		self,
		document_data: dict,
		conditions: dict,
	) -> bool:
		"""Check if document matches rule conditions."""
		for field, expected in conditions.items():
			actual = self._get_field_value(document_data, field)

			if isinstance(expected, dict):
				# Complex conditions: $gt, $lt, $in, $contains, $regex
				if not self._evaluate_complex(actual, expected):
					return False
			else:
				# Simple equality
				if actual != expected:
					return False

		return True

	def _get_field_value(self, data: dict, field_path: str) -> Any:
		"""Get nested field value using dot notation."""
		parts = field_path.split(".")
		value = data

		for part in parts:
			if isinstance(value, dict) and part in value:
				value = value[part]
			else:
				return None

		return value

	def _evaluate_complex(self, actual: Any, condition: dict) -> bool:
		"""Evaluate complex condition operators."""
		for op, expected in condition.items():
			if op == "$gt":
				if actual is None or actual <= expected:
					return False
			elif op == "$gte":
				if actual is None or actual < expected:
					return False
			elif op == "$lt":
				if actual is None or actual >= expected:
					return False
			elif op == "$lte":
				if actual is None or actual > expected:
					return False
			elif op == "$eq":
				if actual != expected:
					return False
			elif op == "$ne":
				if actual == expected:
					return False
			elif op == "$in":
				if actual not in expected:
					return False
			elif op == "$nin":
				if actual in expected:
					return False
			elif op == "$contains":
				if actual is None or expected not in str(actual):
					return False
			elif op == "$regex":
				if actual is None or not re.search(expected, str(actual)):
					return False
			elif op == "$exists":
				if expected and actual is None:
					return False
				if not expected and actual is not None:
					return False

		return True

	async def _apply_rule(
		self,
		document_id: UUID,
		tenant_id: UUID,
		rule: RoutingRule,
	) -> RoutingResult:
		"""Apply routing rule to document."""
		logger.info(f"Applying routing rule {rule.id} to document {document_id}")

		if rule.destination_type == "folder":
			await self._move_to_folder(document_id, rule.destination_id)
			return RoutingResult(
				routed=True,
				destination_type="folder",
				destination_id=rule.destination_id,
				rule_id=rule.id,
			)

		elif rule.destination_type == "workflow":
			from .workflow_engine import WorkflowEngine
			engine = WorkflowEngine(self.db)
			instance = await engine.start_workflow(
				rule.destination_id,
				document_id,
			)
			return RoutingResult(
				routed=True,
				destination_type="workflow",
				destination_id=rule.destination_id,
				rule_id=rule.id,
				workflow_instance_id=instance.id,
			)

		elif rule.destination_type == "user_inbox":
			await self._route_to_inbox(document_id, rule.destination_id)
			return RoutingResult(
				routed=True,
				destination_type="user_inbox",
				destination_id=rule.destination_id,
				rule_id=rule.id,
			)

		return RoutingResult(routed=False, message=f"Unknown destination type: {rule.destination_type}")

	async def _move_to_folder(self, document_id: UUID, folder_id: UUID) -> None:
		"""Move document to folder."""
		from papermerge.core.features.nodes.db.orm import Node
		node = self.db.get(Node, document_id)
		if node:
			node.parent_id = folder_id
			self.db.commit()

	async def _route_to_inbox(self, document_id: UUID, user_id: UUID) -> None:
		"""Route document to user's inbox."""
		from papermerge.core.features.users.db.orm import User
		user = self.db.get(User, user_id)
		if user and user.inbox_folder_id:
			await self._move_to_folder(document_id, user.inbox_folder_id)

	async def _get_document_data(self, document_id: UUID) -> dict:
		"""Get document data for routing evaluation."""
		from papermerge.core.features.document.db.orm import Document
		from papermerge.core.features.custom_fields.db.orm import CustomFieldValue

		doc = self.db.get(Document, document_id)
		if not doc:
			return {}

		data = {
			"id": str(doc.id),
			"title": doc.title,
			"ctype": doc.ctype,
			"lang": doc.lang,
			"metadata": {},
		}

		# Get custom field values
		stmt = select(CustomFieldValue).where(
			CustomFieldValue.document_id == document_id
		)
		for cfv in self.db.scalars(stmt):
			data["metadata"][cfv.custom_field.name] = cfv.value

		return data

	async def _log_routing(
		self,
		tenant_id: UUID,
		document_id: UUID,
		rule_id: UUID | None,
		matched: bool,
		destination_type: str | None,
		destination_id: UUID | None,
		mode: str,
		conditions: dict | None,
	) -> None:
		"""Log routing decision."""
		log = RoutingLog(
			tenant_id=tenant_id,
			document_id=document_id,
			rule_id=rule_id,
			matched=matched,
			destination_type=destination_type,
			destination_id=destination_id,
			mode=mode,
			evaluated_conditions=conditions,
		)
		self.db.add(log)
		self.db.commit()

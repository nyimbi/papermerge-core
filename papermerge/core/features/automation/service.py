# (c) Copyright Datacraft, 2026
"""Business logic for the workflow automation rules engine."""
import json
import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.utils.tz import utc_now
from .db.orm import AutomationRule

_log = logging.getLogger(__name__)


def _uuid7str() -> str:
	from uuid6 import uuid7
	return str(uuid7())


# ── Condition evaluation ───────────────────────────────────────────────────────

def evaluate_condition(condition: dict, document_data: dict) -> bool:
	"""Evaluate a single condition dict against a flat document_data dict.

	condition keys: field, operator, value
	Supported operators: equals, not_equals, contains, greater_than, less_than
	"""
	field: str = condition.get("field", "")
	operator: str = condition.get("operator", "equals")
	expected = condition.get("value")

	actual = document_data.get(field)

	if actual is None:
		# Field absent — only not_equals can be True
		return operator == "not_equals"

	try:
		match operator:
			case "equals":
				return str(actual).lower() == str(expected).lower()
			case "not_equals":
				return str(actual).lower() != str(expected).lower()
			case "contains":
				# Works for strings and lists
				if isinstance(actual, list):
					return str(expected).lower() in [str(v).lower() for v in actual]
				return str(expected).lower() in str(actual).lower()
			case "greater_than":
				return float(actual) > float(expected)
			case "less_than":
				return float(actual) < float(expected)
			case _:
				_log.warning("Unknown operator %r in condition — treating as False", operator)
				return False
	except (ValueError, TypeError) as exc:
		_log.warning("Condition eval error for field=%r op=%r: %s", field, operator, exc)
		return False


# ── Action execution ───────────────────────────────────────────────────────────

async def execute_action(
	action: dict,
	document_id: str,
	tenant_id: str,
	session: AsyncSession,
	dry_run: bool = False,
) -> dict:
	"""Dispatch a single action dict.

	Returns a result dict describing what happened (or would happen).
	"""
	action_type: str = action.get("type", "")
	params: dict = action.get("params", {})

	_log.debug("execute_action type=%r doc=%s dry_run=%s", action_type, document_id, dry_run)

	match action_type:
		case "notify_user":
			return await _action_notify_user(document_id, params, session, dry_run)
		case "route_to_folder":
			return await _action_route_to_folder(document_id, params, session, dry_run)
		case "apply_tag":
			return await _action_apply_tag(document_id, params, session, dry_run)
		case "assign_approval_workflow":
			return await _action_assign_approval_workflow(document_id, tenant_id, params, session, dry_run)
		case "set_document_type":
			return await _action_set_document_type(document_id, params, session, dry_run)
		case "send_webhook":
			return {"type": action_type, "status": "skipped", "reason": "webhook dispatch handled externally"}
		case _:
			_log.warning("Unknown action type %r — skipping", action_type)
			return {"type": action_type, "status": "skipped", "reason": f"unknown action type {action_type!r}"}


async def _action_notify_user(
	document_id: str,
	params: dict,
	session: AsyncSession,
	dry_run: bool,
) -> dict:
	user_id_str: str | None = params.get("user_id")
	message: str = params.get("message", f"Automation rule triggered for document {document_id}")
	title: str = params.get("title", "Automation Notification")

	if dry_run:
		return {"type": "notify_user", "status": "dry_run", "user_id": user_id_str, "message": message}

	if not user_id_str:
		return {"type": "notify_user", "status": "skipped", "reason": "no user_id in params"}

	try:
		user_uuid = UUID(user_id_str)
	except ValueError:
		return {"type": "notify_user", "status": "error", "reason": f"invalid user_id {user_id_str!r}"}

	from papermerge.core.features.notifications.db.orm import Notification
	notification = Notification(
		id=_uuid7str(),
		user_id=user_uuid,
		type="automation",
		title=title,
		message=message,
		link=f"/documents/{document_id}",
	)
	session.add(notification)
	_log.info("notify_user: queued notification for user %s doc %s", user_id_str, document_id)
	return {"type": "notify_user", "status": "ok", "user_id": user_id_str}


async def _action_route_to_folder(
	document_id: str,
	params: dict,
	session: AsyncSession,
	dry_run: bool,
) -> dict:
	folder_id: str | None = params.get("folder_id")
	if not folder_id:
		return {"type": "route_to_folder", "status": "skipped", "reason": "no folder_id in params"}

	if dry_run:
		return {"type": "route_to_folder", "status": "dry_run", "folder_id": folder_id}

	from sqlalchemy import text
	await session.execute(
		text("UPDATE nodes SET parent_id = :folder_id WHERE id = :doc_id"),
		{"folder_id": folder_id, "doc_id": document_id},
	)
	_log.info("route_to_folder: moved doc %s -> folder %s", document_id, folder_id)
	return {"type": "route_to_folder", "status": "ok", "folder_id": folder_id}


async def _action_apply_tag(
	document_id: str,
	params: dict,
	session: AsyncSession,
	dry_run: bool,
) -> dict:
	tag_id: str | None = params.get("tag_id")
	if not tag_id:
		return {"type": "apply_tag", "status": "skipped", "reason": "no tag_id in params"}

	if dry_run:
		return {"type": "apply_tag", "status": "dry_run", "tag_id": tag_id}

	from sqlalchemy import text
	# documents_tags is the standard association table
	await session.execute(
		text(
			"INSERT INTO documents_tags (document_id, tag_id) VALUES (:doc_id, :tag_id) "
			"ON CONFLICT DO NOTHING"
		),
		{"doc_id": document_id, "tag_id": tag_id},
	)
	_log.info("apply_tag: tagged doc %s with tag %s", document_id, tag_id)
	return {"type": "apply_tag", "status": "ok", "tag_id": tag_id}


async def _action_assign_approval_workflow(
	document_id: str,
	tenant_id: str,
	params: dict,
	session: AsyncSession,
	dry_run: bool,
) -> dict:
	workflow_name: str = params.get("workflow_name", "Auto-assigned review")
	steps_raw: list = params.get("steps", [])

	if dry_run:
		return {
			"type": "assign_approval_workflow",
			"status": "dry_run",
			"workflow_name": workflow_name,
			"steps": steps_raw,
		}

	try:
		from papermerge.core.features.approvals.db.orm import ApprovalStep, ApprovalWorkflow
		wf = ApprovalWorkflow(
			id=_uuid7str(),
			document_id=document_id,
			name=workflow_name,
			status="in_review",
			created_by_id="automation",
			tenant_id=tenant_id,
		)
		session.add(wf)
		await session.flush()

		for order, step_data in enumerate(steps_raw, start=1):
			step = ApprovalStep(
				id=_uuid7str(),
				workflow_id=wf.id,
				step_order=order,
				approver_email=step_data.get("approver_email", ""),
				approver_user_id=step_data.get("approver_user_id"),
				status="pending",
			)
			session.add(step)

		_log.info("assign_approval_workflow: created workflow %s for doc %s", wf.id, document_id)
		return {"type": "assign_approval_workflow", "status": "ok", "workflow_id": wf.id}
	except Exception as exc:
		_log.exception("assign_approval_workflow failed for doc %s: %s", document_id, exc)
		return {"type": "assign_approval_workflow", "status": "error", "reason": str(exc)}


async def _action_set_document_type(
	document_id: str,
	params: dict,
	session: AsyncSession,
	dry_run: bool,
) -> dict:
	document_type_id: str | None = params.get("document_type_id")
	if not document_type_id:
		return {"type": "set_document_type", "status": "skipped", "reason": "no document_type_id in params"}

	if dry_run:
		return {"type": "set_document_type", "status": "dry_run", "document_type_id": document_type_id}

	from sqlalchemy import text
	await session.execute(
		text("UPDATE documents SET document_type_id = :dt_id WHERE basetreenode_ptr_id = :doc_id"),
		{"dt_id": document_type_id, "doc_id": document_id},
	)
	_log.info("set_document_type: doc %s -> type %s", document_id, document_type_id)
	return {"type": "set_document_type", "status": "ok", "document_type_id": document_type_id}


# ── Rule evaluation ────────────────────────────────────────────────────────────

async def evaluate_rules(
	event: str,
	document_id: str,
	document_data: dict,
	tenant_id: str,
	session: AsyncSession,
	dry_run: bool = False,
) -> list[dict]:
	"""Evaluate all active rules for the given event and tenant.

	Returns a list of result dicts — one per rule that had all conditions pass.
	When dry_run=True, conditions are still evaluated but actions are not executed.
	"""
	stmt = (
		select(AutomationRule)
		.where(
			AutomationRule.trigger_event == event,
			AutomationRule.tenant_id == tenant_id,
			AutomationRule.is_active == True,  # noqa: E712
		)
		.order_by(AutomationRule.priority.desc(), AutomationRule.created_at)
	)
	result = await session.execute(stmt)
	rules = result.scalars().all()

	results = []
	for rule in rules:
		try:
			conditions: list[dict] = json.loads(rule.conditions) if rule.conditions else []
			actions: list[dict] = json.loads(rule.actions) if rule.actions else []
		except json.JSONDecodeError as exc:
			_log.warning("Rule %s has invalid JSON: %s", rule.id, exc)
			continue

		# All conditions must pass (AND logic)
		if not all(evaluate_condition(c, document_data) for c in conditions):
			_log.debug("Rule %s conditions not met for doc %s", rule.id, document_id)
			continue

		_log.info("Rule %r matched doc=%s event=%s dry_run=%s", rule.name, document_id, event, dry_run)

		action_results = []
		for action in actions:
			action_result = await execute_action(action, document_id, tenant_id, session, dry_run=dry_run)
			action_results.append(action_result)

		if not dry_run:
			rule.run_count = (rule.run_count or 0) + 1
			rule.last_run_at = utc_now()

		results.append({
			"rule_id": rule.id,
			"rule_name": rule.name,
			"conditions_matched": len(conditions),
			"actions": action_results,
		})

	if not dry_run and results:
		await session.commit()

	return results

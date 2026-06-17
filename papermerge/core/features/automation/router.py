# (c) Copyright Datacraft, 2026
"""REST endpoints for the automation rules engine — auto-discovered by router_loader."""
import json
import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core import schema
from papermerge.core.db.engine import get_db
from papermerge.core.features.auth import get_current_user
from papermerge.core.utils.tz import utc_now
from .db.orm import AutomationRule
from .service import evaluate_rules

router = APIRouter(tags=["automation"])

_log = logging.getLogger(__name__)


def _uuid7str() -> str:
	from uuid6 import uuid7
	return str(uuid7())


# ── Pydantic I/O schemas ──────────────────────────────────────────────────────

VALID_TRIGGERS = frozenset({
	"document.classified",
	"document.uploaded",
	"document.expiring",
	"scan.batch_complete",
})

VALID_OPERATORS = frozenset({"equals", "not_equals", "contains", "greater_than", "less_than"})
VALID_FIELDS = frozenset({"document_type", "tag_id", "page_count", "confidence_score"})
VALID_ACTION_TYPES = frozenset({
	"notify_user",
	"assign_approval_workflow",
	"route_to_folder",
	"apply_tag",
	"send_webhook",
	"set_document_type",
})


class ConditionIn(BaseModel):
	field: str
	operator: str
	value: str


class ActionIn(BaseModel):
	type: str
	params: dict = {}


class CreateRuleIn(BaseModel):
	name: str
	description: str = ""
	trigger_event: str
	conditions: list[ConditionIn] = []
	actions: list[ActionIn] = []
	is_active: bool = True
	priority: int = 0

	@field_validator("trigger_event")
	@classmethod
	def validate_trigger(cls, v: str) -> str:
		if v not in VALID_TRIGGERS:
			raise ValueError(f"trigger_event must be one of {sorted(VALID_TRIGGERS)}")
		return v


class UpdateRuleIn(BaseModel):
	name: str | None = None
	description: str | None = None
	trigger_event: str | None = None
	conditions: list[ConditionIn] | None = None
	actions: list[ActionIn] | None = None
	is_active: bool | None = None
	priority: int | None = None

	@field_validator("trigger_event")
	@classmethod
	def validate_trigger(cls, v: str | None) -> str | None:
		if v is not None and v not in VALID_TRIGGERS:
			raise ValueError(f"trigger_event must be one of {sorted(VALID_TRIGGERS)}")
		return v


class RuleOut(BaseModel):
	id: str
	name: str
	description: str
	trigger_event: str
	conditions: list[dict]
	actions: list[dict]
	is_active: bool
	priority: int
	run_count: int
	last_run_at: datetime | None
	tenant_id: str
	created_by_id: str
	created_at: datetime

	class Config:
		from_attributes = True

	@classmethod
	def from_orm_row(cls, row: AutomationRule) -> "RuleOut":
		return cls(
			id=row.id,
			name=row.name,
			description=row.description or "",
			trigger_event=row.trigger_event,
			conditions=json.loads(row.conditions) if row.conditions else [],
			actions=json.loads(row.actions) if row.actions else [],
			is_active=row.is_active,
			priority=row.priority,
			run_count=row.run_count,
			last_run_at=row.last_run_at,
			tenant_id=row.tenant_id,
			created_by_id=row.created_by_id,
			created_at=row.created_at,
		)


class TestRuleIn(BaseModel):
	document_id: str


class TestRuleOut(BaseModel):
	rule_id: str
	rule_name: str
	conditions_matched: bool
	actions_preview: list[dict]


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _get_rule_or_404(rule_id: str, tenant_id: str, session: AsyncSession) -> AutomationRule:
	stmt = select(AutomationRule).where(
		AutomationRule.id == rule_id,
		AutomationRule.tenant_id == tenant_id,
	)
	result = await session.execute(stmt)
	rule = result.scalar_one_or_none()
	if rule is None:
		raise HTTPException(status_code=404, detail="Automation rule not found.")
	return rule


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/automation/rules", response_model=list[RuleOut])
async def list_rules(
	current_user: Annotated[schema.User, Depends(get_current_user)],
	db_session: AsyncSession = Depends(get_db),
) -> list[RuleOut]:
	"""List all automation rules for the current tenant."""
	stmt = (
		select(AutomationRule)
		.where(AutomationRule.tenant_id == str(current_user.tenant_id))
		.order_by(AutomationRule.priority.desc(), AutomationRule.created_at)
	)
	result = await db_session.execute(stmt)
	rows = result.scalars().all()
	return [RuleOut.from_orm_row(r) for r in rows]


@router.post("/automation/rules", response_model=RuleOut, status_code=status.HTTP_201_CREATED)
async def create_rule(
	body: CreateRuleIn,
	current_user: Annotated[schema.User, Depends(get_current_user)],
	db_session: AsyncSession = Depends(get_db),
) -> RuleOut:
	"""Create a new automation rule."""
	rule = AutomationRule(
		id=_uuid7str(),
		name=body.name,
		description=body.description,
		trigger_event=body.trigger_event,
		conditions=json.dumps([c.model_dump() for c in body.conditions]),
		actions=json.dumps([a.model_dump() for a in body.actions]),
		is_active=body.is_active,
		priority=body.priority,
		run_count=0,
		tenant_id=str(current_user.tenant_id),
		created_by_id=str(current_user.id),
		created_at=utc_now(),
	)
	db_session.add(rule)
	await db_session.commit()
	await db_session.refresh(rule)
	return RuleOut.from_orm_row(rule)


@router.patch("/automation/rules/{rule_id}", response_model=RuleOut)
async def update_rule(
	rule_id: str,
	body: UpdateRuleIn,
	current_user: Annotated[schema.User, Depends(get_current_user)],
	db_session: AsyncSession = Depends(get_db),
) -> RuleOut:
	"""Update an automation rule — partial update. Use is_active to toggle."""
	rule = await _get_rule_or_404(rule_id, str(current_user.tenant_id), db_session)

	if body.name is not None:
		rule.name = body.name
	if body.description is not None:
		rule.description = body.description
	if body.trigger_event is not None:
		rule.trigger_event = body.trigger_event
	if body.conditions is not None:
		rule.conditions = json.dumps([c.model_dump() for c in body.conditions])
	if body.actions is not None:
		rule.actions = json.dumps([a.model_dump() for a in body.actions])
	if body.is_active is not None:
		rule.is_active = body.is_active
	if body.priority is not None:
		rule.priority = body.priority

	await db_session.commit()
	await db_session.refresh(rule)
	return RuleOut.from_orm_row(rule)


@router.delete("/automation/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
	rule_id: str,
	current_user: Annotated[schema.User, Depends(get_current_user)],
	db_session: AsyncSession = Depends(get_db),
) -> None:
	"""Delete an automation rule."""
	rule = await _get_rule_or_404(rule_id, str(current_user.tenant_id), db_session)
	await db_session.delete(rule)
	await db_session.commit()


@router.post("/automation/rules/{rule_id}/test", response_model=list[dict])
async def test_rule(
	rule_id: str,
	body: TestRuleIn,
	current_user: Annotated[schema.User, Depends(get_current_user)],
	db_session: AsyncSession = Depends(get_db),
) -> list[dict]:
	"""Dry-run a single rule against a document — evaluates conditions, returns
	what actions would execute without actually executing them."""
	rule = await _get_rule_or_404(rule_id, str(current_user.tenant_id), db_session)

	# Build minimal document_data from DB for condition evaluation
	from sqlalchemy import text
	doc_result = await db_session.execute(
		text(
			"SELECT d.document_type_id, n.title, "
			"       (SELECT COUNT(*) FROM pages p WHERE p.document_ver_id IN "
			"            (SELECT id FROM document_versions WHERE document_id = d.basetreenode_ptr_id)) AS page_count "
			"FROM documents d JOIN nodes n ON n.id = d.basetreenode_ptr_id "
			"WHERE d.basetreenode_ptr_id = :doc_id"
		),
		{"doc_id": body.document_id},
	)
	row = doc_result.fetchone()
	document_data: dict = {}
	if row:
		document_data = {
			"document_type": str(row.document_type_id) if row.document_type_id else None,
			"page_count": row.page_count or 0,
		}

	# Run with dry_run=True — only this rule, same evaluate_rules path
	results = await evaluate_rules(
		event=rule.trigger_event,
		document_id=body.document_id,
		document_data=document_data,
		tenant_id=str(current_user.tenant_id),
		session=db_session,
		dry_run=True,
	)
	# Filter to just the requested rule
	return [r for r in results if r["rule_id"] == rule_id]


@router.get("/automation/rules/{rule_id}/history", response_model=dict)
async def rule_history(
	rule_id: str,
	current_user: Annotated[schema.User, Depends(get_current_user)],
	db_session: AsyncSession = Depends(get_db),
) -> dict:
	"""Return summary stats for a rule (last_run_at, run_count).
	Full per-execution history requires an audit log table; this returns
	the lightweight stats available on the rule itself."""
	rule = await _get_rule_or_404(rule_id, str(current_user.tenant_id), db_session)
	return {
		"rule_id": rule.id,
		"rule_name": rule.name,
		"run_count": rule.run_count,
		"last_run_at": rule.last_run_at.isoformat() if rule.last_run_at else None,
		"is_active": rule.is_active,
	}

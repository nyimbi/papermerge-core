# (c) Copyright Datacraft, 2026
"""Auto-routing REST endpoints."""
import logging
import uuid
from uuid import UUID
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, and_, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.engine import get_db
from papermerge.core.features.auth.dependencies import require_scopes
from papermerge.core.features.auth import scopes
from papermerge.core.features.auto_routing.db.orm import AutoRoutingRule
from papermerge.core.features.auto_routing.service import apply_auto_routing

router = APIRouter(
	prefix="/auto-routing",
	tags=["auto-routing"],
)

_log = logging.getLogger(__name__)


# ── Schemas ────────────────────────────────────────────────────────────────────

class AutoRoutingRuleCreate(BaseModel):
	name: str
	document_type: str
	confidence_threshold: float = 0.75
	destination_folder_id: UUID
	project_id: UUID | None = None
	priority: int = 0
	is_active: bool = True


class AutoRoutingRuleUpdate(BaseModel):
	name: str | None = None
	document_type: str | None = None
	confidence_threshold: float | None = None
	destination_folder_id: UUID | None = None
	project_id: UUID | None = None
	priority: int | None = None
	is_active: bool | None = None


class AutoRoutingRuleOut(BaseModel):
	id: UUID
	name: str
	document_type: str
	confidence_threshold: float
	destination_folder_id: UUID
	project_id: UUID | None = None
	priority: int
	is_active: bool
	applied_count: int
	tenant_id: UUID
	created_by_id: UUID
	created_at: datetime
	updated_at: datetime

	model_config = ConfigDict(from_attributes=True)


class AutoRoutingRuleListResponse(BaseModel):
	items: list[AutoRoutingRuleOut]
	total: int
	page: int
	page_size: int


class TestAutoRoutingRequest(BaseModel):
	document_id: str
	document_type: str | None = None
	confidence: float | None = None


class TestAutoRoutingResponse(BaseModel):
	would_route: bool
	matched_rule: AutoRoutingRuleOut | None = None
	destination_folder_id: UUID | None = None


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/rules", response_model=AutoRoutingRuleListResponse)
async def list_auto_routing_rules(
	user: require_scopes(scopes.ROUTING_VIEW),
	db_session: AsyncSession = Depends(get_db),
	page: int = 1,
	page_size: int = 50,
	active_only: bool = False,
):
	"""List auto-routing rules for the current tenant."""
	offset = (page - 1) * page_size
	conditions = [AutoRoutingRule.tenant_id == UUID(str(user.tenant_id))]
	if active_only:
		conditions.append(AutoRoutingRule.is_active.is_(True))

	total = await db_session.scalar(
		select(func.count()).select_from(AutoRoutingRule).where(and_(*conditions))
	)

	result = await db_session.execute(
		select(AutoRoutingRule)
		.where(and_(*conditions))
		.order_by(AutoRoutingRule.priority.desc(), AutoRoutingRule.created_at.asc())
		.offset(offset)
		.limit(page_size)
	)
	rules = result.scalars().all()

	return AutoRoutingRuleListResponse(
		items=[AutoRoutingRuleOut.model_validate(r) for r in rules],
		total=total or 0,
		page=page,
		page_size=page_size,
	)


@router.post("/rules", response_model=AutoRoutingRuleOut, status_code=201)
async def create_auto_routing_rule(
	body: AutoRoutingRuleCreate,
	user: require_scopes(scopes.ROUTING_CREATE),
	db_session: AsyncSession = Depends(get_db),
):
	"""Create a new auto-routing rule."""
	rule = AutoRoutingRule(
		id=uuid.uuid4(),
		tenant_id=UUID(str(user.tenant_id)),
		created_by_id=UUID(str(user.id)),
		**body.model_dump(),
	)
	db_session.add(rule)
	await db_session.commit()
	await db_session.refresh(rule)
	return AutoRoutingRuleOut.model_validate(rule)


@router.patch("/rules/{rule_id}", response_model=AutoRoutingRuleOut)
async def update_auto_routing_rule(
	rule_id: UUID,
	body: AutoRoutingRuleUpdate,
	user: require_scopes(scopes.ROUTING_UPDATE),
	db_session: AsyncSession = Depends(get_db),
):
	"""Update an existing auto-routing rule."""
	result = await db_session.execute(
		select(AutoRoutingRule).where(
			and_(
				AutoRoutingRule.id == rule_id,
				AutoRoutingRule.tenant_id == UUID(str(user.tenant_id)),
			)
		)
	)
	rule: AutoRoutingRule | None = result.scalar_one_or_none()
	if rule is None:
		raise HTTPException(status_code=404, detail="Auto-routing rule not found")

	changes = body.model_dump(exclude_none=True)
	for field, value in changes.items():
		setattr(rule, field, value)

	from papermerge.core.utils.tz import utc_now
	rule.updated_at = utc_now()

	await db_session.commit()
	await db_session.refresh(rule)
	return AutoRoutingRuleOut.model_validate(rule)


@router.delete("/rules/{rule_id}", status_code=204)
async def delete_auto_routing_rule(
	rule_id: UUID,
	user: require_scopes(scopes.ROUTING_DELETE),
	db_session: AsyncSession = Depends(get_db),
):
	"""Delete an auto-routing rule."""
	result = await db_session.execute(
		select(AutoRoutingRule).where(
			and_(
				AutoRoutingRule.id == rule_id,
				AutoRoutingRule.tenant_id == UUID(str(user.tenant_id)),
			)
		)
	)
	rule: AutoRoutingRule | None = result.scalar_one_or_none()
	if rule is None:
		raise HTTPException(status_code=404, detail="Auto-routing rule not found")

	await db_session.delete(rule)
	await db_session.commit()


@router.post("/rules/{rule_id}/test", response_model=TestAutoRoutingResponse)
async def test_auto_routing_rule(
	rule_id: UUID,
	body: TestAutoRoutingRequest,
	user: require_scopes(scopes.ROUTING_VIEW),
	db_session: AsyncSession = Depends(get_db),
):
	"""
	Dry-run: check whether a specific rule would match a given document.

	If body.document_type / confidence are omitted, the endpoint reads them
	from the document's current classification metadata (if available).
	"""
	# Fetch the rule
	result = await db_session.execute(
		select(AutoRoutingRule).where(
			and_(
				AutoRoutingRule.id == rule_id,
				AutoRoutingRule.tenant_id == UUID(str(user.tenant_id)),
			)
		)
	)
	rule: AutoRoutingRule | None = result.scalar_one_or_none()
	if rule is None:
		raise HTTPException(status_code=404, detail="Auto-routing rule not found")

	# Resolve document_type + confidence from body or document metadata
	doc_type = body.document_type
	confidence = body.confidence

	if doc_type is None or confidence is None:
		# Try to read from document_metadata on the node
		try:
			from papermerge.core.features.document.db.orm import Document
			doc_result = await db_session.execute(
				select(Document).where(Document.id == UUID(body.document_id))
			)
			doc = doc_result.scalar_one_or_none()
			if doc and doc.document_metadata:
				meta = doc.document_metadata
				doc_type = doc_type or meta.get("document_type")
				confidence = confidence if confidence is not None else meta.get("confidence")
		except Exception as exc:
			_log.warning("test_auto_routing: could not load document metadata — %s", exc)

	if doc_type is None or confidence is None:
		raise HTTPException(
			status_code=422,
			detail="document_type and confidence are required when document has no classification metadata",
		)

	# Check match
	type_match = rule.document_type == doc_type
	conf_match = confidence >= rule.confidence_threshold
	would_route = rule.is_active and type_match and conf_match

	return TestAutoRoutingResponse(
		would_route=would_route,
		matched_rule=AutoRoutingRuleOut.model_validate(rule) if would_route else None,
		destination_folder_id=rule.destination_folder_id if would_route else None,
	)

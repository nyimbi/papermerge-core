# (c) Copyright Datacraft, 2026
"""Auto-routing API endpoints."""
import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.engine import get_db
from papermerge.core.features.auth.dependencies import require_scopes
from papermerge.core.features.auth import scopes
from papermerge.core.services.auto_router import AutoRouter
from . import schema
from .db.orm import RoutingRule, RoutingLog

router = APIRouter(
	prefix="/routing",
	tags=["routing"],
)

logger = logging.getLogger(__name__)


@router.get("/rules")
async def list_routing_rules(
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
	mode: str | None = None,
	active_only: bool = True,
	page: int = 1,
	page_size: int = 50,
) -> schema.RuleListResponse:
	"""List routing rules."""
	offset = (page - 1) * page_size

	conditions = [RoutingRule.tenant_id == user.tenant_id]
	if active_only:
		conditions.append(RoutingRule.is_active == True)
	if mode and mode != "both":
		conditions.append(
			(RoutingRule.mode == mode) | (RoutingRule.mode == "both")
		)

	count_stmt = select(func.count()).select_from(RoutingRule).where(and_(*conditions))
	total = await db_session.scalar(count_stmt)

	stmt = select(RoutingRule).where(
		and_(*conditions)
	).order_by(RoutingRule.priority).offset(offset).limit(page_size)
	result = await db_session.execute(stmt)
	rules = result.scalars().all()

	return schema.RuleListResponse(
		items=[schema.RuleInfo.model_validate(r) for r in rules],
		total=total,
		page=page,
		page_size=page_size,
	)


@router.post("/rules")
async def create_routing_rule(
	rule: schema.RuleCreate,
	user: require_scopes(scopes.NODE_CREATE),
	db_session: AsyncSession = Depends(get_db),
) -> schema.RuleDetail:
	"""Create a routing rule."""
	db_rule = RoutingRule(
		tenant_id=user.tenant_id,
		name=rule.name,
		description=rule.description,
		priority=rule.priority,
		conditions=rule.conditions,
		destination_type=rule.destination_type,
		destination_id=rule.destination_id,
		mode=rule.mode,
		is_active=True,
		created_by=user.id,
	)
	db_session.add(db_rule)
	await db_session.commit()
	await db_session.refresh(db_rule)

	return schema.RuleDetail.model_validate(db_rule)


@router.get("/rules/{rule_id}")
async def get_routing_rule(
	rule_id: UUID,
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
) -> schema.RuleDetail:
	"""Get routing rule details."""
	rule = await db_session.get(RoutingRule, rule_id)
	if not rule or rule.tenant_id != user.tenant_id:
		raise HTTPException(status_code=404, detail="Rule not found")

	return schema.RuleDetail.model_validate(rule)


@router.patch("/rules/{rule_id}")
async def update_routing_rule(
	rule_id: UUID,
	updates: schema.RuleUpdate,
	user: require_scopes(scopes.NODE_UPDATE),
	db_session: AsyncSession = Depends(get_db),
) -> schema.RuleDetail:
	"""Update a routing rule."""
	rule = await db_session.get(RoutingRule, rule_id)
	if not rule or rule.tenant_id != user.tenant_id:
		raise HTTPException(status_code=404, detail="Rule not found")

	update_data = updates.model_dump(exclude_unset=True)
	for field, value in update_data.items():
		setattr(rule, field, value)

	await db_session.commit()
	await db_session.refresh(rule)

	return schema.RuleDetail.model_validate(rule)


@router.delete("/rules/{rule_id}")
async def delete_routing_rule(
	rule_id: UUID,
	user: require_scopes(scopes.NODE_DELETE),
	db_session: AsyncSession = Depends(get_db),
) -> dict:
	"""Delete a routing rule."""
	rule = await db_session.get(RoutingRule, rule_id)
	if not rule or rule.tenant_id != user.tenant_id:
		raise HTTPException(status_code=404, detail="Rule not found")

	await db_session.delete(rule)
	await db_session.commit()

	return {"success": True}


@router.post("/route")
async def route_document(
	request: schema.RouteDocumentRequest,
	user: require_scopes(scopes.NODE_UPDATE),
	db_session: AsyncSession = Depends(get_db),
) -> schema.RouteDocumentResponse:
	"""Route a document based on its metadata."""
	auto_router = AutoRouter(db_session)

	result = await auto_router.route_document(
		document_id=request.document_id,
		mode=request.mode,
	)

	if result:
		return schema.RouteDocumentResponse(
			success=True,
			matched=True,
			rule_id=result.rule_id,
			destination_type=result.destination_type,
			destination_id=result.destination_id,
			message="Document routed successfully",
		)

	return schema.RouteDocumentResponse(
		success=True,
		matched=False,
		message="No matching rule found",
	)


@router.post("/test")
async def test_routing_rules(
	request: schema.TestRuleRequest,
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
) -> schema.TestRuleResponse:
	"""Test routing rules against provided metadata without routing."""
	auto_router = AutoRouter(db_session)

	rule = await auto_router.find_matching_rule(
		tenant_id=user.tenant_id,
		metadata=request.metadata,
		mode=request.mode,
	)

	if rule:
		return schema.TestRuleResponse(
			matched=True,
			matching_rule=schema.RuleInfo.model_validate(rule),
		)

	return schema.TestRuleResponse(matched=False)


@router.get("/logs")
async def list_routing_logs(
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
	document_id: UUID | None = None,
	matched_only: bool = False,
	page: int = 1,
	page_size: int = 50,
) -> schema.RoutingLogListResponse:
	"""List routing log entries."""
	offset = (page - 1) * page_size

	conditions = [RoutingLog.tenant_id == user.tenant_id]
	if document_id:
		conditions.append(RoutingLog.document_id == document_id)
	if matched_only:
		conditions.append(RoutingLog.matched == True)

	count_stmt = select(func.count()).select_from(RoutingLog).where(and_(*conditions))
	total = await db_session.scalar(count_stmt)

	stmt = select(RoutingLog).where(
		and_(*conditions)
	).order_by(RoutingLog.created_at.desc()).offset(offset).limit(page_size)
	result = await db_session.execute(stmt)
	logs = result.scalars().all()

	return schema.RoutingLogListResponse(
		items=[schema.RoutingLogInfo.model_validate(log) for log in logs],
		total=total,
		page=page,
		page_size=page_size,
	)

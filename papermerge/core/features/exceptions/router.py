# (c) Copyright Datacraft, 2026
"""Exception Event API endpoints."""
import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.engine import get_db
from papermerge.core.features.auth.dependencies import require_scopes
from papermerge.core.features.auth import scopes
from . import schema
from .db.orm import ExceptionEvent, ExceptionRoutingRule, ExceptionStatus

router = APIRouter(
	prefix="/exceptions",
	tags=["exceptions"],
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exception Events
# ---------------------------------------------------------------------------

@router.get("")
async def list_exceptions(
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
	status: str | None = None,
	exception_type: str | None = None,
	batch_id: str | None = None,
	document_id: str | None = None,
	severity: str | None = None,
	page: int = 1,
	page_size: int = 50,
) -> schema.ExceptionEventListResponse:
	"""List exception events with optional filters."""
	offset = (page - 1) * page_size

	conditions = [ExceptionEvent.tenant_id == user.tenant_id]
	if status:
		conditions.append(ExceptionEvent.status == status)
	if exception_type:
		conditions.append(ExceptionEvent.exception_type == exception_type)
	if batch_id:
		conditions.append(ExceptionEvent.batch_id == batch_id)
	if document_id:
		conditions.append(ExceptionEvent.document_id == document_id)
	if severity:
		conditions.append(ExceptionEvent.severity == severity)

	count_stmt = select(func.count()).select_from(ExceptionEvent).where(*conditions)
	total = await db_session.scalar(count_stmt) or 0

	stmt = (
		select(ExceptionEvent)
		.where(*conditions)
		.order_by(ExceptionEvent.created_at.desc())
		.offset(offset)
		.limit(page_size)
	)
	result = await db_session.execute(stmt)
	events = result.scalars().all()

	return schema.ExceptionEventListResponse(
		items=[schema.ExceptionEventInfo.model_validate(e) for e in events],
		total=total,
		page=page,
		page_size=page_size,
	)


@router.post("")
async def create_exception(
	event_data: schema.ExceptionEventCreate,
	user: require_scopes(scopes.NODE_UPDATE),
	db_session: AsyncSession = Depends(get_db),
) -> schema.ExceptionEventInfo:
	"""Create a new exception event (called by quality pipeline or scan agent)."""
	event = ExceptionEvent(
		tenant_id=user.tenant_id,
		scan_job_id=event_data.scan_job_id,
		document_id=event_data.document_id,
		batch_id=event_data.batch_id,
		page_number=event_data.page_number,
		exception_type=event_data.exception_type,
		severity=event_data.severity,
		routing_action=event_data.routing_action,
		description=event_data.description,
		auto_fixable=event_data.auto_fixable,
		quality_score=event_data.quality_score,
		defects=event_data.defects,
		status=ExceptionStatus.OPEN.value,
	)

	# Auto-apply routing rule if one exists for this exception type
	if not event_data.routing_action:
		rule = await _find_routing_rule(
			db_session, user.tenant_id, event_data.exception_type
		)
		if rule:
			event.routing_action = rule.action

	db_session.add(event)
	await db_session.commit()
	await db_session.refresh(event)

	return schema.ExceptionEventInfo.model_validate(event)


@router.get("/stats")
async def get_exception_stats(
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
) -> schema.ExceptionStatsInfo:
	"""Get exception counts by type/status for dashboard widget."""
	tenant_filter = ExceptionEvent.tenant_id == user.tenant_id

	# Total
	total_stmt = select(func.count()).select_from(ExceptionEvent).where(tenant_filter)
	total = await db_session.scalar(total_stmt) or 0

	# By status
	status_stmt = (
		select(ExceptionEvent.status, func.count().label("cnt"))
		.where(tenant_filter)
		.group_by(ExceptionEvent.status)
	)
	status_result = await db_session.execute(status_stmt)
	by_status = {row[0]: row[1] for row in status_result.fetchall()}

	# By exception type
	type_stmt = (
		select(ExceptionEvent.exception_type, func.count().label("cnt"))
		.where(tenant_filter)
		.group_by(ExceptionEvent.exception_type)
	)
	type_result = await db_session.execute(type_stmt)
	by_type = {row[0]: row[1] for row in type_result.fetchall()}

	# By severity
	severity_stmt = (
		select(ExceptionEvent.severity, func.count().label("cnt"))
		.where(tenant_filter)
		.group_by(ExceptionEvent.severity)
	)
	severity_result = await db_session.execute(severity_stmt)
	by_severity = {row[0]: row[1] for row in severity_result.fetchall()}

	# Open count
	open_stmt = select(func.count()).select_from(ExceptionEvent).where(
		tenant_filter, ExceptionEvent.status == ExceptionStatus.OPEN.value
	)
	open_count = await db_session.scalar(open_stmt) or 0

	# Critical + open
	critical_open_stmt = select(func.count()).select_from(ExceptionEvent).where(
		tenant_filter,
		ExceptionEvent.status == ExceptionStatus.OPEN.value,
		ExceptionEvent.severity == "critical",
	)
	critical_open = await db_session.scalar(critical_open_stmt) or 0

	return schema.ExceptionStatsInfo(
		total=total,
		by_status=by_status,
		by_type=by_type,
		by_severity=by_severity,
		open_count=open_count,
		critical_open=critical_open,
	)


@router.get("/{exception_id}")
async def get_exception(
	exception_id: str,
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
) -> schema.ExceptionEventInfo:
	"""Get a specific exception event."""
	stmt = select(ExceptionEvent).where(
		and_(
			ExceptionEvent.id == exception_id,
			ExceptionEvent.tenant_id == user.tenant_id,
		)
	)
	result = await db_session.execute(stmt)
	event = result.scalar()

	if not event:
		raise HTTPException(status_code=404, detail="Exception event not found")

	return schema.ExceptionEventInfo.model_validate(event)


@router.patch("/{exception_id}/resolve")
async def resolve_exception(
	exception_id: str,
	resolve_data: schema.ExceptionEventResolve,
	user: require_scopes(scopes.NODE_UPDATE),
	db_session: AsyncSession = Depends(get_db),
) -> schema.ExceptionEventInfo:
	"""Resolve an exception event."""
	stmt = select(ExceptionEvent).where(
		and_(
			ExceptionEvent.id == exception_id,
			ExceptionEvent.tenant_id == user.tenant_id,
		)
	)
	result = await db_session.execute(stmt)
	event = result.scalar()

	if not event:
		raise HTTPException(status_code=404, detail="Exception event not found")

	if event.status == ExceptionStatus.RESOLVED.value:
		raise HTTPException(status_code=409, detail="Exception is already resolved")

	event.status = ExceptionStatus.RESOLVED.value
	event.resolved_by_id = str(user.id)
	event.resolved_at = datetime.utcnow()
	if resolve_data.resolution_notes:
		event.resolution_notes = resolve_data.resolution_notes

	await db_session.commit()
	await db_session.refresh(event)

	return schema.ExceptionEventInfo.model_validate(event)


@router.patch("/{exception_id}/dismiss")
async def dismiss_exception(
	exception_id: str,
	dismiss_data: schema.ExceptionEventDismiss,
	user: require_scopes(scopes.NODE_UPDATE),
	db_session: AsyncSession = Depends(get_db),
) -> schema.ExceptionEventInfo:
	"""Dismiss an exception event."""
	stmt = select(ExceptionEvent).where(
		and_(
			ExceptionEvent.id == exception_id,
			ExceptionEvent.tenant_id == user.tenant_id,
		)
	)
	result = await db_session.execute(stmt)
	event = result.scalar()

	if not event:
		raise HTTPException(status_code=404, detail="Exception event not found")

	if event.status in (ExceptionStatus.RESOLVED.value, ExceptionStatus.DISMISSED.value):
		raise HTTPException(
			status_code=409,
			detail=f"Exception is already {event.status}",
		)

	event.status = ExceptionStatus.DISMISSED.value
	event.resolved_by_id = str(user.id)
	event.resolved_at = datetime.utcnow()
	if dismiss_data.resolution_notes:
		event.resolution_notes = dismiss_data.resolution_notes

	await db_session.commit()
	await db_session.refresh(event)

	return schema.ExceptionEventInfo.model_validate(event)


# ---------------------------------------------------------------------------
# Routing Rules
# ---------------------------------------------------------------------------

@router.get("/routing-rules")
async def list_routing_rules(
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
	active_only: bool = False,
	exception_type: str | None = None,
) -> schema.RoutingRuleListResponse:
	"""List exception routing rules for the tenant."""
	conditions = [ExceptionRoutingRule.tenant_id == user.tenant_id]
	if active_only:
		conditions.append(ExceptionRoutingRule.is_active == True)
	if exception_type:
		conditions.append(ExceptionRoutingRule.exception_type == exception_type)

	count_stmt = (
		select(func.count()).select_from(ExceptionRoutingRule).where(*conditions)
	)
	total = await db_session.scalar(count_stmt) or 0

	stmt = (
		select(ExceptionRoutingRule)
		.where(*conditions)
		.order_by(ExceptionRoutingRule.priority, ExceptionRoutingRule.exception_type)
	)
	result = await db_session.execute(stmt)
	rules = result.scalars().all()

	return schema.RoutingRuleListResponse(
		items=[schema.RoutingRuleInfo.model_validate(r) for r in rules],
		total=total,
	)


@router.post("/routing-rules")
async def create_routing_rule(
	rule_data: schema.RoutingRuleCreate,
	user: require_scopes(scopes.SYSTEM_ADMIN),
	db_session: AsyncSession = Depends(get_db),
) -> schema.RoutingRuleInfo:
	"""Create a new exception routing rule."""
	rule = ExceptionRoutingRule(
		tenant_id=user.tenant_id,
		project_id=rule_data.project_id,
		exception_type=rule_data.exception_type,
		action=rule_data.action,
		priority=rule_data.priority,
		is_active=rule_data.is_active,
		config=rule_data.config,
	)
	db_session.add(rule)
	await db_session.commit()
	await db_session.refresh(rule)

	return schema.RoutingRuleInfo.model_validate(rule)


@router.patch("/routing-rules/{rule_id}")
async def update_routing_rule(
	rule_id: str,
	updates: schema.RoutingRuleUpdate,
	user: require_scopes(scopes.SYSTEM_ADMIN),
	db_session: AsyncSession = Depends(get_db),
) -> schema.RoutingRuleInfo:
	"""Update an exception routing rule."""
	stmt = select(ExceptionRoutingRule).where(
		and_(
			ExceptionRoutingRule.id == rule_id,
			ExceptionRoutingRule.tenant_id == user.tenant_id,
		)
	)
	result = await db_session.execute(stmt)
	rule = result.scalar()

	if not rule:
		raise HTTPException(status_code=404, detail="Routing rule not found")

	update_data = updates.model_dump(exclude_unset=True)
	for field, value in update_data.items():
		setattr(rule, field, value)

	await db_session.commit()
	await db_session.refresh(rule)

	return schema.RoutingRuleInfo.model_validate(rule)


@router.delete("/routing-rules/{rule_id}")
async def delete_routing_rule(
	rule_id: str,
	user: require_scopes(scopes.SYSTEM_ADMIN),
	db_session: AsyncSession = Depends(get_db),
) -> dict:
	"""Delete an exception routing rule."""
	stmt = select(ExceptionRoutingRule).where(
		and_(
			ExceptionRoutingRule.id == rule_id,
			ExceptionRoutingRule.tenant_id == user.tenant_id,
		)
	)
	result = await db_session.execute(stmt)
	rule = result.scalar()

	if not rule:
		raise HTTPException(status_code=404, detail="Routing rule not found")

	await db_session.delete(rule)
	await db_session.commit()

	return {"success": True}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _find_routing_rule(
	db_session: AsyncSession,
	tenant_id: str | None,
	exception_type: str,
) -> ExceptionRoutingRule | None:
	"""Find the highest-priority active routing rule for the given exception type."""
	stmt = (
		select(ExceptionRoutingRule)
		.where(
			and_(
				ExceptionRoutingRule.tenant_id == tenant_id,
				ExceptionRoutingRule.exception_type == exception_type,
				ExceptionRoutingRule.is_active == True,
			)
		)
		.order_by(ExceptionRoutingRule.priority)
		.limit(1)
	)
	result = await db_session.execute(stmt)
	return result.scalar()

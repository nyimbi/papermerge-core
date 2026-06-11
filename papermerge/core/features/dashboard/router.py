# (c) Copyright Datacraft, 2026
"""Dashboard API endpoints."""
import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.engine import get_db
from papermerge.core.features.auth.dependencies import require_scopes
from papermerge.core.features.auth import scopes

router = APIRouter(
	prefix="/dashboard",
	tags=["dashboard"],
)

logger = logging.getLogger(__name__)


@router.get("/stats")
async def get_dashboard_stats(
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
) -> dict:
	"""Get dashboard statistics for current user."""
	from papermerge.core.features.ownership.db.orm import Ownership
	from papermerge.core.features.nodes.db.orm import Node
	from papermerge.core.features.workflows.db.orm import WorkflowApprovalRequest, WorkflowInstance

	now = datetime.now(timezone.utc)
	month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

	async def _count_documents() -> int:
		stmt = (
			select(func.count())
			.select_from(Ownership)
			.join(Node, Node.id == Ownership.resource_id)
			.where(
				Ownership.owner_type == "user",
				Ownership.owner_id == user.id,
				Ownership.resource_type == "node",
				Node.ctype == "document",
			)
		)
		return (await db_session.scalar(stmt)) or 0

	async def _count_documents_this_month() -> int:
		stmt = (
			select(func.count())
			.select_from(Ownership)
			.join(Node, Node.id == Ownership.resource_id)
			.where(
				Ownership.owner_type == "user",
				Ownership.owner_id == user.id,
				Ownership.resource_type == "node",
				Node.ctype == "document",
				Ownership.created_at >= month_start,
			)
		)
		return (await db_session.scalar(stmt)) or 0

	async def _count_pending_tasks() -> int:
		stmt = (
			select(func.count())
			.select_from(WorkflowApprovalRequest)
			.where(
				WorkflowApprovalRequest.assignee_id == user.id,
				WorkflowApprovalRequest.status == "pending",
			)
		)
		return (await db_session.scalar(stmt)) or 0

	async def _count_active_workflows() -> int:
		stmt = (
			select(func.count())
			.select_from(WorkflowInstance)
			.where(WorkflowInstance.status == "running")
		)
		return (await db_session.scalar(stmt)) or 0

	async def _sum_storage_bytes() -> int:
		from papermerge.core.features.document.db.orm import DocumentVersion
		stmt = (
			select(func.coalesce(func.sum(DocumentVersion.size), 0))
			.join(Ownership, Ownership.resource_id == DocumentVersion.document_id)
			.where(
				Ownership.owner_type == "user",
				Ownership.owner_id == user.id,
				Ownership.resource_type == "node",
			)
		)
		return int((await db_session.scalar(stmt)) or 0)

	async def _count_ocr_processed() -> int:
		from papermerge.core.features.ingestion.db.orm import IngestionJob, IngestionSource
		stmt = (
			select(func.count())
			.select_from(IngestionJob)
			.join(IngestionSource, IngestionSource.id == IngestionJob.source_id)
			.where(
				IngestionJob.status == "completed",
				IngestionSource.tenant_id == user.tenant_id,
			)
		)
		return (await db_session.scalar(stmt)) or 0

	async def _get_storage_quota_bytes() -> int:
		from papermerge.core.features.tenants.db.orm import Tenant as TenantORM
		tenant = await db_session.get(TenantORM, user.tenant_id)
		quota_gb = (tenant.storage_quota_gb if tenant and tenant.storage_quota_gb else 10)
		return quota_gb * 1024 * 1024 * 1024

	try:
		total, this_month, pending, active_wf, storage, ocr, quota = await asyncio.gather(
			_count_documents(),
			_count_documents_this_month(),
			_count_pending_tasks(),
			_count_active_workflows(),
			_sum_storage_bytes(),
			_count_ocr_processed(),
			_get_storage_quota_bytes(),
		)
	except Exception:
		logger.exception("Failed to fetch dashboard stats")
		total = this_month = pending = active_wf = storage = ocr = 0
		quota = 10 * 1024 * 1024 * 1024

	return {
		"totalDocuments": total,
		"documentsThisMonth": this_month,
		"pendingTasks": pending,
		"storageUsedBytes": storage,
		"storageQuotaBytes": quota,
		"activeWorkflows": active_wf,
		"ocrProcessed": ocr,
	}


@router.get("/activity")
async def get_recent_activity(
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
	limit: int = 10,
) -> dict:
	"""Get recent activity for current user from audit log."""
	from papermerge.core import orm as core_orm

	try:
		stmt = (
			select(core_orm.AuditLog)
			.where(core_orm.AuditLog.user_id == user.id)
			.order_by(core_orm.AuditLog.timestamp.desc())
			.limit(limit)
		)
		result = await db_session.execute(stmt)
		entries = result.scalars().all()

		count_stmt = (
			select(func.count())
			.select_from(core_orm.AuditLog)
			.where(core_orm.AuditLog.user_id == user.id)
		)
		total = (await db_session.scalar(count_stmt)) or 0

		items = [
			{
				"id": str(e.id),
				"timestamp": e.timestamp.isoformat() if e.timestamp else None,
				"table_name": e.table_name,
				"operation": e.operation,
				"record_id": str(e.record_id) if e.record_id else None,
			}
			for e in entries
		]
	except Exception:
		logger.exception("Failed to fetch dashboard activity")
		items, total = [], 0

	return {"items": items, "total": total}

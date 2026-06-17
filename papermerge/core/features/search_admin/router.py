"""Search index administration router.

Auto-discovered by papermerge.core.router_loader.discover_routers via router.py.

Endpoints:
  GET  /admin/search/index-stats          — index coverage stats for tenant
  POST /admin/search/reindex              — queue re-OCR for all non-completed docs
  POST /admin/search/reindex/{document_id} — queue re-OCR for a single document
  GET  /admin/search/failed-documents     — list documents with ocr_status=FAILURE
"""
import logging
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select as sa_select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from papermerge.core.db.engine import get_db
from papermerge.core.features.auth.dependencies import require_scopes
from papermerge.core.features.auth import scopes
from papermerge.core.tasks import send_task
from papermerge.core.types import OCRStatusEnum

logger = logging.getLogger(__name__)

router = APIRouter(
	prefix="/admin/search",
	tags=["search-admin"],
)

# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class IndexStats(BaseModel):
	total_documents: int
	indexed_documents: int
	pending_indexing: int
	failed_indexing: int
	last_updated: datetime
	vector_index_available: bool


class ReindexResponse(BaseModel):
	queued_count: int


class FailedDocument(BaseModel):
	id: str
	title: str
	created_at: datetime
	ocr_status: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _vector_index_available() -> bool:
	try:
		from pgvector.sqlalchemy import Vector  # noqa: F401
		return True
	except ImportError:
		return False


# ---------------------------------------------------------------------------
# GET /admin/search/index-stats
# ---------------------------------------------------------------------------

@router.get(
	"/index-stats",
	response_model=IndexStats,
	responses={
		status.HTTP_403_FORBIDDEN: {"description": "Requires tenant.admin scope"},
	},
)
async def get_index_stats(
	user: Annotated[object, Depends(require_scopes(scopes.TENANT_ADMIN))],
	db_session: AsyncSession = Depends(get_db),
) -> IndexStats:
	"""Return search index coverage statistics for the current tenant.

	Counts are scoped to documents the authenticated admin can see via
	the Ownership table (same as other admin endpoints).
	"""
	from papermerge.core import orm as core_orm
	from papermerge.core.features.ownership.db.orm import Ownership
	from papermerge.core.types import OwnerType

	# Access subquery: all node_ids accessible to this user (owner or group member).
	user_groups_sq = sa_select(core_orm.UserGroup.group_id).where(
		core_orm.UserGroup.user_id == user.id
	)
	access_sq = sa_select(Ownership.resource_id).where(
		Ownership.resource_type == "node",
		(
			(Ownership.owner_type == OwnerType.USER.value)
			& (Ownership.owner_id == user.id)
		)
		| (
			(Ownership.owner_type == OwnerType.GROUP.value)
			& (Ownership.owner_id.in_(user_groups_sq))
		),
	)

	base = (
		sa_select(func.count())
		.select_from(core_orm.Document)
		.where(
			core_orm.Document.id.in_(access_sq),
			core_orm.Document.deleted_at.is_(None),
		)
	)

	total = (await db_session.execute(base)).scalar_one()

	indexed = (await db_session.execute(
		base.where(core_orm.Document.ocr_status == OCRStatusEnum.success)
	)).scalar_one()

	pending = (await db_session.execute(
		base.where(core_orm.Document.ocr_status.in_([
			OCRStatusEnum.received,
			OCRStatusEnum.started,
		]))
	)).scalar_one()

	failed = (await db_session.execute(
		base.where(core_orm.Document.ocr_status == OCRStatusEnum.failure)
	)).scalar_one()

	return IndexStats(
		total_documents=total,
		indexed_documents=indexed,
		pending_indexing=pending,
		failed_indexing=failed,
		last_updated=datetime.utcnow(),
		vector_index_available=_vector_index_available(),
	)


# ---------------------------------------------------------------------------
# POST /admin/search/reindex
# ---------------------------------------------------------------------------

@router.post(
	"/reindex",
	response_model=ReindexResponse,
	status_code=status.HTTP_202_ACCEPTED,
	responses={
		status.HTTP_403_FORBIDDEN: {"description": "Requires tenant.admin scope"},
	},
)
async def reindex_all_pending(
	user: Annotated[object, Depends(require_scopes(scopes.TENANT_ADMIN))],
	db_session: AsyncSession = Depends(get_db),
) -> ReindexResponse:
	"""Queue re-OCR for all documents that are not yet successfully indexed.

	Targets documents with ocr_status in (UNKNOWN, RECEIVED, STARTED, FAILURE).
	Resets each to RECEIVED and dispatches a process_upload task.
	"""
	from papermerge.core import orm as core_orm
	from papermerge.core.features.ownership.db.orm import Ownership
	from papermerge.core.types import OwnerType

	user_groups_sq = sa_select(core_orm.UserGroup.group_id).where(
		core_orm.UserGroup.user_id == user.id
	)
	access_sq = sa_select(Ownership.resource_id).where(
		Ownership.resource_type == "node",
		(
			(Ownership.owner_type == OwnerType.USER.value)
			& (Ownership.owner_id == user.id)
		)
		| (
			(Ownership.owner_type == OwnerType.GROUP.value)
			& (Ownership.owner_id.in_(user_groups_sq))
		),
	)

	# Fetch all non-completed documents with their latest version.
	stmt = (
		sa_select(core_orm.Document)
		.options(selectinload(core_orm.Document.versions))
		.where(
			core_orm.Document.id.in_(access_sq),
			core_orm.Document.deleted_at.is_(None),
			core_orm.Document.ocr_status != OCRStatusEnum.success,
		)
	)
	result = await db_session.execute(stmt)
	docs = result.scalars().all()

	queued = 0
	for doc in docs:
		versions = sorted(doc.versions, key=lambda v: v.number, reverse=True)
		if not versions:
			continue
		latest = versions[0]

		# Reset status so UI reflects in-progress immediately.
		await db_session.execute(
			sa_update(core_orm.Document)
			.where(core_orm.Document.id == doc.id)
			.values(ocr_status=OCRStatusEnum.received)
		)

		send_task(
			"process_upload",
			kwargs={
				"document_id": str(doc.id),
				"document_version_id": str(latest.id),
				"lang": latest.lang or "eng",
				"user_id": str(user.id),
			},
			route_name="s3",
		)
		queued += 1

	await db_session.commit()
	logger.info(f"Admin reindex: queued {queued} documents for user {user.id}")
	return ReindexResponse(queued_count=queued)


# ---------------------------------------------------------------------------
# POST /admin/search/reindex/{document_id}
# ---------------------------------------------------------------------------

@router.post(
	"/reindex/{document_id}",
	response_model=ReindexResponse,
	status_code=status.HTTP_202_ACCEPTED,
	responses={
		status.HTTP_403_FORBIDDEN: {"description": "Requires tenant.admin scope"},
		status.HTTP_404_NOT_FOUND: {"description": "Document not found"},
		status.HTTP_409_CONFLICT: {"description": "Document has no versions"},
	},
)
async def reindex_document(
	document_id: uuid.UUID,
	user: Annotated[object, Depends(require_scopes(scopes.TENANT_ADMIN))],
	db_session: AsyncSession = Depends(get_db),
) -> ReindexResponse:
	"""Queue re-OCR for a single document by ID."""
	from papermerge.core import orm as core_orm

	stmt = (
		sa_select(core_orm.Document)
		.options(selectinload(core_orm.Document.versions))
		.where(core_orm.Document.id == document_id)
	)
	result = await db_session.execute(stmt)
	doc = result.scalar_one_or_none()

	if doc is None:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

	versions = sorted(doc.versions, key=lambda v: v.number, reverse=True)
	if not versions:
		raise HTTPException(
			status_code=status.HTTP_409_CONFLICT,
			detail="Document has no versions to re-index.",
		)
	latest = versions[0]

	await db_session.execute(
		sa_update(core_orm.Document)
		.where(core_orm.Document.id == document_id)
		.values(ocr_status=OCRStatusEnum.received)
	)
	await db_session.commit()

	send_task(
		"process_upload",
		kwargs={
			"document_id": str(document_id),
			"document_version_id": str(latest.id),
			"lang": latest.lang or "eng",
			"user_id": str(user.id),
		},
		route_name="s3",
	)

	logger.info(f"Admin reindex: queued document {document_id} for user {user.id}")
	return ReindexResponse(queued_count=1)


# ---------------------------------------------------------------------------
# GET /admin/search/failed-documents
# ---------------------------------------------------------------------------

@router.get(
	"/failed-documents",
	response_model=list[FailedDocument],
	responses={
		status.HTTP_403_FORBIDDEN: {"description": "Requires tenant.admin scope"},
	},
)
async def list_failed_documents(
	user: Annotated[object, Depends(require_scopes(scopes.TENANT_ADMIN))],
	limit: int = Query(default=50, ge=1, le=500),
	db_session: AsyncSession = Depends(get_db),
) -> list[FailedDocument]:
	"""Return documents with ocr_status=FAILURE for the current tenant."""
	from papermerge.core import orm as core_orm
	from papermerge.core.features.ownership.db.orm import Ownership
	from papermerge.core.types import OwnerType

	user_groups_sq = sa_select(core_orm.UserGroup.group_id).where(
		core_orm.UserGroup.user_id == user.id
	)
	access_sq = sa_select(Ownership.resource_id).where(
		Ownership.resource_type == "node",
		(
			(Ownership.owner_type == OwnerType.USER.value)
			& (Ownership.owner_id == user.id)
		)
		| (
			(Ownership.owner_type == OwnerType.GROUP.value)
			& (Ownership.owner_id.in_(user_groups_sq))
		),
	)

	stmt = (
		sa_select(core_orm.Document)
		.where(
			core_orm.Document.id.in_(access_sq),
			core_orm.Document.deleted_at.is_(None),
			core_orm.Document.ocr_status == OCRStatusEnum.failure,
		)
		.order_by(core_orm.Document.created_at.desc())
		.limit(limit)
	)
	result = await db_session.execute(stmt)
	docs = result.scalars().all()

	return [
		FailedDocument(
			id=str(doc.id),
			title=doc.title,
			created_at=doc.created_at,
			ocr_status=doc.ocr_status,
		)
		for doc in docs
	]

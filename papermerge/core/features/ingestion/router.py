# (c) Copyright Datacraft, 2026
"""Document ingestion API endpoints."""
import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Depends, status
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.engine import get_db
from papermerge.core.features.auth.dependencies import require_scopes
from papermerge.core.features.auth import scopes
from . import schema
from .db.orm import IngestionSource, IngestionJob

router = APIRouter(
	prefix="/ingestion",
	tags=["ingestion"],
)

logger = logging.getLogger(__name__)


@router.get("/sources")
async def list_ingestion_sources(
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
	page: int = 1,
	page_size: int = 20,
) -> schema.SourceListResponse:
	"""List ingestion sources."""
	offset = (page - 1) * page_size

	conditions = [IngestionSource.tenant_id == user.tenant_id]

	count_stmt = select(func.count()).select_from(IngestionSource).where(and_(*conditions))
	total = await db_session.scalar(count_stmt)

	stmt = select(IngestionSource).where(and_(*conditions)).offset(offset).limit(page_size)
	result = await db_session.execute(stmt)
	sources = result.scalars().all()

	return schema.SourceListResponse(
		items=[schema.SourceInfo.model_validate(s) for s in sources],
		total=total,
		page=page,
		page_size=page_size,
	)


@router.post("/sources")
async def create_ingestion_source(
	source: schema.SourceCreate,
	user: require_scopes(scopes.NODE_CREATE),
	db_session: AsyncSession = Depends(get_db),
) -> schema.SourceInfo:
	"""Create an ingestion source."""
	db_source = IngestionSource(
		tenant_id=user.tenant_id,
		name=source.name,
		source_type=source.source_type,
		config=source.config,
		mode=source.mode,
		target_folder_id=source.target_folder_id,
		is_active=False,
	)
	db_session.add(db_source)
	await db_session.commit()
	await db_session.refresh(db_source)

	return schema.SourceInfo.model_validate(db_source)


@router.get("/sources/{source_id}")
async def get_ingestion_source(
	source_id: UUID,
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
) -> schema.SourceDetail:
	"""Get ingestion source details."""
	source = await db_session.get(IngestionSource, source_id)
	if not source:
		raise HTTPException(status_code=404, detail="Source not found")

	return schema.SourceDetail.model_validate(source)


@router.post("/sources/{source_id}/start")
async def start_ingestion_source(
	source_id: UUID,
	user: require_scopes(scopes.NODE_UPDATE),
	db_session: AsyncSession = Depends(get_db),
) -> dict:
	"""Start an ingestion source (e.g., folder watcher)."""
	source = await db_session.get(IngestionSource, source_id)
	if not source:
		raise HTTPException(status_code=404, detail="Source not found")

	source.is_active = True
	await db_session.commit()

	# Queue the watcher task
	from papermerge.core.tasks import send_task
	send_task(
		"darchiva.ingestion.start_watcher",
		kwargs={"source_id": str(source_id)}
	)

	return {"success": True, "message": "Source started"}


@router.post("/sources/{source_id}/stop")
async def stop_ingestion_source(
	source_id: UUID,
	user: require_scopes(scopes.NODE_UPDATE),
	db_session: AsyncSession = Depends(get_db),
) -> dict:
	"""Stop an ingestion source."""
	source = await db_session.get(IngestionSource, source_id)
	if not source:
		raise HTTPException(status_code=404, detail="Source not found")

	source.is_active = False
	await db_session.commit()

	return {"success": True, "message": "Source stopped"}


@router.delete("/sources/{source_id}")
async def delete_ingestion_source(
	source_id: UUID,
	user: require_scopes(scopes.NODE_DELETE),
	db_session: AsyncSession = Depends(get_db),
) -> dict:
	"""Delete an ingestion source."""
	source = await db_session.get(IngestionSource, source_id)
	if not source:
		raise HTTPException(status_code=404, detail="Source not found")

	await db_session.delete(source)
	await db_session.commit()

	return {"success": True}


@router.get("/jobs")
async def list_ingestion_jobs(
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
	source_id: UUID | None = None,
	status_filter: str | None = None,
	page: int = 1,
	page_size: int = 50,
) -> schema.JobListResponse:
	"""List ingestion jobs."""
	offset = (page - 1) * page_size

	conditions = [IngestionJob.tenant_id == user.tenant_id]
	if source_id:
		conditions.append(IngestionJob.source_id == source_id)
	if status_filter:
		conditions.append(IngestionJob.status == status_filter)

	count_stmt = select(func.count()).select_from(IngestionJob).where(and_(*conditions))
	total = await db_session.scalar(count_stmt)

	stmt = select(IngestionJob).where(
		and_(*conditions)
	).order_by(IngestionJob.created_at.desc()).offset(offset).limit(page_size)
	result = await db_session.execute(stmt)
	jobs = result.scalars().all()

	return schema.JobListResponse(
		items=[schema.JobInfo.model_validate(j) for j in jobs],
		total=total,
		page=page,
		page_size=page_size,
	)


@router.get("/jobs/{job_id}")
async def get_ingestion_job(
	job_id: UUID,
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
) -> schema.JobDetail:
	"""Get ingestion job details."""
	job = await db_session.get(IngestionJob, job_id)
	if not job:
		raise HTTPException(status_code=404, detail="Job not found")

	return schema.JobDetail.model_validate(job)


@router.post("/email")
async def ingest_from_email(
	request: schema.EmailIngestionRequest,
	user: require_scopes(scopes.NODE_CREATE),
	db_session: AsyncSession = Depends(get_db),
) -> schema.IngestionResponse:
	"""Process documents from an email."""
	from papermerge.core.tasks import send_task

	# Queue email processing task
	send_task(
		"darchiva.ingestion.process_email",
		kwargs={
			"tenant_id": str(user.tenant_id),
			"email_data": request.model_dump(),
		}
	)

	return schema.IngestionResponse(
		success=True,
		message="Email processing queued",
	)

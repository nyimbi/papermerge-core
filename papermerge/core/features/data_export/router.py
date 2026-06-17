# (c) Copyright Datacraft, 2026
"""Data export REST endpoints — auto-discovered by router_loader.

Routes
------
POST   /admin/data-export                   create full-tenant async export job
GET    /admin/data-export/{job_id}           poll job status
GET    /admin/data-export/{job_id}/download  stream the completed ZIP
POST   /documents/bundle                    immediate bundle (≤10 docs)
POST   /admin/gdpr/subject-request          immediate GDPR subject export
GET    /admin/data-export                   list recent export jobs
"""
import json
import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.engine import get_db
from papermerge.core.features.auth import get_current_user
from papermerge.core.features.users.schema import User
from papermerge.core.utils.tz import utc_now
from papermerge.core.utils.uuid_compat import uuid7str

from .db.orm import DataExportJob

_log = logging.getLogger(__name__)

router = APIRouter(tags=["data-export"])

MAX_IMMEDIATE_BUNDLE_DOCS = 10


# ── I/O schemas ───────────────────────────────────────────────────────────────

class StartExportOut(BaseModel):
	job_id: str
	status: str
	message: str


class ExportJobOut(BaseModel):
	id: str
	job_type: str
	status: str
	requested_by_id: str
	tenant_id: str
	file_size_bytes: int | None
	error_message: str | None
	created_at: datetime
	completed_at: datetime | None

	class Config:
		from_attributes = True


class BundleIn(BaseModel):
	document_ids: list[str]
	include_metadata: bool = True


class GdprSubjectIn(BaseModel):
	email: str


# ── helpers ───────────────────────────────────────────────────────────────────

def _get_tenant_id(user: User) -> str:
	return str(getattr(user, "tenant_id", None) or getattr(user, "group_id", None) or str(user.id))


async def _get_job_or_404(job_id: str, db: AsyncSession) -> DataExportJob:
	job = (
		await db.execute(select(DataExportJob).where(DataExportJob.id == job_id))
	).scalar_one_or_none()
	if job is None:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Export job not found")
	return job


# ── endpoints ─────────────────────────────────────────────────────────────────

@router.get(
	"/admin/data-export",
	response_model=list[ExportJobOut],
	summary="List recent data export jobs for this tenant",
)
async def list_export_jobs(
	user: Annotated[User, Depends(get_current_user)],
	db: AsyncSession = Depends(get_db),
	limit: int = 20,
) -> list[ExportJobOut]:
	tenant_id = _get_tenant_id(user)
	stmt = (
		select(DataExportJob)
		.where(DataExportJob.tenant_id == tenant_id)
		.order_by(desc(DataExportJob.created_at))
		.limit(limit)
	)
	rows = (await db.execute(stmt)).scalars().all()
	return list(rows)


@router.post(
	"/admin/data-export",
	response_model=StartExportOut,
	status_code=status.HTTP_202_ACCEPTED,
	summary="Start a full-tenant async export job",
)
async def start_full_tenant_export(
	user: Annotated[User, Depends(get_current_user)],
	db: AsyncSession = Depends(get_db),
) -> StartExportOut:
	tenant_id = _get_tenant_id(user)
	job = DataExportJob(
		id=uuid7str(),
		job_type="full_tenant",
		status="pending",
		requested_by_id=str(user.id),
		tenant_id=tenant_id,
		params="{}",
	)
	db.add(job)
	await db.commit()

	# Dispatch celery task (import here to avoid circular at module load)
	try:
		from celery import current_app as celery_app
		celery_app.send_task("darchiva.data_export.run_export", args=[job.id])
	except Exception as exc:
		_log.warning("start_full_tenant_export: could not enqueue task: %s", exc)

	return StartExportOut(job_id=job.id, status="pending", message="Export job queued")


@router.get(
	"/admin/data-export/{job_id}",
	response_model=ExportJobOut,
	summary="Poll the status of a data export job",
)
async def get_export_job(
	job_id: str,
	user: Annotated[User, Depends(get_current_user)],
	db: AsyncSession = Depends(get_db),
) -> ExportJobOut:
	job = await _get_job_or_404(job_id, db)
	return job


@router.get(
	"/admin/data-export/{job_id}/download",
	summary="Stream the completed ZIP for a data export job",
)
async def download_export(
	job_id: str,
	user: Annotated[User, Depends(get_current_user)],
	db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
	job = await _get_job_or_404(job_id, db)

	if job.status != "completed":
		raise HTTPException(
			status_code=status.HTTP_409_CONFLICT,
			detail=f"Export not ready — current status: {job.status}",
		)
	if not job.file_path:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Export file missing")

	from papermerge.storage.base import get_storage_backend
	storage = get_storage_backend()

	try:
		file_bytes: bytes = storage.download_file(job.file_path)
	except Exception as exc:
		_log.error("download_export: cannot fetch %s: %s", job.file_path, exc)
		raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Could not retrieve export file")

	return StreamingResponse(
		iter([file_bytes]),
		media_type="application/zip",
		headers={"Content-Disposition": f'attachment; filename="export_{job_id[:8]}.zip"'},
	)


@router.post(
	"/documents/bundle",
	summary="Immediate document bundle download (≤10 documents)",
)
async def download_bundle(
	body: BundleIn,
	user: Annotated[User, Depends(get_current_user)],
	db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
	if len(body.document_ids) > MAX_IMMEDIATE_BUNDLE_DOCS:
		raise HTTPException(
			status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
			detail=f"Immediate bundle supports at most {MAX_IMMEDIATE_BUNDLE_DOCS} documents. "
			       "Use POST /admin/data-export for larger exports.",
		)
	if not body.document_ids:
		raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="document_ids must not be empty")

	from .service import create_document_bundle
	zip_bytes = await create_document_bundle(body.document_ids, body.include_metadata, db)

	return StreamingResponse(
		iter([zip_bytes]),
		media_type="application/zip",
		headers={"Content-Disposition": 'attachment; filename="document_bundle.zip"'},
	)


@router.post(
	"/admin/gdpr/subject-request",
	summary="Immediate GDPR data subject export — returns ZIP of all documents for an email",
)
async def gdpr_subject_request(
	body: GdprSubjectIn,
	user: Annotated[User, Depends(get_current_user)],
	db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
	from .service import export_gdpr_subject
	zip_bytes = await export_gdpr_subject(body.email, db)

	safe_email = body.email.replace("@", "_at_").replace(".", "_")[:50]
	return StreamingResponse(
		iter([zip_bytes]),
		media_type="application/zip",
		headers={"Content-Disposition": f'attachment; filename="gdpr_{safe_email}.zip"'},
	)

# (c) Copyright Datacraft, 2026
"""Celery tasks for async data export jobs."""
import asyncio
import json
import logging

from celery import shared_task

_log = logging.getLogger(__name__)


@shared_task(name="darchiva.data_export.run_export")
def run_export_task(job_id: str) -> None:
	"""Execute a DataExportJob identified by *job_id*.

	Reads the job row, runs the appropriate export function, uploads the
	resulting ZIP to object storage, then marks the job completed (or failed).
	"""
	asyncio.run(_run_export_async(job_id))


async def _run_export_async(job_id: str) -> None:
	from papermerge.core.db.engine import get_async_session_maker
	from papermerge.core.features.data_export.db.orm import DataExportJob
	from papermerge.core.features.data_export.service import (
		create_document_bundle,
		export_full_tenant,
		export_gdpr_subject,
	)
	from papermerge.storage.base import get_storage_backend
	from papermerge.core.utils.tz import utc_now
	from sqlalchemy import select

	session_maker = get_async_session_maker()
	storage = get_storage_backend()

	async with session_maker() as session:
		job = (
			await session.execute(select(DataExportJob).where(DataExportJob.id == job_id))
		).scalar_one_or_none()

		if job is None:
			_log.error("run_export_task: job %s not found", job_id)
			return

		job.status = "processing"
		await session.commit()

		try:
			params: dict = json.loads(job.params or "{}")

			if job.job_type == "bundle":
				document_ids: list[str] = params.get("document_ids", [])
				include_metadata: bool = params.get("include_metadata", True)
				zip_bytes = await create_document_bundle(document_ids, include_metadata, session)

			elif job.job_type == "full_tenant":
				zip_bytes = await export_full_tenant(job.tenant_id, session)

			elif job.job_type == "gdpr_subject":
				email: str = params.get("subject_email", "")
				zip_bytes = await export_gdpr_subject(email, session)

			else:
				raise ValueError(f"Unknown job_type: {job.job_type!r}")

			export_key = f"exports/{job_id}/export.zip"
			await storage.upload_bytes(zip_bytes, export_key, "application/zip")

			job.status = "completed"
			job.file_path = export_key
			job.file_size_bytes = len(zip_bytes)
			job.completed_at = utc_now()
			_log.info("run_export_task: job %s completed (%d bytes)", job_id[:8], len(zip_bytes))

		except Exception as exc:
			_log.error("run_export_task: job %s failed: %s", job_id[:8], exc, exc_info=True)
			job.status = "failed"
			job.error_message = str(exc)[:500]
			job.completed_at = utc_now()

		await session.commit()

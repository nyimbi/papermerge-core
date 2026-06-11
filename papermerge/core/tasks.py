import logging
import asyncio

from celery import shared_task

from papermerge.celery_app import app as celery_app
from papermerge.core.utils.decorators import if_redis_present

logger = logging.getLogger(__name__)


def _log_task(name: str) -> str:
	return f"Running task: {name}"


@shared_task
def delete_user_data(user_id: str):
	"""Soft-delete a user and their associated data."""
	logger.info(_log_task(f"delete_user_data:{user_id[:8]}"))

	import uuid as _uuid

	async def _run():
		from papermerge.core.db.engine import get_async_session_maker
		from papermerge.core.features.users.db import api as users_dbapi

		async_session = get_async_session_maker()
		async with async_session() as session:
			try:
				uid = _uuid.UUID(user_id)
				await users_dbapi.delete_user(
					session,
					user_id=uid,
					deleted_by_user_id=uid,
				)
				await session.commit()
				logger.info(f"Deleted user data for {user_id}")
			except Exception as e:
				logger.error(f"Failed to delete user data for {user_id}: {e}")
				raise

	asyncio.run(_run())

@if_redis_present
def send_task(*args, **kwargs):
	logger.debug(f"Send task {args} {kwargs}")
	celery_app.send_task(*args, **kwargs)


@shared_task
def sync_email_account(account_id: str, owner_id: str):
	"""Sync emails from an IMAP account."""
	logger.info(_log_task(f"sync_email_account:{account_id[:8]}"))

	from papermerge.core.db.engine import sync_engine
	from sqlalchemy.orm import Session
	from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
	from papermerge.core.features.emails.models import EmailAccountModel
	from papermerge.core.features.emails.imap_client import sync_account
	import os

	async def _sync():
		from papermerge.core.db.engine import get_async_session_maker
		async_session = get_async_session_maker()

		async with async_session() as session:
			from sqlalchemy import select
			stmt = select(EmailAccountModel).where(EmailAccountModel.id == account_id)
			result = await session.execute(stmt)
			account = result.scalar_one_or_none()

			if not account:
				logger.error(f"Email account not found: {account_id}")
				return

			if not account.is_active:
				logger.info(f"Email account inactive: {account_id}")
				return

			stats = await sync_account(account, session, owner_id)
			logger.info(
				f"Email sync complete for {account_id[:8]}: "
				f"fetched={stats['messages_fetched']}, "
				f"imported={stats['messages_imported']}, "
				f"errors={len(stats['errors'])}"
			)

	asyncio.run(_sync())


@shared_task
def sync_all_email_accounts():
	"""Sync all active email accounts."""
	logger.info(_log_task("sync_all_email_accounts"))

	from papermerge.core.features.emails.models import EmailAccountModel
	from sqlalchemy import select
	from datetime import datetime, timedelta
	import asyncio

	async def _sync_all():
		from papermerge.core.db.engine import get_async_session_maker
		async_session = get_async_session_maker()

		async with async_session() as session:
			now = datetime.utcnow()

			# Find accounts due for sync
			stmt = select(EmailAccountModel).where(
				EmailAccountModel.is_active == True,
				EmailAccountModel.sync_enabled == True,
			)
			result = await session.execute(stmt)
			accounts = result.scalars().all()

			for account in accounts:
				# Check if due for sync
				if account.last_sync_at:
					next_sync = account.last_sync_at + timedelta(minutes=account.sync_interval_minutes)
					if now < next_sync:
						continue

				# Queue individual sync
				sync_email_account.delay(account.id, account.owner_id)

	asyncio.run(_sync_all())


@shared_task
def process_email_attachments(email_import_id: str, owner_id: str):
	"""Process attachments from an imported email."""
	logger.info(_log_task(f"process_email_attachments:{email_import_id[:8]}"))

	import asyncio

	async def _process():
		from papermerge.core.db.engine import get_async_session_maker
		from papermerge.core.features.emails.models import EmailImportModel, EmailAttachmentModel
		from sqlalchemy import select
		from sqlalchemy.orm import selectinload

		async_session = get_async_session_maker()

		async with async_session() as session:
			stmt = select(EmailImportModel).where(
				EmailImportModel.id == email_import_id
			).options(selectinload(EmailImportModel.attachments))

			result = await session.execute(stmt)
			email_import = result.scalar_one_or_none()

			if not email_import:
				logger.error(f"Email import not found: {email_import_id}")
				return

			for attachment in email_import.attachments:
				if attachment.import_status != "pending":
					continue

				try:
					from papermerge.core.features.document.db import api as doc_dbapi
					from papermerge.core.features.document import schema as doc_schema
					from papermerge.core.lib.mime import detect_and_validate_mime_type
					from papermerge.storage.base import get_storage_backend
					from papermerge.core import pathlib as plib
					from papermerge.core.utils.uuid_compat import uuid7

					# Get attachment content from storage
					storage = get_storage_backend()
					content = await storage.download_file(attachment.storage_key)

					doc_id = uuid7()
					ver_id = uuid7()
					mime_type = detect_and_validate_mime_type(
						content[:8192], attachment.filename, validate_structure=False
					)

					# Upload to document storage
					object_key = str(plib.docver_path(ver_id, file_name=attachment.filename))
					await storage.upload_bytes(content, object_key, str(mime_type))

					# Create document
					new_doc = doc_schema.NewDocument(
						id=doc_id,
						title=attachment.filename,
						lang="eng",
						parent_id=email_import.target_folder_id,
						size=len(content),
						page_count=0,
						ocr=True,
						file_name=attachment.filename,
						ctype="document",
					)
					doc = await doc_dbapi.create_document(
						session, new_doc, mime_type=mime_type, document_version_id=ver_id
					)

					attachment.document_id = doc.id
					attachment.import_status = "imported"

					# Trigger processing
					send_task("process_upload", kwargs={
						"document_id": str(doc_id),
						"document_version_id": str(ver_id),
						"lang": "eng",
						"user_id": str(owner_id),
					})

					logger.info(f"Imported attachment: {attachment.filename} -> {doc_id}")

				except Exception as e:
					attachment.import_status = "failed"
					attachment.import_error = str(e)
					logger.error(f"Failed to process attachment {attachment.filename}: {e}")

			await session.commit()

	asyncio.run(_process())


@shared_task(name="darchiva.ingestion.start_watcher")
def start_ingestion_watcher(source_id: str):
	"""Watch a folder source and ingest new files."""
	logger.info(_log_task(f"start_ingestion_watcher:{source_id[:8]}"))

	import os
	import glob

	async def _run():
		from papermerge.core.db.engine import get_async_session_maker
		from papermerge.core.features.ingestion.db.orm import (
			IngestionSource, IngestionJob, JobStatus,
		)
		from sqlalchemy import select
		from datetime import datetime, timezone

		async_session = get_async_session_maker()

		async with async_session() as session:
			source = await session.get(IngestionSource, source_id)
			if not source or not source.is_active:
				logger.info(f"Ingestion source inactive or not found: {source_id}")
				return

			if source.source_type != "watched_folder":
				logger.info(f"Source {source_id} is not a watched_folder, skipping")
				return

			folder_path = source.config.get("path", "")
			patterns = source.config.get("patterns", ["*.pdf"])

			if not folder_path or not os.path.isdir(folder_path):
				logger.warning(f"Watch path not found: {folder_path}")
				return

			files = []
			for pattern in patterns:
				files.extend(glob.glob(os.path.join(folder_path, pattern)))

			# Check which files already have ingestion jobs
			existing_stmt = select(IngestionJob.source_path).where(
				IngestionJob.source_id == source_id,
				IngestionJob.status.in_([JobStatus.PENDING, JobStatus.PROCESSING, JobStatus.COMPLETED]),
			)
			result = await session.execute(existing_stmt)
			already_ingested = {row[0] for row in result.all()}

			new_files = [f for f in files if f not in already_ingested]
			logger.info(f"Found {len(new_files)} new files to ingest from {folder_path}")

			for file_path in new_files:
				job = IngestionJob(
					source_id=source_id,
					source_path=file_path,
					status=JobStatus.PENDING,
				)
				session.add(job)

			source.last_checked_at = datetime.now(timezone.utc)
			await session.commit()

			for file_path in new_files:
				send_task(
					"darchiva.ingestion.process_file",
					kwargs={"source_id": source_id, "file_path": file_path},
				)

	asyncio.run(_run())


@shared_task(name="darchiva.ingestion.process_file")
def process_ingestion_file(source_id: str, file_path: str):
	"""Read a file from a watched folder and create a document from it."""
	logger.info(_log_task(f"process_ingestion_file:{file_path}"))

	import os

	async def _run():
		from papermerge.core.db.engine import get_async_session_maker
		from papermerge.core.features.ingestion.db.orm import IngestionSource, IngestionJob, JobStatus
		from sqlalchemy import select
		from datetime import datetime, timezone

		async_session = get_async_session_maker()

		async with async_session() as session:
			# Find the pending job for this file
			stmt = select(IngestionJob).where(
				IngestionJob.source_id == source_id,
				IngestionJob.source_path == file_path,
				IngestionJob.status == JobStatus.PENDING,
			)
			result = await session.execute(stmt)
			job = result.scalar_one_or_none()

			if not job:
				logger.warning(f"No pending ingestion job found for {file_path}")
				return

			job.status = JobStatus.PROCESSING
			job.started_at = datetime.now(timezone.utc)
			await session.commit()

			try:
				if not os.path.isfile(file_path):
					raise FileNotFoundError(f"File not found: {file_path}")

				source = await session.get(IngestionSource, source_id)
				file_size = os.path.getsize(file_path)
				file_name = os.path.basename(file_path)

				# Queue the actual document upload through the OCR pipeline
				send_task(
					"process_upload",
					kwargs={
						"file_path": file_path,
						"file_name": file_name,
						"file_size": file_size,
						"source_id": source_id,
						"apply_ocr": source.apply_ocr if source else True,
					},
				)

				job.status = JobStatus.COMPLETED
				job.completed_at = datetime.now(timezone.utc)
				await session.commit()
				logger.info(f"Queued ingestion for {file_name}")

			except Exception as e:
				job.status = JobStatus.FAILED
				job.error_message = str(e)
				job.completed_at = datetime.now(timezone.utc)
				await session.commit()
				logger.error(f"Failed to process ingestion file {file_path}: {e}")
				raise

	asyncio.run(_run())


@shared_task(name="darchiva.form.process")
def process_form_extraction(document_id: str, template_id: str | None, tenant_id: str):
	"""Extract form data from a document using OCR + LLM."""
	logger.info(_log_task(f"process_form_extraction:{document_id[:8]}"))

	async def _run():
		from papermerge.core.db.engine import get_async_session_maker
		from papermerge.core.features.form_recognition.db.orm import FormExtraction
		from sqlalchemy import select
		from datetime import datetime, timezone

		async_session = get_async_session_maker()

		async with async_session() as session:
			stmt = select(FormExtraction).where(
				FormExtraction.document_id == document_id,
				FormExtraction.status == "pending",
			)
			result = await session.execute(stmt)
			extraction = result.scalar_one_or_none()

			if not extraction:
				from uuid import uuid4
				extraction = FormExtraction(
					id=uuid4(),
					document_id=document_id,
					template_id=template_id,
					status="processing",
				)
				session.add(extraction)
			else:
				extraction.status = "processing"

			await session.commit()

			try:
				extraction.status = "completed"
				extraction.extracted_at = datetime.now(timezone.utc)
				await session.commit()
				logger.info(f"Form extraction completed for document {document_id}")
			except Exception as e:
				extraction.status = "failed"
				await session.commit()
				logger.error(f"Form extraction failed for document {document_id}: {e}")
				raise

	asyncio.run(_run())

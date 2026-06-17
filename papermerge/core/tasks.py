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

	from papermerge.core.features.emails.models import EmailAccountModel
	from papermerge.core.features.emails.imap_client import sync_account

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


@shared_task(name="darchiva.ingestion.process_batch")
def process_ingestion_batch(batch_id: str, file_paths: list[str], template_id: str | None = None):
	"""Process a batch of file uploads, fanning out a process_upload per file."""
	logger.info(_log_task(f"process_batch:{batch_id[:8]} files={len(file_paths)}"))

	import os

	async def _run():
		from papermerge.core.db.engine import get_async_session_maker
		from papermerge.core.features.ingestion.db.orm import IngestionBatch
		from datetime import datetime, timezone

		async_session = get_async_session_maker()

		async with async_session() as session:
			batch = await session.get(IngestionBatch, batch_id)
			if not batch:
				logger.warning(f"process_batch: batch {batch_id} not found")
				return

			batch.status = "processing"
			batch.started_at = datetime.now(timezone.utc)
			await session.commit()

			processed = 0
			failed = 0

			for file_path in file_paths:
				try:
					if not os.path.isfile(file_path):
						raise FileNotFoundError(f"File not found: {file_path}")

					file_name = os.path.basename(file_path)
					file_size = os.path.getsize(file_path)

					send_task(
						"process_upload",
						kwargs={
							"file_path": file_path,
							"file_name": file_name,
							"file_size": file_size,
							"source_id": None,
							"apply_ocr": True,
						},
					)
					processed += 1

				except Exception as e:
					logger.error(f"process_batch: failed to queue {file_path}: {e}")
					failed += 1

			batch.processed_files = processed
			batch.failed_files = failed
			batch.status = "completed" if failed == 0 else "partial"
			batch.completed_at = datetime.now(timezone.utc)
			await session.commit()
			logger.info(f"process_batch:{batch_id[:8]} done processed={processed} failed={failed}")

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
				from uuid import UUID as _UUID
				from papermerge.core.services.form_recognition import FormRecognitionService
				from papermerge.core.features.document.db.orm import DocumentVersion
				from sqlalchemy import select as _select

				# Fetch latest version text + page images for extraction
				ver_stmt = (
					_select(DocumentVersion)
					.where(DocumentVersion.document_id == document_id)
					.order_by(DocumentVersion.number.desc())
					.limit(1)
				)
				ver = (await session.execute(ver_stmt)).scalar_one_or_none()
				ocr_results = [{"text": ver.text or ""}] if ver else []

				svc = FormRecognitionService(session)
				result = await svc.recognize_and_extract(
					document_id=_UUID(document_id),
					tenant_id=_UUID(tenant_id),
					page_images=[],
					ocr_results=ocr_results,
				)
				extraction.status = "completed" if result.success else "failed"
				extraction.extracted_at = datetime.now(timezone.utc)
				if result.success:
					extraction.extracted_data = {
						"template_id": str(result.template_id) if result.template_id else None,
						"template_name": result.template_name,
						"confidence": result.confidence,
						"fields": [f.__dict__ if hasattr(f, "__dict__") else f for f in (result.fields or [])],
					}
				await session.commit()
				logger.info(f"Form extraction {'succeeded' if result.success else 'failed'} for {document_id}: {result.message}")
			except Exception as e:
				extraction.status = "failed"
				await session.commit()
				logger.error(f"Form extraction failed for document {document_id}: {e}")
				raise

	asyncio.run(_run())


@shared_task(name="darchiva.ingestion.process_email")
def process_email_ingestion(tenant_id: str, email_data: dict):
	"""Ingest attachments from an emailed document submission."""
	logger.info(_log_task(f"process_email_ingestion:tenant={tenant_id[:8]}"))

	import base64

	async def _run():
		from papermerge.core.db.engine import get_async_session_maker
		from papermerge.core.features.document.db import api as doc_dbapi
		from papermerge.core.features.document import schema as doc_schema
		from papermerge.core.lib.mime import detect_and_validate_mime_type
		from papermerge.core.utils.uuid_compat import uuid7
		from sqlalchemy import select

		async_session = get_async_session_maker()

		async with async_session() as session:
			attachments = email_data.get("attachments", [])
			subject = email_data.get("subject", "Email document")
			from_address = email_data.get("from_address", "")

			if not attachments:
				logger.info(f"No attachments in email from {from_address!r}, skipping")
				return

			# Find the inbox special folder for this tenant
			from papermerge.core.features.special_folders.db.orm import SpecialFolder
			from papermerge.core.types import FolderType, OwnerType
			inbox_stmt = select(SpecialFolder).where(
				SpecialFolder.folder_type == FolderType.INBOX,
			).limit(1)
			result = await session.execute(inbox_stmt)
			inbox = result.scalar_one_or_none()
			parent_id = inbox.folder_id if inbox else None

			for attachment in attachments:
				filename = attachment.get("filename", "attachment")
				content_b64 = attachment.get("content_base64", "")

				if not content_b64:
					logger.warning(f"Empty attachment {filename!r} in email from {from_address!r}")
					continue

				try:
					content = base64.b64decode(content_b64)
					mime_type = detect_and_validate_mime_type(
						content[:8192], filename, validate_structure=False
					)

					from papermerge.storage.base import get_storage_backend
					from papermerge.core import pathlib as plib

					doc_id = uuid7()
					ver_id = uuid7()

					storage = get_storage_backend()
					object_key = str(plib.docver_path(ver_id, file_name=filename))
					await storage.upload_bytes(content, object_key, str(mime_type))

					title = f"{subject} — {filename}" if subject else filename
					new_doc = doc_schema.NewDocument(
						id=doc_id,
						title=title[:500],
						lang="eng",
						parent_id=parent_id,
						size=len(content),
						page_count=0,
						ocr=True,
						file_name=filename,
						ctype="document",
					)
					await doc_dbapi.create_document(
						session, new_doc, mime_type=mime_type, document_version_id=ver_id
					)

					send_task("process_upload", kwargs={
						"document_id": str(doc_id),
						"document_version_id": str(ver_id),
						"lang": "eng",
					})

					logger.info(f"Ingested email attachment {filename!r} as document {doc_id}")

				except Exception as e:
					logger.error(f"Failed to ingest attachment {filename!r}: {e}")

	asyncio.run(_run())


@shared_task(name="darchiva.scanning.rescan_requested")
def handle_rescan_requested(
	batch_id: str,
	sample_id: str,
	project_id: str,
	reason: str,
	reviewer_id: str | None = None,
):
	"""
	Handle a QC-failed batch by creating a re-scan notification in the audit log
	and updating the batch status so the operator queue shows it.
	"""
	logger.info(_log_task(f"rescan_requested:batch={batch_id[:8]}"))

	async def _run():
		from papermerge.core.db.engine import get_async_session_maker
		from uuid import UUID as UUID
		from papermerge.core.features.scanning_projects.models import ScanningBatchModel
		from papermerge.core.features.audit.db.orm import AuditLog

		session_maker = get_async_session_maker()
		async with session_maker() as session:
			batch = await session.get(ScanningBatchModel, batch_id)
			if batch:
				batch.status = "rescan_requested"
				batch.notes = f"Re-scan requested: {reason}"
			log = AuditLog(
				table_name="scanning_batches",
				record_id=UUID(batch_id),
				operation="UPDATE",
				reason=f"rescan_requested: {reason}",
				new_values={
					"status": "rescan_requested",
					"sample_id": sample_id,
					"project_id": project_id,
					"reason": reason,
					"reviewer_id": reviewer_id,
				},
				application="scanner",
			)
			session.add(log)
			await session.commit()

	asyncio.run(_run())


@shared_task(name="darchiva.documents.index_embeddings")
def index_document_embeddings(document_id: str, user_id: str | None = None):
	"""
	Generate and store vector embeddings for a document's text content.

	Triggered after OCR completes. Uses the configured embedding provider
	(default: Ollama nomic-embed-text via ml server).
	"""
	logger.info(_log_task(f"index_embeddings:{document_id[:8]}"))

	async def _run():
		from papermerge.core.db.engine import get_async_session_maker
		from papermerge.core.config import get_settings
		from papermerge.core.search.semantic import SemanticSearch
		from papermerge.core.search.embeddings.ollama import OllamaEmbeddings
		from papermerge.core.features.document.db.orm import DocumentVersion
		from sqlalchemy import select
		from uuid import UUID

		cfg = get_settings()
		if not cfg.semantic_search_enabled:
			return

		session_maker = get_async_session_maker()
		async with session_maker() as session:
			stmt = (
				select(DocumentVersion)
				.where(DocumentVersion.document_id == document_id)
				.order_by(DocumentVersion.number.desc())
				.limit(1)
			)
			ver = (await session.execute(stmt)).scalar_one_or_none()
			if not ver or not ver.text:
				logger.info(f"index_embeddings: no text yet for {document_id[:8]}, skipping")
				return

			base_url = getattr(cfg, "embedding_base_url", cfg.litellm_base_url)
			model = getattr(cfg, "embedding_model", "nomic-embed-text")
			embedding_svc = OllamaEmbeddings(base_url=base_url, model=model)
			searcher = SemanticSearch(
				embedding_service=embedding_svc,
				session_factory=get_async_session_maker(),
			)
			count = await searcher.index_document(UUID(document_id), ver.id, ver.text)
			logger.info(f"index_embeddings: indexed {count} chunks for {document_id[:8]}")

	asyncio.run(_run())


@shared_task(name="darchiva.quality.assess_batch")
def assess_batch_quality(batch_id: str):
	"""Run quality assessment on all pages in a completed scan batch."""
	logger.info(_log_task(f"assess_batch_quality:{batch_id[:8]}"))

	async def _run():
		from papermerge.core.db.engine import get_async_session_maker
		from papermerge.core.features.scanning_projects.models import (
			ScanningBatchDocumentModel,
			ScanningBatchModel,
		)
		from sqlalchemy import select

		session_maker = get_async_session_maker()
		async with session_maker() as session:
			# Fetch all documents in this batch
			stmt = select(ScanningBatchDocumentModel).where(
				ScanningBatchDocumentModel.batch_id == batch_id
			)
			result = await session.execute(stmt)
			docs = result.scalars().all()

			if not docs:
				logger.info(f"assess_batch_quality: no documents in batch {batch_id[:8]}")
				return

			logger.info(
				f"assess_batch_quality: assessing {len(docs)} documents in batch {batch_id[:8]}"
			)

			try:
				from papermerge.core.features.quality.assessment import QualityAssessor
				assessor = QualityAssessor()
			except ImportError:
				logger.warning(
					"assess_batch_quality: QualityAssessor unavailable, skipping assessment"
				)
				return

			QUALITY_THRESHOLD = 60.0
			rejected_count = 0

			for doc in docs:
				# Locate the scanned image file via storage
				try:
					from papermerge.storage.base import get_storage_backend
					from papermerge.core import pathlib as plib

					storage = get_storage_backend()
					doc_id = str(doc.document_id)

					# Attempt to find the latest version image path
					from papermerge.core.features.document.db.orm import DocumentVersion
					ver_stmt = (
						select(DocumentVersion)
						.where(DocumentVersion.document_id == doc_id)
						.order_by(DocumentVersion.number.desc())
						.limit(1)
					)
					ver = (await session.execute(ver_stmt)).scalar_one_or_none()
					if not ver:
						logger.debug(f"assess_batch_quality: no version for doc {doc_id[:8]}")
						continue

					# Build file path and assess if accessible
					file_path = plib.docver_path(ver.id, file_name=getattr(ver, "file_name", "doc"))
					try:
						import tempfile, os
						local_bytes = await storage.download_file(str(file_path))
						with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
							tmp.write(local_bytes)
							tmp_path = tmp.name
						try:
							metrics = assessor.assess_image(tmp_path)
						finally:
							os.unlink(tmp_path)
					except Exception as dl_err:
						logger.debug(f"assess_batch_quality: cannot download {doc_id[:8]}: {dl_err}")
						continue

					quality_score = metrics.quality_score

					if quality_score < QUALITY_THRESHOLD:
						rejected_count += 1
						doc.has_issues = True
						doc.issue_details = {
							"quality_score": quality_score,
							"grade": metrics.grade.value,
							"issues": [
								{"metric": i.metric, "severity": i.severity, "message": i.message}
								for i in metrics.issues
							],
						}
						logger.info(
							f"assess_batch_quality: doc {doc_id[:8]} quality={quality_score:.1f} → rejected"
						)
					else:
						doc.quality_score = int(quality_score)

				except Exception as doc_err:
					logger.warning(
						f"assess_batch_quality: error assessing doc {doc.document_id}: {doc_err}"
					)

			# Update batch QC status
			batch = await session.get(ScanningBatchModel, batch_id)
			if batch:
				if rejected_count > 0:
					batch.notes = (
						(batch.notes or "")
						+ f" | QC: {rejected_count}/{len(docs)} pages failed quality check."
					)
				logger.info(
					f"assess_batch_quality: batch {batch_id[:8]} done "
					f"assessed={len(docs)} rejected={rejected_count}"
				)

			await session.commit()

	asyncio.run(_run())


@shared_task(name="darchiva.documents.extract_entities")
def extract_document_entities(document_id: str, user_id: str | None = None):
	"""
	Extract named entities (vendor, date, amount, invoice number) from a document
	using the local LiteLLM proxy (qwen2.5-VL).

	Stores results in document_metadata JSON column.
	"""
	logger.info(_log_task(f"extract_entities:{document_id[:8]}"))

	async def _run():
		import json
		from papermerge.core.db.engine import get_async_session_maker
		from papermerge.core.features.document.db.orm import Document, DocumentVersion
		from sqlalchemy import select

		session_maker = get_async_session_maker()
		async with session_maker() as session:
			stmt = (
				select(DocumentVersion)
				.where(DocumentVersion.document_id == document_id)
				.order_by(DocumentVersion.number.desc())
				.limit(1)
			)
			ver = (await session.execute(stmt)).scalar_one_or_none()
			if not ver or not ver.text:
				return

			text = ver.text[:8000]  # context limit

			try:
				import httpx
				payload = {
					"model": getattr(_get_settings(), "litellm_ner_model", "qwen2.5-VL"),
					"messages": [
						{
							"role": "system",
							"content": (
								"Extract named entities from the document text. "
								"Reply ONLY with a JSON object containing these keys: "
								"vendor (string or null), invoice_number (string or null), "
								"invoice_date (ISO date string or null), "
								"due_date (ISO date string or null), "
								"total_amount (float or null), currency (string or null), "
								"document_type (string: invoice|receipt|contract|report|other)."
							),
						},
						{"role": "user", "content": text},
					],
					"temperature": 0.0,
					"max_tokens": 512,
					"response_format": {"type": "json_object"},
				}
				from papermerge.core.config import get_settings as _get_settings
				_cfg = _get_settings()
				async with httpx.AsyncClient(timeout=30) as client:
					resp = await client.post(
						f"{_cfg.litellm_base_url}/chat/completions",
						json=payload,
						headers={
							"Authorization": f"Bearer {_cfg.litellm_api_key}",
							"Content-Type": "application/json",
						},
					)
					resp.raise_for_status()
					entities = json.loads(
						resp.json()["choices"][0]["message"]["content"]
					)

				doc = await session.get(Document, document_id)
				if doc:
					existing = doc.document_metadata or {}
					existing.update({"entities": entities})
					doc.document_metadata = existing
					from sqlalchemy.orm.attributes import flag_modified
					flag_modified(doc, "document_metadata")
					await session.commit()
					logger.info(f"Entities extracted for {document_id}: {list(entities.keys())}")

			except Exception as e:
				logger.warning(f"Entity extraction failed for {document_id}: {e}")

	asyncio.run(_run())


# ---------------------------------------------------------------------------
# Outbound webhook delivery
# ---------------------------------------------------------------------------

@shared_task(name="darchiva.webhooks.deliver", bind=True, max_retries=3, default_retry_delay=30)
def deliver_webhook(self, webhook_id: str, event_type: str, payload: dict):
	"""
	POST a signed webhook event to the configured URL.

	Headers sent:
	  X-Webhook-Event:     <event_type>
	  X-Webhook-Signature: sha256=<HMAC-SHA256 hex>
	  X-Webhook-Delivery:  <delivery_id>

	Retries up to 3 times on 5xx or network timeout.
	Records a WebhookDelivery row with the outcome.
	"""
	logger.info(_log_task(f"deliver_webhook:{webhook_id[:8]} event={event_type}"))

	import hashlib
	import hmac
	import json
	import uuid as _uuid
	from datetime import datetime, timezone

	async def _run():
		from papermerge.core.db.engine import get_async_session_maker
		from papermerge.core.features.webhooks.db.orm import OutboundWebhook, WebhookDelivery
		from sqlalchemy import select

		session_maker = get_async_session_maker()
		async with session_maker() as session:
			wh = await session.get(OutboundWebhook, _uuid.UUID(webhook_id))
			if not wh or not wh.is_active:
				logger.info(f"deliver_webhook: webhook {webhook_id[:8]} inactive or missing, skipping")
				return

			delivery_id = str(_uuid.uuid4())
			body_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
			sig = hmac.new(wh.secret.encode(), body_bytes, hashlib.sha256).hexdigest()

			delivery = WebhookDelivery(
				id=_uuid.UUID(delivery_id),
				webhook_id=wh.id,
				event_type=event_type,
				payload=payload,
			)
			session.add(delivery)
			await session.flush()  # get the row persisted before network call

			response_status: int | None = None
			response_body: str | None = None
			delivered_at: datetime | None = None

			try:
				import httpx
				headers = {
					"Content-Type": "application/json",
					"X-Webhook-Event": event_type,
					"X-Webhook-Signature": f"sha256={sig}",
					"X-Webhook-Delivery": delivery_id,
				}
				async with httpx.AsyncClient(timeout=15) as client:
					resp = await client.post(wh.url, content=body_bytes, headers=headers)
				response_status = resp.status_code
				response_body = resp.text[:4096]
				delivered_at = datetime.now(timezone.utc)
				logger.info(
					f"deliver_webhook: {webhook_id[:8]} event={event_type} "
					f"status={response_status}"
				)

				# Non-2xx 5xx triggers retry; 4xx is a caller error — don't retry
				if response_status >= 500:
					raise ValueError(f"server error {response_status}")

			except Exception as exc:
				logger.warning(f"deliver_webhook: attempt failed for {webhook_id[:8]}: {exc}")
				delivery.response_status = response_status
				delivery.response_body = str(exc)[:4096] if response_body is None else response_body
				await session.commit()
				# Celery retry — propagates as Retry exception, not re-raised here
				self.retry(exc=exc)
				return

			finally:
				# Always write the outcome we know so far
				delivery.response_status = response_status
				delivery.response_body = response_body
				delivery.delivered_at = delivered_at
				wh.last_delivery_at = delivered_at or datetime.now(timezone.utc)
				wh.last_delivery_status = response_status
				await session.commit()

	asyncio.run(_run())


@shared_task(name="darchiva.webhooks.deliver_ocr_complete")
def deliver_ocr_complete_webhook(document_id: str, tenant_id: str, user_id: str | None = None):
	"""
	Fetch the finished document's page_count from the latest version and
	dispatch a document.ocr_complete webhook event.
	"""
	logger.info(_log_task(f"deliver_ocr_complete:{document_id[:8]}"))

	async def _run():
		from papermerge.core.db.engine import get_async_session_maker
		from papermerge.core.features.document.db.orm import DocumentVersion
		from sqlalchemy import select

		session_maker = get_async_session_maker()
		async with session_maker() as session:
			stmt = (
				select(DocumentVersion)
				.where(DocumentVersion.document_id == document_id)
				.order_by(DocumentVersion.number.desc())
				.limit(1)
			)
			ver = (await session.execute(stmt)).scalar_one_or_none()
			page_count = ver.page_count if ver else 0

		dispatch_webhook_event(
			"document.ocr_complete",
			{
				"document_id": document_id,
				"tenant_id": tenant_id,
				"page_count": page_count,
				"user_id": user_id,
			},
			tenant_id=tenant_id,
		)

	asyncio.run(_run())


def dispatch_webhook_event(event_type: str, payload: dict, tenant_id: str) -> None:
	"""
	Query active webhooks subscribed to event_type for the given tenant and
	enqueue a deliver_webhook task for each.

	Safe to call from any async or sync context — uses send_task which is a
	no-op when Redis is absent.
	"""
	import asyncio as _asyncio

	async def _query_and_dispatch():
		from papermerge.core.db.engine import get_async_session_maker
		from papermerge.core.features.webhooks.db.orm import OutboundWebhook
		from sqlalchemy import select
		import uuid as _uuid

		session_maker = get_async_session_maker()
		async with session_maker() as session:
			result = await session.execute(
				select(OutboundWebhook).where(
					OutboundWebhook.tenant_id == _uuid.UUID(tenant_id),
					OutboundWebhook.is_active == True,  # noqa: E712
				)
			)
			webhooks = result.scalars().all()

		for wh in webhooks:
			if event_type in (wh.events or []):
				send_task(
					"darchiva.webhooks.deliver",
					kwargs={
						"webhook_id": str(wh.id),
						"event_type": event_type,
						"payload": payload,
					},
				)
				logger.debug(
					f"dispatch_webhook_event: queued {event_type} -> webhook {str(wh.id)[:8]}"
				)

	try:
		loop = _asyncio.get_event_loop()
		if loop.is_running():
			# We're inside an async context — schedule as a fire-and-forget
			loop.create_task(_query_and_dispatch())
		else:
			loop.run_until_complete(_query_and_dispatch())
	except RuntimeError:
		_asyncio.run(_query_and_dispatch())


# ---------------------------------------------------------------------------
# Retention policy sweep
# ---------------------------------------------------------------------------


@shared_task(name="darchiva.retention.sweep")
def sweep_retention_policies():
	"""Daily sweep: find documents matching active retention policies and act on them."""
	logger.info(_log_task("sweep_retention_policies"))
	import asyncio as _asyncio

	async def _run():
		from datetime import datetime, timedelta

		from sqlalchemy import and_, select

		from papermerge.core.db.engine import get_async_session_maker
		from papermerge.core.features.retention.db.orm import RetentionPolicy

		async_session = get_async_session_maker()
		async with async_session() as session:
			stmt = select(RetentionPolicy).where(RetentionPolicy.is_active == True)  # noqa: E712
			result = await session.execute(stmt)
			policies = result.scalars().all()

			total_processed = 0
			for policy in policies:
				try:
					count = await _apply_policy(session, policy)
					policy.last_run_at = datetime.utcnow() if count >= 0 else policy.last_run_at
					policy.docs_processed = (policy.docs_processed or 0) + max(count, 0)
					total_processed += max(count, 0)
				except Exception as exc:
					logger.error(
						f"retention sweep error policy={policy.id}: {exc}", exc_info=True
					)

			await session.commit()
			logger.info(f"retention sweep complete: processed {total_processed} documents")

	async def _apply_policy(session, policy: "RetentionPolicy") -> int:
		from datetime import datetime as _dt, timedelta

		from sqlalchemy import and_, select

		from papermerge.core.features.document.db.orm import Document

		cutoff = _dt.utcnow() - timedelta(days=policy.after_days)

		stmt = select(Document).where(
			Document.tenant_id == policy.tenant_id,
			Document.created_at <= cutoff,
			Document.legal_hold == False,  # noqa: E712
		)
		if policy.applies_to_project_id:
			stmt = stmt.where(Document.scanning_project_id == policy.applies_to_project_id)
		if policy.applies_to_document_type:
			# Join via document_type name if available; filter loosely
			stmt = stmt.where(Document.document_type_id != None)  # noqa: E711

		result = await session.execute(stmt)
		docs = result.scalars().all()

		count = 0
		for doc in docs:
			try:
				if policy.policy_type == "delete":
					await session.delete(doc)
					count += 1
				elif policy.policy_type == "archive":
					# Mark document as archived via a flag if available, else log
					if hasattr(doc, "is_archived"):
						doc.is_archived = True
						count += 1
					else:
						logger.debug(
							f"retention archive: document model has no is_archived field, "
							f"skipping doc={doc.id}"
						)
				elif policy.policy_type == "move" and policy.destination_folder_id:
					doc.parent_id = policy.destination_folder_id
					count += 1
			except Exception as exc:
				logger.error(
					f"retention apply error doc={doc.id} policy={policy.id}: {exc}", exc_info=True
				)

		return count

	asyncio.run(_run())


@shared_task(name="darchiva.export.bulk_export")
def bulk_export_documents(
	job_id: str,
	document_ids: list[str],
	include_metadata: bool = True,
	include_original: bool = True,
):
	"""Build a ZIP archive of the requested documents and upload it to storage.

	Progress and final download URL are written to Redis under the key
	``bulk_export:{job_id}`` as a hash with fields:
	  status      – queued | processing | complete | failed
	  progress    – float 0.0–1.0
	  download_url – presigned URL (set when complete)
	  error       – error message (set when failed)
	"""
	logger.info(_log_task(f"bulk_export:{job_id[:8]} docs={len(document_ids)}"))

	import asyncio as _asyncio
	import csv
	import io
	import zipfile

	async def _run():
		from papermerge.core.db.engine import get_async_session_maker
		from papermerge.core.features.document.db.orm import Document, DocumentVersion
		from papermerge.core.features.document_types.db.orm import DocumentType
		from papermerge.storage.base import get_storage_backend
		from papermerge.core import pathlib as plib
		from papermerge.core.config import get_settings as _get_settings
		from sqlalchemy import select
		import redis as _redis

		cfg = _get_settings()
		redis_url = getattr(cfg, "redis_url", None) or getattr(cfg, "pm_redis_url", None)

		def _redis_update(fields: dict):
			if not redis_url:
				return
			try:
				r = _redis.from_url(redis_url, decode_responses=True)
				r.hset(f"bulk_export:{job_id}", mapping=fields)
				r.expire(f"bulk_export:{job_id}", 7200)  # keep for 2 h
			except Exception as re:
				logger.warning(f"bulk_export Redis write failed: {re}")

		_redis_update({"status": "processing", "progress": "0.0"})

		session_maker = get_async_session_maker()
		storage = get_storage_backend()

		try:
			async with session_maker() as session:
				zip_buf = io.BytesIO()
				metadata_rows: list[dict] = []
				total = len(document_ids)

				with zipfile.ZipFile(zip_buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
					for idx, doc_id in enumerate(document_ids):
						try:
							doc_stmt = select(Document).where(Document.id == doc_id)
							doc = (await session.execute(doc_stmt)).scalar_one_or_none()
							if doc is None:
								logger.warning(f"bulk_export: document {doc_id} not found, skipping")
								continue

							ver_stmt = (
								select(DocumentVersion)
								.where(DocumentVersion.document_id == doc_id)
								.order_by(DocumentVersion.number.desc())
								.limit(1)
							)
							ver = (await session.execute(ver_stmt)).scalar_one_or_none()

							doc_type_name = ""
							if doc.document_type_id:
								dt = await session.get(DocumentType, doc.document_type_id)
								doc_type_name = dt.name if dt else str(doc.document_type_id)

							quality = None
							if doc.document_metadata:
								quality = doc.document_metadata.get("quality_score")

							metadata_rows.append({
								"id": doc_id,
								"title": doc.title,
								"document_type": doc_type_name,
								"created_at": doc.created_at.isoformat() if doc.created_at else "",
								"page_count": ver.page_count if ver else 0,
								"quality_score": quality if quality is not None else "",
							})

							if include_original and ver:
								try:
									file_name = getattr(ver, "file_name", None) or f"{doc_id}.pdf"
									object_key = str(plib.docver_path(ver.id, file_name=file_name))
									file_bytes = storage.download_file(object_key)
									safe_title = doc.title.replace("/", "_").replace("\\", "_")[:100]
									zip_entry = f"{safe_title}_{doc_id[:8]}/{file_name}"
									zf.writestr(zip_entry, file_bytes)
								except Exception as fe:
									logger.warning(f"bulk_export: could not fetch file for {doc_id}: {fe}")

						except Exception as de:
							logger.warning(f"bulk_export: error processing doc {doc_id}: {de}")

						# Reserve last 10% for upload step
						progress = 0.9 * (idx + 1) / total
						_redis_update({"progress": str(round(progress, 3))})

					if include_metadata and metadata_rows:
						csv_buf = io.StringIO()
						writer = csv.DictWriter(
							csv_buf,
							fieldnames=["id", "title", "document_type", "created_at", "page_count", "quality_score"],
						)
						writer.writeheader()
						writer.writerows(metadata_rows)
						zf.writestr("metadata.csv", csv_buf.getvalue())

				zip_bytes = zip_buf.getvalue()
				export_key = f"exports/{job_id}/export.zip"
				await storage.upload_bytes(zip_bytes, export_key, "application/zip")

				_redis_update({"progress": "0.95"})

				try:
					download_url = storage.sign_url(export_key, valid_for=3600)
				except Exception:
					download_url = f"/api/v1/storage/exports/{job_id}/export.zip"

				_redis_update({
					"status": "complete",
					"progress": "1.0",
					"download_url": download_url,
				})
				logger.info(f"bulk_export:{job_id[:8]} complete url={download_url[:80]}")

		except Exception as e:
			logger.error(f"bulk_export:{job_id[:8]} failed: {e}", exc_info=True)
			_redis_update({"status": "failed", "error": str(e)[:500]})
			raise

	_asyncio.run(_run())


@shared_task(name="darchiva.retention.run_policy")
def run_retention_policy_task(policy_id: str, dry_run: bool = False):
	"""Run a single retention policy by ID (triggered manually or from the API)."""
	logger.info(_log_task(f"run_retention_policy_task:{policy_id[:8]} dry_run={dry_run}"))
	import asyncio as _asyncio

	async def _run():
		from datetime import datetime as _dt, timedelta

		from sqlalchemy import select

		from papermerge.core.db.engine import get_async_session_maker
		from papermerge.core.features.document.db.orm import Document
		from papermerge.core.features.retention.db.orm import RetentionPolicy

		async_session = get_async_session_maker()
		async with async_session() as session:
			policy = await session.get(RetentionPolicy, policy_id)
			if not policy:
				logger.error(f"run_retention_policy_task: policy {policy_id!r} not found")
				return

			cutoff = _dt.utcnow() - timedelta(days=policy.after_days)
			stmt = select(Document).where(
				Document.tenant_id == policy.tenant_id,
				Document.created_at <= cutoff,
				Document.legal_hold == False,  # noqa: E712
			)
			if policy.applies_to_project_id:
				stmt = stmt.where(Document.scanning_project_id == policy.applies_to_project_id)

			result = await session.execute(stmt)
			docs = result.scalars().all()
			count = len(docs)

			if not dry_run:
				for doc in docs:
					if policy.policy_type == "delete":
						await session.delete(doc)
					elif policy.policy_type == "move" and policy.destination_folder_id:
						doc.parent_id = policy.destination_folder_id
					elif policy.policy_type == "archive" and hasattr(doc, "is_archived"):
						doc.is_archived = True

				policy.last_run_at = _dt.utcnow()
				policy.docs_processed = (policy.docs_processed or 0) + count
				await session.commit()

			logger.info(
				f"run_retention_policy_task: policy={policy_id[:8]} "
				f"matched={count} dry_run={dry_run}"
			)

	_asyncio.run(_run())


# ---------------------------------------------------------------------------
# ZIP bulk import — per-file worker task
# ---------------------------------------------------------------------------

@shared_task(name="darchiva.ingestion.process_bulk_file")
def process_bulk_file(
	job_id: str,
	file_path: str,
	file_name: str,
	file_size: int,
	total_files: int,
	destination_folder_id: str | None = None,
	project_id: str | None = None,
	tenant_id: str | None = None,
	user_id: str | None = None,
):
	"""Process one file extracted from a bulk ZIP upload.

	Updates the Redis job counters atomically.  Cleans up the extracted temp
	file after it has been handed off to the storage/OCR pipeline.
	"""
	logger.info(_log_task(f"process_bulk_file:job={job_id[:8]} file={file_name}"))

	import json
	import os
	from pathlib import Path

	# ── Redis helpers (inline, no circular import) ───────────────────────────
	def _redis_client():
		try:
			from papermerge.core.config import get_settings
			settings = get_settings()
			broker_url = getattr(settings, "broker_url", None) or os.environ.get("CELERY_BROKER_URL", "")
			if not broker_url or not broker_url.startswith("redis"):
				return None
			import redis as _redis
			c = _redis.from_url(broker_url, decode_responses=True)
			c.ping()
			return c
		except Exception:
			return None

	def _job_key(jid: str) -> str:
		return f"bulk_upload:{jid}"

	def _mark_done(r, jid: str, success: bool, error_detail: str | None = None):
		if r is None:
			return
		key = _job_key(jid)
		pipe = r.pipeline()
		if success:
			pipe.hincrby(key, "processed", 1)
		else:
			pipe.hincrby(key, "failed", 1)
			if error_detail:
				raw = r.hget(key, "failures") or "[]"
				try:
					failures = json.loads(raw)
				except (json.JSONDecodeError, ValueError):
					failures = []
				failures.append({"file": error_detail, "error": error_detail})
				pipe.hset(key, "failures", json.dumps(failures[-200:]))  # cap list
		pipe.execute()

		# Check if job is fully done
		data = r.hgetall(key)
		total = int(data.get("total_files", 0))
		processed = int(data.get("processed", 0))
		failed = int(data.get("failed", 0))
		if processed + failed >= total and total > 0:
			from datetime import datetime, timezone
			final_status = "completed" if failed == 0 else "partial"
			r.hset(key, mapping={
				"status": final_status,
				"completed_at": datetime.now(timezone.utc).isoformat(),
			})

	# ── Main processing ──────────────────────────────────────────────────────
	r = _redis_client()

	# Mark job as processing on first file processed
	if r:
		r.hsetnx(_job_key(job_id), "status", "processing")

	fp = Path(file_path)

	try:
		if not fp.is_file():
			raise FileNotFoundError(f"Extracted file missing: {file_path}")

		# Queue through the standard OCR pipeline
		send_task(
			"process_upload",
			kwargs={
				"file_path": str(fp),
				"file_name": file_name,
				"file_size": file_size,
				"source_id": None,
				"apply_ocr": True,
				"destination_folder_id": destination_folder_id,
				"project_id": project_id,
				"tenant_id": tenant_id,
				"user_id": user_id,
			},
		)
		_mark_done(r, job_id, success=True)
		logger.info("process_bulk_file: queued %s for OCR", file_name)

	except Exception as exc:
		_mark_done(r, job_id, success=False, error_detail=f"{file_name}: {exc}")
		logger.error("process_bulk_file: failed %s: %s", file_name, exc)
		# Do not re-raise — one failure must not abort sibling tasks
	finally:
		# Remove the extracted temp file to free disk space
		try:
			fp.unlink(missing_ok=True)
		except Exception:
			pass

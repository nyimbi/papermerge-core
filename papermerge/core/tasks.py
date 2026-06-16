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

# (c) Copyright Datacraft, 2026
"""Document ingestion service for watched folders and email."""
import logging
import asyncio
from pathlib import Path
from uuid import UUID
from datetime import datetime, timezone
from typing import Callable, Awaitable
from dataclasses import dataclass
from enum import Enum

from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from papermerge.core.features.ingestion.db.orm import IngestionSource, IngestionJob

logger = logging.getLogger(__name__)


class IngestionMode(str, Enum):
	ARCHIVAL = "archival"
	OPERATIONAL = "operational"


class JobStatus(str, Enum):
	PENDING = "pending"
	PROCESSING = "processing"
	COMPLETED = "completed"
	FAILED = "failed"


@dataclass
class IngestionResult:
	"""Result of document ingestion."""
	success: bool
	document_id: UUID | None = None
	job_id: UUID | None = None
	message: str | None = None
	metadata: dict | None = None


class IngestionService:
	"""Handle document ingestion from multiple sources."""

	def __init__(
		self,
		db: Session,
		document_processor: Callable[[bytes, dict], Awaitable[UUID]] | None = None,
	):
		self.db = db
		self.document_processor = document_processor
		self._watchers: dict[UUID, asyncio.Task] = {}

	async def ingest_file(
		self,
		tenant_id: UUID,
		file_path: Path | str,
		source_id: UUID | None = None,
		mode: IngestionMode = IngestionMode.OPERATIONAL,
		metadata: dict | None = None,
	) -> IngestionResult:
		"""Ingest a single file."""
		file_path = Path(file_path)

		if not file_path.exists():
			return IngestionResult(
				success=False,
				message=f"File not found: {file_path}",
			)

		# Create ingestion job
		job = await self._create_job(
			tenant_id=tenant_id,
			source_id=source_id,
			source_type="file",
			source_path=str(file_path),
			mode=mode.value,
		)

		try:
			# Read file content
			content = file_path.read_bytes()

			# Build metadata
			doc_metadata = {
				"original_filename": file_path.name,
				"file_size": len(content),
				"ingestion_mode": mode.value,
				"ingestion_source": "file",
				**(metadata or {}),
			}

			# Process document
			if self.document_processor:
				document_id = await self.document_processor(content, doc_metadata)
			else:
				document_id = await self._default_process(tenant_id, content, doc_metadata)

			# Update job
			job.status = JobStatus.COMPLETED.value
			job.document_id = document_id
			job.completed_at = datetime.now(timezone.utc)
			self.db.commit()

			return IngestionResult(
				success=True,
				document_id=document_id,
				job_id=job.id,
				metadata=doc_metadata,
			)

		except Exception as e:
			logger.error(f"Ingestion failed for {file_path}: {e}")
			job.status = JobStatus.FAILED.value
			job.error_message = str(e)
			job.completed_at = datetime.now(timezone.utc)
			self.db.commit()

			return IngestionResult(
				success=False,
				job_id=job.id,
				message=str(e),
			)

	async def ingest_email(
		self,
		tenant_id: UUID,
		email_data: dict,
		source_id: UUID | None = None,
		mode: IngestionMode = IngestionMode.OPERATIONAL,
	) -> list[IngestionResult]:
		"""Ingest documents from email attachments."""
		results = []

		# Create job for email
		job = await self._create_job(
			tenant_id=tenant_id,
			source_id=source_id,
			source_type="email",
			source_path=email_data.get("message_id", "unknown"),
			mode=mode.value,
		)

		try:
			attachments = email_data.get("attachments", [])

			for attachment in attachments:
				filename = attachment.get("filename", "unknown")
				content = attachment.get("content")  # bytes

				if not content:
					continue

				# Build metadata from email
				doc_metadata = {
					"original_filename": filename,
					"file_size": len(content),
					"ingestion_mode": mode.value,
					"ingestion_source": "email",
					"email_from": email_data.get("from"),
					"email_to": email_data.get("to"),
					"email_subject": email_data.get("subject"),
					"email_date": email_data.get("date"),
					"email_message_id": email_data.get("message_id"),
				}

				# Process document
				if self.document_processor:
					document_id = await self.document_processor(content, doc_metadata)
				else:
					document_id = await self._default_process(tenant_id, content, doc_metadata)

				results.append(IngestionResult(
					success=True,
					document_id=document_id,
					job_id=job.id,
					metadata=doc_metadata,
				))

			# Update job
			job.status = JobStatus.COMPLETED.value
			job.documents_processed = len(results)
			job.completed_at = datetime.now(timezone.utc)
			self.db.commit()

		except Exception as e:
			logger.error(f"Email ingestion failed: {e}")
			job.status = JobStatus.FAILED.value
			job.error_message = str(e)
			job.completed_at = datetime.now(timezone.utc)
			self.db.commit()

			results.append(IngestionResult(
				success=False,
				job_id=job.id,
				message=str(e),
			))

		return results

	async def start_folder_watcher(
		self,
		source_id: UUID,
	) -> bool:
		"""Start watching a folder for new files."""
		source = self.db.get(IngestionSource, source_id)
		if not source or source.source_type != "watched_folder":
			return False

		if source_id in self._watchers:
			return True  # Already watching

		# Create watcher task
		task = asyncio.create_task(
			self._watch_folder(source_id, source.config)
		)
		self._watchers[source_id] = task

		# Update source status
		source.is_active = True
		self.db.commit()

		logger.info(f"Started folder watcher for source {source_id}")
		return True

	async def stop_folder_watcher(self, source_id: UUID) -> bool:
		"""Stop watching a folder."""
		if source_id not in self._watchers:
			return False

		self._watchers[source_id].cancel()
		del self._watchers[source_id]

		# Update source status
		source = self.db.get(IngestionSource, source_id)
		if source:
			source.is_active = False
			self.db.commit()

		logger.info(f"Stopped folder watcher for source {source_id}")
		return True

	async def create_source(
		self,
		tenant_id: UUID,
		name: str,
		source_type: str,
		config: dict,
		mode: IngestionMode = IngestionMode.OPERATIONAL,
		target_folder_id: UUID | None = None,
	) -> IngestionSource:
		"""Create an ingestion source."""
		source = IngestionSource(
			tenant_id=tenant_id,
			name=name,
			source_type=source_type,
			config=config,
			mode=mode.value,
			target_folder_id=target_folder_id,
			is_active=False,
		)
		self.db.add(source)
		self.db.commit()
		self.db.refresh(source)
		return source

	async def get_sources(self, tenant_id: UUID) -> list[IngestionSource]:
		"""Get all ingestion sources for tenant."""
		stmt = select(IngestionSource).where(
			IngestionSource.tenant_id == tenant_id
		)
		return list(self.db.scalars(stmt))

	async def get_jobs(
		self,
		tenant_id: UUID,
		source_id: UUID | None = None,
		status: str | None = None,
		limit: int = 100,
	) -> list[IngestionJob]:
		"""Get ingestion jobs."""
		conditions = [IngestionJob.tenant_id == tenant_id]

		if source_id:
			conditions.append(IngestionJob.source_id == source_id)
		if status:
			conditions.append(IngestionJob.status == status)

		stmt = select(IngestionJob).where(
			and_(*conditions)
		).order_by(IngestionJob.created_at.desc()).limit(limit)

		return list(self.db.scalars(stmt))

	async def _create_job(
		self,
		tenant_id: UUID,
		source_id: UUID | None,
		source_type: str,
		source_path: str,
		mode: str,
	) -> IngestionJob:
		"""Create an ingestion job record."""
		job = IngestionJob(
			tenant_id=tenant_id,
			source_id=source_id,
			source_type=source_type,
			source_path=source_path,
			mode=mode,
			status=JobStatus.PROCESSING.value,
		)
		self.db.add(job)
		self.db.commit()
		self.db.refresh(job)
		return job

	async def _watch_folder(
		self,
		source_id: UUID,
		config: dict,
	) -> None:
		"""Watch folder for new files."""
		folder_path = Path(config.get("path", ""))
		poll_interval = config.get("poll_interval", 60)
		file_patterns = config.get("patterns", ["*.pdf", "*.tiff", "*.png", "*.jpg"])
		move_after_process = config.get("move_after_process", True)
		processed_folder = config.get("processed_folder", "processed")

		if not folder_path.exists():
			logger.error(f"Watch folder does not exist: {folder_path}")
			return

		processed_path = folder_path / processed_folder
		if move_after_process:
			processed_path.mkdir(exist_ok=True)

		processed_files: set[str] = set()

		while True:
			try:
				source = self.db.get(IngestionSource, source_id)
				if not source or not source.is_active:
					break

				# Find new files
				for pattern in file_patterns:
					for file_path in folder_path.glob(pattern):
						if file_path.is_file() and str(file_path) not in processed_files:
							# Ingest file
							mode = IngestionMode(source.mode)
							result = await self.ingest_file(
								tenant_id=source.tenant_id,
								file_path=file_path,
								source_id=source_id,
								mode=mode,
							)

							processed_files.add(str(file_path))

							if result.success and move_after_process:
								# Move to processed folder
								dest = processed_path / file_path.name
								file_path.rename(dest)

				# Update last check time
				source.last_check_at = datetime.now(timezone.utc)
				self.db.commit()

				await asyncio.sleep(poll_interval)

			except asyncio.CancelledError:
				break
			except Exception as e:
				logger.error(f"Error in folder watcher {source_id}: {e}")
				await asyncio.sleep(poll_interval)

	async def _default_process(
		self,
		tenant_id: UUID,
		content: bytes,
		metadata: dict,
	) -> UUID:
		"""Default document processing - create document and trigger OCR."""
		import tempfile
		from pathlib import Path
		from uuid_extensions import uuid7
		from sqlalchemy.ext.asyncio import AsyncSession

		from papermerge.core.features.document.db import api as doc_dbapi
		from papermerge.core.features.document import schema as doc_schema
		from papermerge.core.features.nodes.db.api import get_node_by_id
		from papermerge.core.lib.mime import detect_and_validate_mime_type
		from papermerge.core.tasks import send_task
		from papermerge.core import pathlib as plib
		from papermerge.storage.base import get_storage_backend

		doc_id = uuid7()
		document_version_id = uuid7()
		filename = metadata.get("original_filename", f"document_{doc_id}.pdf")

		# Detect mime type
		mime_type = detect_and_validate_mime_type(
			content[:8192],
			filename,
			validate_structure=False
		)

		# Get tenant's inbox folder for ingested documents
		from papermerge.core.features.tenants.db.orm import Tenant
		tenant = self.db.get(Tenant, tenant_id)
		if not tenant:
			raise ValueError(f"Tenant not found: {tenant_id}")

		# Use tenant's default inbox or a configured ingestion folder
		parent_id = tenant.inbox_folder_id

		# Upload to storage
		storage = get_storage_backend()
		object_key = str(plib.docver_path(document_version_id, file_name=filename))

		with tempfile.NamedTemporaryFile(delete=False) as tmp:
			tmp.write(content)
			tmp_path = Path(tmp.name)

		try:
			await storage.upload_file_from_path(
				file_path=tmp_path,
				object_key=object_key,
				content_type=str(mime_type),
			)
		finally:
			tmp_path.unlink(missing_ok=True)

		# Create document in database
		new_document = doc_schema.NewDocument(
			id=doc_id,
			title=filename,
			lang=metadata.get("language", "eng"),
			parent_id=parent_id,
			size=len(content),
			page_count=0,
			ocr=metadata.get("ocr", True),
			file_name=filename,
			ctype="document",
		)

		# Need async session for document creation
		from papermerge.core.db.engine import get_async_session_maker
		async_session = get_async_session_maker()

		async with async_session() as session:
			doc = await doc_dbapi.create_document(
				session,
				new_document,
				mime_type=mime_type,
				document_version_id=document_version_id
			)

		# Trigger post-upload processing (page extraction, OCR)
		send_task(
			"process_upload",
			kwargs={
				"document_id": str(doc_id),
				"document_version_id": str(document_version_id),
				"lang": metadata.get("language", "eng"),
				"user_id": str(metadata.get("user_id", tenant.owner_id)),
			},
		)

		logger.info(f"Created document {doc_id} from ingestion: {filename}")
		return doc_id

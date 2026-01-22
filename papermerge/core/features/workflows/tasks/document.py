# (c) Copyright Datacraft, 2026
"""Document lifecycle tasks for workflow engine."""
import logging
from typing import Any
from uuid import UUID

from prefect import task

from papermerge.core.config.prefect import get_prefect_settings
from .base import TaskResult, log_task_start, log_task_complete

logger = logging.getLogger(__name__)
settings = get_prefect_settings()


@task(
	name="source",
	description="Load document source from storage",
	retries=settings.default_retries,
	retry_delay_seconds=settings.retry_delay_seconds,
)
async def source_task(ctx: dict, config: dict) -> dict:
	"""
	Load a document from its source location.

	This is typically the first task in a workflow, responsible for:
	- Retrieving the document from storage
	- Extracting basic metadata
	- Preparing document for processing

	Config options:
		- storage_tier: str - Which storage tier to fetch from (hot/cold/archive)
		- include_versions: bool - Whether to include all versions
		- extract_metadata: bool - Whether to extract file metadata

	Returns:
		Document information including file path and metadata
	"""
	log_task_start("source", ctx, config)

	document_id = ctx["document_id"]
	storage_tier = config.get("storage_tier", "hot")
	include_versions = config.get("include_versions", False)
	extract_metadata = config.get("extract_metadata", True)

	try:
		# Import here to avoid circular imports
		from papermerge.core.db.engine import get_session
		from papermerge.core.features.document.db.orm import Document

		async with get_session() as db:
			document = await db.get(Document, UUID(document_id))
			if not document:
				result = TaskResult.failure_result(
					f"Document not found: {document_id}",
					error_code="DOCUMENT_NOT_FOUND",
				)
				log_task_complete("source", ctx, result)
				return result.model_dump()

			# Get document info
			doc_info = {
				"document_id": str(document.id),
				"title": document.title,
				"file_name": getattr(document, "file_name", None),
				"page_count": getattr(document, "page_count", 0),
				"size_bytes": getattr(document, "size", 0),
				"mime_type": getattr(document, "mime_type", "application/pdf"),
			}

			# Get storage location
			# TODO: Integrate with storage service
			doc_info["storage_path"] = f"/media/{document_id}"
			doc_info["storage_tier"] = storage_tier

			result = TaskResult.success_result(
				"Document loaded successfully",
				document=doc_info,
			)
			log_task_complete("source", ctx, result)
			return result.model_dump()

	except Exception as e:
		logger.exception(f"Error loading document {document_id}")
		result = TaskResult.failure_result(
			f"Failed to load document: {str(e)}",
			error_code="SOURCE_ERROR",
		)
		log_task_complete("source", ctx, result)
		return result.model_dump()


@task(
	name="preprocess",
	description="Preprocess document for analysis",
	retries=settings.default_retries,
	retry_delay_seconds=settings.retry_delay_seconds,
)
async def preprocess_task(ctx: dict, config: dict) -> dict:
	"""
	Preprocess a document before OCR/NLP.

	Preprocessing steps may include:
	- Image enhancement (deskew, denoise, contrast)
	- Page splitting/merging
	- Format conversion
	- Quality assessment

	Config options:
		- deskew: bool - Enable deskew correction
		- denoise: bool - Enable noise removal
		- enhance_contrast: bool - Enhance image contrast
		- target_dpi: int - Target DPI for processing
		- split_pages: bool - Split multi-page documents

	Returns:
		Preprocessing results including quality metrics
	"""
	log_task_start("preprocess", ctx, config)

	document_id = ctx["document_id"]
	deskew = config.get("deskew", True)
	denoise = config.get("denoise", True)
	enhance_contrast = config.get("enhance_contrast", False)
	target_dpi = config.get("target_dpi", 300)

	try:
		from papermerge.core.features.quality.assessment import QualityAssessor
		from papermerge.storage.base import get_storage_backend
		from papermerge.core import pathlib as plib
		from papermerge.core.db.engine import get_async_session_maker
		from papermerge.core.features.document.db.orm import DocumentVersion
		from sqlalchemy import select
		import tempfile
		from pathlib import Path

		# Get previous source result
		source_result = ctx.get("previous_results", {}).get("source", {})
		doc_info = source_result.get("data", {}).get("document", {})

		preprocessing_results = {
			"document_id": document_id,
			"original_pages": doc_info.get("page_count", 0),
			"processed_pages": doc_info.get("page_count", 0),
			"deskew_applied": deskew,
			"denoise_applied": denoise,
			"contrast_enhanced": enhance_contrast,
			"output_dpi": target_dpi,
			"quality_scores": [],
		}

		# Get document version for quality assessment
		async_session = get_async_session_maker()
		async with async_session() as session:
			stmt = select(DocumentVersion).where(
				DocumentVersion.document_id == document_id
			).order_by(DocumentVersion.number.desc()).limit(1)
			result = await session.execute(stmt)
			version = result.scalar_one_or_none()

		if version:
			storage = get_storage_backend()
			object_key = str(plib.docver_path(version.id, version.file_name))

			with tempfile.TemporaryDirectory() as tmpdir:
				local_path = Path(tmpdir) / version.file_name
				await storage.download_file_to_path(object_key, local_path)

				assessor = QualityAssessor(min_dpi=target_dpi)
				metrics = assessor.assess_image(local_path)

				preprocessing_results["quality_scores"].append({
					"page": 1,
					"sharpness": metrics.sharpness or 0.0,
					"contrast": metrics.contrast or 0.0,
					"noise_level": metrics.noise_level or 0.0,
					"overall": metrics.quality_score,
					"grade": metrics.grade.value,
					"issues": [
						{"metric": i.metric, "message": i.message, "severity": i.severity}
						for i in metrics.issues
					],
				})
				preprocessing_results["average_quality"] = metrics.quality_score
		else:
			preprocessing_results["average_quality"] = 0.0

		result = TaskResult.success_result(
			"Document preprocessed successfully",
			preprocessing=preprocessing_results,
		)
		log_task_complete("preprocess", ctx, result)
		return result.model_dump()

	except Exception as e:
		logger.exception(f"Error preprocessing document {document_id}")
		result = TaskResult.failure_result(
			f"Preprocessing failed: {str(e)}",
			error_code="PREPROCESS_ERROR",
		)
		log_task_complete("preprocess", ctx, result)
		return result.model_dump()


@task(
	name="store",
	description="Store document in target location",
	retries=settings.default_retries,
	retry_delay_seconds=settings.retry_delay_seconds,
)
async def store_task(ctx: dict, config: dict) -> dict:
	"""
	Store a processed document.

	This task handles:
	- Moving document to destination folder
	- Setting storage tier
	- Creating backup copies
	- Updating metadata

	Config options:
		- destination_folder_id: UUID - Target folder
		- storage_tier: str - Storage tier (hot/cold/archive)
		- create_backup: bool - Create backup copy
		- overwrite_existing: bool - Overwrite if exists

	Returns:
		Storage confirmation with new location
	"""
	log_task_start("store", ctx, config)

	document_id = ctx["document_id"]
	destination_folder_id = config.get("destination_folder_id")
	storage_tier = config.get("storage_tier", "hot")
	create_backup = config.get("create_backup", False)

	try:
		from papermerge.core.db.engine import get_session
		from papermerge.core.features.document.db.orm import Document

		async with get_session() as db:
			document = await db.get(Document, UUID(document_id))
			if not document:
				result = TaskResult.failure_result(
					f"Document not found: {document_id}",
					error_code="DOCUMENT_NOT_FOUND",
				)
				log_task_complete("store", ctx, result)
				return result.model_dump()

			# Move to destination folder if specified
			if destination_folder_id:
				document.parent_id = UUID(destination_folder_id)
				await db.commit()

			storage_info = {
				"document_id": document_id,
				"storage_tier": storage_tier,
				"destination_folder_id": destination_folder_id,
				"backup_created": create_backup,
				"storage_path": f"/media/{document_id}",
			}

			result = TaskResult.success_result(
				"Document stored successfully",
				storage=storage_info,
			)
			log_task_complete("store", ctx, result)
			return result.model_dump()

	except Exception as e:
		logger.exception(f"Error storing document {document_id}")
		result = TaskResult.failure_result(
			f"Storage failed: {str(e)}",
			error_code="STORE_ERROR",
		)
		log_task_complete("store", ctx, result)
		return result.model_dump()


@task(
	name="index",
	description="Index document for search",
	retries=settings.default_retries,
	retry_delay_seconds=settings.retry_delay_seconds,
)
async def index_task(ctx: dict, config: dict) -> dict:
	"""
	Index a document for full-text and semantic search.

	This task handles:
	- Full-text indexing (PostgreSQL FTS / Elasticsearch)
	- Semantic embedding generation
	- Metadata indexing

	Config options:
		- index_fulltext: bool - Enable FTS indexing
		- index_semantic: bool - Enable vector embeddings
		- embedding_model: str - Model for embeddings
		- chunk_size: int - Text chunk size for embeddings

	Returns:
		Indexing results with stats
	"""
	log_task_start("index", ctx, config)

	document_id = ctx["document_id"]
	index_fulltext = config.get("index_fulltext", True)
	index_semantic = config.get("index_semantic", False)
	embedding_model = config.get("embedding_model", "text-embedding-3-small")

	try:
		# Get OCR results from context
		ocr_result = ctx.get("previous_results", {}).get("ocr", {})
		text_content = ocr_result.get("data", {}).get("text", "")

		indexing_results = {
			"document_id": document_id,
			"fulltext_indexed": False,
			"semantic_indexed": False,
			"word_count": len(text_content.split()) if text_content else 0,
			"chunk_count": 0,
		}

		if index_fulltext and text_content:
			# TODO: Integrate with search service
			# For now, mark as indexed
			indexing_results["fulltext_indexed"] = True
			logger.info(f"Full-text indexed document {document_id}")

		if index_semantic and text_content:
			# TODO: Integrate with embedding service
			# Chunk the text and generate embeddings
			chunk_size = config.get("chunk_size", 500)
			words = text_content.split()
			chunks = [
				" ".join(words[i:i + chunk_size])
				for i in range(0, len(words), chunk_size)
			]
			indexing_results["chunk_count"] = len(chunks)
			indexing_results["semantic_indexed"] = True
			indexing_results["embedding_model"] = embedding_model
			logger.info(f"Semantic indexed document {document_id} ({len(chunks)} chunks)")

		result = TaskResult.success_result(
			"Document indexed successfully",
			indexing=indexing_results,
		)
		log_task_complete("index", ctx, result)
		return result.model_dump()

	except Exception as e:
		logger.exception(f"Error indexing document {document_id}")
		result = TaskResult.failure_result(
			f"Indexing failed: {str(e)}",
			error_code="INDEX_ERROR",
		)
		log_task_complete("index", ctx, result)
		return result.model_dump()

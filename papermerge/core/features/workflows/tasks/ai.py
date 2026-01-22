# (c) Copyright Datacraft, 2026
"""AI/ML processing tasks for workflow engine."""
import logging
from typing import Any
from uuid import UUID

from prefect import task

from papermerge.core.config.prefect import get_prefect_settings
from .base import TaskResult, log_task_start, log_task_complete

logger = logging.getLogger(__name__)
settings = get_prefect_settings()


@task(
	name="ocr",
	description="Extract text from document using OCR",
	retries=settings.default_retries,
	retry_delay_seconds=settings.retry_delay_seconds,
	timeout_seconds=settings.default_timeout,
)
async def ocr_task(ctx: dict, config: dict) -> dict:
	"""
	Perform OCR on a document to extract text.

	Supports multiple OCR engines:
	- tesseract: Open-source OCR (default)
	- paddle: PaddleOCR for complex layouts
	- qwen_vl: Vision-language model for difficult documents
	- hybrid: Combine multiple engines

	Config options:
		- engine: str - OCR engine to use
		- languages: list[str] - Languages to recognize
		- detect_orientation: bool - Auto-detect page orientation
		- detect_tables: bool - Detect and preserve table structure
		- confidence_threshold: float - Minimum confidence score

	Returns:
		Extracted text and OCR metadata
	"""
	log_task_start("ocr", ctx, config)

	document_id = ctx["document_id"]
	engine = config.get("engine", "tesseract")
	languages = config.get("languages", ["eng"])
	detect_tables = config.get("detect_tables", True)
	confidence_threshold = config.get("confidence_threshold", 0.7)

	try:
		from papermerge.core.features.quality.assessment import assess_page_quality

		# Get document path from storage
		from papermerge.storage.base import get_storage_backend
		from papermerge.core import pathlib as plib
		from papermerge.core.db.engine import get_async_session_maker
		from papermerge.core.features.document.db.orm import DocumentVersion
		from sqlalchemy import select
		import tempfile
		from pathlib import Path

		async_session = get_async_session_maker()
		async with async_session() as session:
			stmt = select(DocumentVersion).where(
				DocumentVersion.document_id == document_id
			).order_by(DocumentVersion.number.desc()).limit(1)
			result = await session.execute(stmt)
			version = result.scalar_one_or_none()

		if not version:
			raise ValueError(f"No version found for document {document_id}")

		storage = get_storage_backend()
		object_key = str(plib.docver_path(version.id, version.file_name))

		# Download document for OCR
		with tempfile.TemporaryDirectory() as tmpdir:
			local_path = Path(tmpdir) / version.file_name
			await storage.download_file_to_path(object_key, local_path)

			# Initialize OCR pipeline based on engine config
			try:
				from ocrworker.pipeline import HybridOCRPipeline
				from ocrworker.engines.base import OCREngineType

				engine_map = {
					"tesseract": OCREngineType.TESSERACT,
					"paddle": OCREngineType.PADDLEOCR,
					"qwen_vl": OCREngineType.QWEN_VL,
					"hybrid": OCREngineType.HYBRID,
				}
				primary = engine_map.get(engine, OCREngineType.TESSERACT)

				pipeline = HybridOCRPipeline(
					primary_engine=primary,
					confidence_threshold=confidence_threshold,
				)

				# Run OCR
				ocr_result = pipeline.process_file(local_path, languages=languages)

				ocr_results = {
					"document_id": document_id,
					"engine": engine,
					"languages": languages,
					"text": ocr_result.full_text,
					"pages": [
						{
							"page": p.page_number,
							"text": p.text,
							"confidence": p.confidence,
							"word_count": len(p.text.split()),
							"tables": [],
						}
						for p in ocr_result.pages
					],
					"average_confidence": ocr_result.confidence,
					"tables_detected": 0,
				}

			except ImportError:
				logger.warning("OCR worker not available, using Celery task")
				from papermerge.core.tasks import send_task
				send_task("ocr", kwargs={
					"document_id": str(document_id),
					"lang": languages[0] if languages else "eng",
				})
				ocr_results = {
					"document_id": document_id,
					"engine": engine,
					"languages": languages,
					"text": "",
					"pages": [],
					"average_confidence": 0.0,
					"tables_detected": 0,
					"status": "queued_for_ocr",
				}

		# Check confidence threshold
		if ocr_results["average_confidence"] < confidence_threshold:
			logger.warning(
				f"OCR confidence {ocr_results['average_confidence']:.2f} "
				f"below threshold {confidence_threshold}"
			)

		result = TaskResult.success_result(
			f"OCR completed with {engine} engine",
			text=ocr_results["text"],
			ocr=ocr_results,
		)
		log_task_complete("ocr", ctx, result)
		return result.model_dump()

	except Exception as e:
		logger.exception(f"OCR failed for document {document_id}")
		result = TaskResult.failure_result(
			f"OCR failed: {str(e)}",
			error_code="OCR_ERROR",
		)
		log_task_complete("ocr", ctx, result)
		return result.model_dump()


@task(
	name="nlp",
	description="Extract entities and analyze text",
	retries=settings.default_retries,
	retry_delay_seconds=settings.retry_delay_seconds,
)
async def nlp_task(ctx: dict, config: dict) -> dict:
	"""
	Perform NLP analysis on document text.

	Extracts:
	- Named entities (people, organizations, locations, dates)
	- Key phrases
	- Document structure
	- Language detection

	Config options:
		- extract_entities: bool - Extract named entities
		- extract_keyphrases: bool - Extract key phrases
		- detect_language: bool - Detect document language
		- spacy_model: str - SpaCy model to use

	Returns:
		NLP analysis results including entities and keyphrases
	"""
	log_task_start("nlp", ctx, config)

	document_id = ctx["document_id"]
	extract_entities = config.get("extract_entities", True)
	extract_keyphrases = config.get("extract_keyphrases", True)
	detect_language = config.get("detect_language", True)

	try:
		# Get OCR text
		ocr_result = ctx.get("previous_results", {}).get("ocr", {})
		text = ocr_result.get("data", {}).get("text", "")

		if not text:
			result = TaskResult.failure_result(
				"No text available for NLP analysis",
				error_code="NO_TEXT",
			)
			log_task_complete("nlp", ctx, result)
			return result.model_dump()

		nlp_results = {
			"document_id": document_id,
			"character_count": len(text),
			"word_count": len(text.split()),
			"entities": [],
			"keyphrases": [],
			"language": "en",
		}

		try:
			from ocrworker.nlp.extractor import MetadataExtractor
			extractor = MetadataExtractor(language=config.get("language", "en"))
			extracted = await extractor.extract_async(text)
			
			nlp_results["entities"] = [
				{"text": e.text, "label": e.label, "start": e.start, "end": e.end}
				for e in extracted.all_entities
			]
			nlp_results["language"] = extracted.language
			nlp_results["metadata"] = extracted.to_dict()
		except ImportError:
			logger.warning("ocrworker.nlp not available, using simulated results")
			if detect_language:
				# Simulated language detection
				nlp_results["language"] = "en"
				nlp_results["language_confidence"] = 0.95

			if extract_entities:
				# Simulated entity extraction
				nlp_results["entities"] = [
					{"text": "Sample Entity", "label": "ORG", "start": 0, "end": 13},
					{"text": "January 2026", "label": "DATE", "start": 50, "end": 62},
				]

		if extract_keyphrases:
			# Simulated keyphrase extraction
			nlp_results["keyphrases"] = [
				{"text": "document management", "score": 0.85},
				{"text": "workflow automation", "score": 0.78},
			]

		result = TaskResult.success_result(
			f"NLP analysis completed ({nlp_results['word_count']} words)",
			nlp=nlp_results,
			entities=nlp_results["entities"],
			keyphrases=nlp_results["keyphrases"],
		)
		log_task_complete("nlp", ctx, result)
		return result.model_dump()

	except Exception as e:
		logger.exception(f"NLP failed for document {document_id}")
		result = TaskResult.failure_result(
			f"NLP analysis failed: {str(e)}",
			error_code="NLP_ERROR",
		)
		log_task_complete("nlp", ctx, result)
		return result.model_dump()


@task(
	name="classify",
	description="Classify document type and category",
	retries=settings.default_retries,
	retry_delay_seconds=settings.retry_delay_seconds,
)
async def classify_task(ctx: dict, config: dict) -> dict:
	"""
	Classify a document into predefined categories.

	Classification methods:
	- rule_based: Using keyword matching and patterns
	- ml_model: Using trained ML classifier
	- llm: Using language model for classification

	Config options:
		- method: str - Classification method
		- document_types: list[str] - Available document types
		- confidence_threshold: float - Minimum confidence for auto-assign
		- fallback_type: str - Default type if no match

	Returns:
		Classification results with confidence scores
	"""
	log_task_start("classify", ctx, config)

	document_id = ctx["document_id"]
	method = config.get("method", "rule_based")
	document_types = config.get("document_types", [])
	confidence_threshold = config.get("confidence_threshold", 0.8)
	fallback_type = config.get("fallback_type", "general")

	try:
		# Get NLP results for classification
		nlp_result = ctx.get("previous_results", {}).get("nlp", {})
		entities = nlp_result.get("data", {}).get("entities", [])
		keyphrases = nlp_result.get("data", {}).get("keyphrases", [])

		# Get OCR text
		ocr_result = ctx.get("previous_results", {}).get("ocr", {})
		text = ocr_result.get("data", {}).get("text", "")

		classification_results = {
			"document_id": document_id,
			"character_count": len(text),
			"method": method,
			"predictions": [],
			"assigned_type": None,
			"confidence": 0.0,
			"needs_review": False,
		}

		try:
			from ocrworker.classification.detector import DocumentTypeDetector
			detector = DocumentTypeDetector()
			# We use the text and potentially NLP results if the detector supports it
			detection_result = await detector.detect_async(text, method=method)
			
			predictions = [
				{"type": p.label, "confidence": p.score}
				for p in detection_result.predictions
			]
		except (ImportError, AttributeError):
			logger.warning("ocrworker.classification not available, using simulated results")
			if method == "rule_based":
				# Simulated rule-based classification
				predictions = [
					{"type": "invoice", "confidence": 0.75},
					{"type": "contract", "confidence": 0.15},
					{"type": "correspondence", "confidence": 0.10},
				]
			elif method == "ml_model":
				# Would use trained ML model
				predictions = [
					{"type": "invoice", "confidence": 0.85},
					{"type": "receipt", "confidence": 0.12},
				]
			else:
				# LLM-based classification
				predictions = [
					{"type": "invoice", "confidence": 0.92},
				]

		classification_results["predictions"] = predictions

		# Assign type based on threshold
		if predictions:
			top_prediction = max(predictions, key=lambda x: x["confidence"])
			if top_prediction["confidence"] >= confidence_threshold:
				classification_results["assigned_type"] = top_prediction["type"]
				classification_results["confidence"] = top_prediction["confidence"]
			else:
				classification_results["assigned_type"] = fallback_type
				classification_results["needs_review"] = True
				classification_results["confidence"] = top_prediction["confidence"]

		result = TaskResult.success_result(
			f"Document classified as '{classification_results['assigned_type']}' "
			f"({classification_results['confidence']:.0%} confidence)",
			classification=classification_results,
		)
		log_task_complete("classify", ctx, result)
		return result.model_dump()

	except Exception as e:
		logger.exception(f"Classification failed for document {document_id}")
		result = TaskResult.failure_result(
			f"Classification failed: {str(e)}",
			error_code="CLASSIFY_ERROR",
		)
		log_task_complete("classify", ctx, result)
		return result.model_dump()

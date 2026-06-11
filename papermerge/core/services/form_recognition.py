# (c) Copyright Datacraft, 2026
"""Form recognition and extraction service."""
import logging
from uuid import UUID
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.features.form_recognition.db.orm import (
	FormTemplate,
	FormField,
	FormExtraction,
	ExtractedFieldValue,
	Signature,
)

logger = logging.getLogger(__name__)


class FieldMatch:
	"""Result of field matching."""

	def __init__(
		self,
		field_id: UUID,
		field_name: str,
		field_type: str,
		page_number: int,
		value: Any,
		confidence: float,
		x: float | None = None,
		y: float | None = None,
		width: float | None = None,
		height: float | None = None,
	):
		self.field_id = field_id
		self.field_name = field_name
		self.field_type = field_type
		self.page_number = page_number
		self.value = value
		self.confidence = confidence
		self.x = x
		self.y = y
		self.width = width
		self.height = height


class ExtractionResult:
	"""Result of form extraction."""

	def __init__(
		self,
		success: bool,
		template_id: UUID | None = None,
		template_name: str | None = None,
		fields: list[FieldMatch] | None = None,
		signatures: list[dict] | None = None,
		confidence: float = 0.0,
		message: str | None = None,
	):
		self.success = success
		self.template_id = template_id
		self.template_name = template_name
		self.fields = fields or []
		self.signatures = signatures or []
		self.confidence = confidence
		self.message = message


class FormRecognitionService:
	"""Form recognition and data extraction."""

	def __init__(self, db: AsyncSession):
		self.db = db

	async def recognize_and_extract(
		self,
		document_id: UUID,
		tenant_id: UUID,
		page_images: list[bytes],
		ocr_results: list[dict],
	) -> ExtractionResult:
		"""Recognize form template and extract field values."""
		templates = await self._get_templates(tenant_id)
		if not templates:
			return ExtractionResult(
				success=False,
				message="No form templates configured for tenant",
			)

		# Match document against templates — no min_confidence on ORM, use 0.5 default
		best_match = None
		best_score = 0.0
		MIN_CONFIDENCE = 0.5

		for template in templates:
			score = await self._match_template(template, ocr_results)
			if score > best_score and score >= MIN_CONFIDENCE:
				best_score = score
				best_match = template

		if not best_match:
			return ExtractionResult(
				success=False,
				message="No matching template found",
			)

		fields = await self._extract_fields(best_match, ocr_results, page_images)
		signatures = await self._extract_signatures(page_images, ocr_results)

		extraction = await self._save_extraction(
			document_id, best_match.id, fields, signatures, best_score
		)

		return ExtractionResult(
			success=True,
			template_id=best_match.id,
			template_name=best_match.name,
			fields=fields,
			signatures=signatures,
			confidence=best_score,
		)

	async def extract_with_template(
		self,
		document_id: UUID,
		template_id: UUID,
		page_images: list[bytes],
		ocr_results: list[dict],
	) -> ExtractionResult:
		"""Extract using a specific template."""
		template = await self.db.get(FormTemplate, template_id)
		if not template:
			return ExtractionResult(
				success=False,
				message=f"Template not found: {template_id}",
			)

		fields = await self._extract_fields(template, ocr_results, page_images)
		signatures = await self._extract_signatures(page_images, ocr_results)

		confidence = self._calculate_extraction_confidence(fields)

		await self._save_extraction(
			document_id, template_id, fields, signatures, confidence
		)

		return ExtractionResult(
			success=True,
			template_id=template_id,
			template_name=template.name,
			fields=fields,
			signatures=signatures,
			confidence=confidence,
		)

	async def create_template(
		self,
		tenant_id: UUID,
		name: str,
		category: str,
		fields: list,
		sample_image: bytes | None = None,
		is_multipage: bool = False,
		page_count: int = 1,
	) -> FormTemplate:
		"""Create a new form template.

		`fields` is a list of FieldCreate Pydantic model instances (or dicts).
		`is_multipage` is accepted for API compatibility but not stored — the ORM
		expresses multi-page intent via page_count > 1.
		"""
		template = FormTemplate(
			tenant_id=tenant_id,
			name=name,
			category=category,
			# ORM has no is_multipage / is_active columns.
			# page_count covers multi-page intent.
			page_count=page_count if page_count > 1 else (2 if is_multipage else 1),
		)
		self.db.add(template)
		await self.db.flush()

		for field_data in fields:
			# Support both Pydantic model objects and plain dicts.
			if hasattr(field_data, "name"):
				field_name = field_data.name
				field_type = getattr(field_data, "type", "text")
				field_label = getattr(field_data, "label", None) or field_name
				field_page = getattr(field_data, "page_number", 1)
				bbox = getattr(field_data, "bounding_box", None)
				# anchor_text / regex_pattern come from schema but map to ORM columns
				validation_regex = getattr(field_data, "regex_pattern", None)
				expected_format = getattr(field_data, "anchor_text", None)
				field_required = getattr(field_data, "is_required", False)
			else:
				field_name = field_data["name"]
				field_type = field_data.get("type", "text")
				field_label = field_data.get("label", field_name)
				field_page = field_data.get("page_number", 1)
				bbox = field_data.get("bounding_box")
				validation_regex = field_data.get("regex_pattern")
				expected_format = field_data.get("anchor_text")
				field_required = field_data.get("is_required", False)

			# Unpack bounding_box dict into ORM x/y/width/height columns.
			x = y = width = height = 0.0
			if isinstance(bbox, dict):
				x = float(bbox.get("x", bbox.get("x1", 0.0)))
				y = float(bbox.get("y", bbox.get("y1", 0.0)))
				width = float(bbox.get("width", bbox.get("x2", 0.0) - x))
				height = float(bbox.get("height", bbox.get("y2", 0.0) - y))

			field = FormField(
				template_id=template.id,
				name=field_name,
				field_type=field_type,
				label=field_label,
				page_number=field_page,
				x=x,
				y=y,
				width=width,
				height=height,
				validation_regex=validation_regex,
				expected_format=expected_format,
				required=field_required,
			)
			self.db.add(field)

		await self.db.commit()
		await self.db.refresh(template)
		return template

	async def update_template_from_corrections(
		self,
		extraction_id: UUID,
		corrections: dict[str, Any],
	) -> None:
		"""Update template based on user corrections."""
		extraction = await self.db.get(FormExtraction, extraction_id)
		if not extraction:
			return

		# ORM has reviewed_at / reviewed_by, not a bool `reviewed` column.
		extraction.reviewed_at = datetime.now(timezone.utc)

		# Apply corrections: find matching field_values by field_name and set
		# needs_review=False, update text_value with the corrected content.
		# We must load field_values explicitly (lazy loading not available in async).
		stmt = select(ExtractedFieldValue).where(
			ExtractedFieldValue.extraction_id == extraction_id
		)
		result = await self.db.execute(stmt)
		field_values = result.scalars().all()

		for field_value in field_values:
			if field_value.field_name in corrections:
				corrected = corrections[field_value.field_name]
				# Store corrected value in text_value; mark as no longer needing review.
				field_value.text_value = str(corrected) if corrected is not None else None
				field_value.needs_review = False

		await self.db.commit()

	async def _get_templates(self, tenant_id: UUID) -> list[FormTemplate]:
		"""Get templates for tenant.

		ORM has no `is_active` column — return all templates for the tenant.
		"""
		stmt = select(FormTemplate).where(
			FormTemplate.tenant_id == tenant_id,
		)
		result = await self.db.execute(stmt)
		return list(result.scalars().all())

	async def _match_template(
		self,
		template: FormTemplate,
		ocr_results: list[dict],
	) -> float:
		"""Calculate match score between document and template.

		ORM has no `identifiers` column.  Use template name / category tokens as
		lightweight identifiers for matching heuristic.
		"""
		full_text = " ".join(
			block.get("text", "") for page in ocr_results for block in page.get("blocks", [])
		)
		full_text_lower = full_text.lower()

		# Build a small identifier set from name + category.
		identifiers = [
			token for token in (template.name or "").lower().split()
			if len(token) > 3
		]
		if template.category:
			identifiers += [
				token for token in template.category.lower().split()
				if len(token) > 3
			]

		if not identifiers:
			return 0.0

		matches = sum(1 for ident in identifiers if ident in full_text_lower)
		return matches / len(identifiers)

	async def _extract_fields(
		self,
		template: FormTemplate,
		ocr_results: list[dict],
		page_images: list[bytes],
	) -> list[FieldMatch]:
		"""Extract field values from OCR results."""
		import re

		fields = []

		# ORM has no `order` column — use page_number + name for stable ordering.
		stmt = (
			select(FormField)
			.where(FormField.template_id == template.id)
			.order_by(FormField.page_number, FormField.name)
		)
		result = await self.db.execute(stmt)
		template_fields = list(result.scalars().all())

		for field in template_fields:
			value = None
			confidence = 0.0
			found_x = found_y = found_w = found_h = None

			page_idx = (field.page_number or 1) - 1
			if page_idx >= len(ocr_results):
				continue

			page_ocr = ocr_results[page_idx]
			blocks = page_ocr.get("blocks", [])

			# Strategy 1: bounding box region (x/y/width/height on ORM field)
			if field.x is not None and field.width:
				bbox_region = {
					"x1": field.x,
					"y1": field.y,
					"x2": field.x + field.width,
					"y2": field.y + field.height,
				}
				value, confidence, found_bbox = self._find_value_in_region(blocks, bbox_region)
				if found_bbox:
					found_x = found_bbox.get("x1")
					found_y = found_bbox.get("y1")
					found_w = (found_bbox.get("x2", 0) - (found_x or 0)) or None
					found_h = (found_bbox.get("y2", 0) - (found_y or 0)) or None

			# Strategy 2: expected_format used as anchor text (schema maps anchor_text -> expected_format)
			if not value and field.expected_format:
				value, confidence, found_bbox = self._find_value_by_anchor(
					blocks, field.expected_format, field.field_type
				)
				if found_bbox:
					found_x = found_bbox.get("x1")
					found_y = found_bbox.get("y1")
					found_w = (found_bbox.get("x2", 0) - (found_x or 0)) or None
					found_h = (found_bbox.get("y2", 0) - (found_y or 0)) or None

			# Strategy 3: validation_regex (schema maps regex_pattern -> validation_regex)
			if not value and field.validation_regex:
				page_text = " ".join(b.get("text", "") for b in blocks)
				match = re.search(field.validation_regex, page_text)
				if match:
					value = match.group(1) if match.groups() else match.group(0)
					confidence = 0.8

			if value:
				fields.append(FieldMatch(
					field_id=field.id,
					field_name=field.name,
					field_type=field.field_type,
					page_number=field.page_number,
					value=value,
					confidence=confidence,
					x=found_x,
					y=found_y,
					width=found_w,
					height=found_h,
				))

		return fields

	def _find_value_by_anchor(
		self,
		blocks: list[dict],
		anchor_text: str,
		field_type: str,
	) -> tuple[Any, float, dict | None]:
		"""Find field value by looking near anchor text."""
		anchor_lower = anchor_text.lower()

		for idx, block in enumerate(blocks):
			text = block.get("text", "").lower()
			if anchor_lower in text:
				if ":" in block.get("text", ""):
					parts = block.get("text", "").split(":", 1)
					if len(parts) > 1 and parts[1].strip():
						return parts[1].strip(), 0.85, block.get("bbox")

				if idx + 1 < len(blocks):
					next_block = blocks[idx + 1]
					return (
						next_block.get("text", "").strip(),
						0.75,
						next_block.get("bbox"),
					)

		return None, 0.0, None

	def _find_value_in_region(
		self,
		blocks: list[dict],
		region: dict,
	) -> tuple[Any, float, dict | None]:
		"""Find text within a bounding box region."""
		x1, y1, x2, y2 = (
			region.get("x1", 0),
			region.get("y1", 0),
			region.get("x2", 0),
			region.get("y2", 0),
		)

		for block in blocks:
			bbox = block.get("bbox", {})
			bx1, by1, bx2, by2 = (
				bbox.get("x1", 0),
				bbox.get("y1", 0),
				bbox.get("x2", 0),
				bbox.get("y2", 0),
			)

			if bx1 >= x1 and by1 >= y1 and bx2 <= x2 and by2 <= y2:
				return block.get("text", "").strip(), 0.9, bbox

		return None, 0.0, None

	async def _extract_signatures(
		self,
		page_images: list[bytes],
		ocr_results: list[dict],
	) -> list[dict]:
		"""Extract signature regions from pages."""
		signatures = []

		for page_idx, page_ocr in enumerate(ocr_results):
			blocks = page_ocr.get("blocks", [])

			for idx, block in enumerate(blocks):
				text = block.get("text", "").lower()
				if any(kw in text for kw in ["signature", "sign here", "signed", "sign:"]):
					bbox = block.get("bbox", {})
					if bbox:
						signatures.append({
							"page_number": page_idx + 1,
							"indicator_text": block.get("text", ""),
							"region": {
								"x1": bbox.get("x1", 0),
								"y1": bbox.get("y2", 0),
								"x2": bbox.get("x2", 0) + 100,
								"y2": bbox.get("y2", 0) + 50,
							},
							"type": "handwritten",
						})

		return signatures

	def _calculate_extraction_confidence(self, fields: list[FieldMatch]) -> float:
		"""Calculate overall extraction confidence."""
		if not fields:
			return 0.0
		return sum(f.confidence for f in fields) / len(fields)

	async def _save_extraction(
		self,
		document_id: UUID,
		template_id: UUID,
		fields: list[FieldMatch],
		signatures: list[dict],
		confidence: float,
	) -> FormExtraction:
		"""Save extraction results to database."""
		extraction = FormExtraction(
			document_id=document_id,
			template_id=template_id,
			# ORM column is confidence_score, not confidence
			confidence_score=confidence,
			status="completed",
			extracted_at=datetime.now(timezone.utc),
		)
		self.db.add(extraction)
		await self.db.flush()

		for field in fields:
			# ORM uses typed value columns (text_value, boolean_value, etc.)
			# and needs_review instead of was_corrected / extracted_value / corrected_value.
			field_value = ExtractedFieldValue(
				extraction_id=extraction.id,
				field_id=field.field_id,
				page_number=field.page_number,
				field_name=field.field_name,
				field_type=field.field_type,
				text_value=str(field.value) if field.value is not None else None,
				confidence=field.confidence,
				needs_review=field.confidence < 0.7,
				x=field.x,
				y=field.y,
				width=field.width,
				height=field.height,
			)
			self.db.add(field_value)

		# Signatures in the ORM Signature table are a library, not per-extraction.
		# The ORM Signature has no extraction_id FK.  Log a warning and skip DB
		# persistence of raw detected regions — callers that need to persist
		# confirmed signatures should do so via a dedicated endpoint.
		if signatures:
			logger.debug(
				"_save_extraction: %d signature regions detected but not persisted "
				"(ORM Signature has no extraction_id FK; use a dedicated endpoint to "
				"save confirmed signatures to the library).",
				len(signatures),
			)

		await self.db.commit()
		await self.db.refresh(extraction)
		return extraction

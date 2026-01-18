# (c) Copyright Datacraft, 2026
"""Form recognition and extraction service."""
import logging
from uuid import UUID
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, and_
from sqlalchemy.orm import Session

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
		value: Any,
		confidence: float,
		bounding_box: dict | None = None,
	):
		self.field_id = field_id
		self.field_name = field_name
		self.value = value
		self.confidence = confidence
		self.bounding_box = bounding_box


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

	def __init__(self, db: Session):
		self.db = db

	async def recognize_and_extract(
		self,
		document_id: UUID,
		tenant_id: UUID,
		page_images: list[bytes],
		ocr_results: list[dict],
	) -> ExtractionResult:
		"""Recognize form template and extract field values."""
		# Get active templates for tenant
		templates = await self._get_templates(tenant_id)
		if not templates:
			return ExtractionResult(
				success=False,
				message="No form templates configured for tenant",
			)

		# Match document against templates
		best_match = None
		best_score = 0.0

		for template in templates:
			score = await self._match_template(template, ocr_results)
			if score > best_score and score >= template.min_confidence:
				best_score = score
				best_match = template

		if not best_match:
			return ExtractionResult(
				success=False,
				message="No matching template found",
			)

		# Extract fields using matched template
		fields = await self._extract_fields(best_match, ocr_results, page_images)

		# Extract signatures
		signatures = await self._extract_signatures(page_images, ocr_results)

		# Create extraction record
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
		template = self.db.get(FormTemplate, template_id)
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
		fields: list[dict],
		sample_image: bytes | None = None,
		is_multipage: bool = False,
		page_count: int = 1,
	) -> FormTemplate:
		"""Create a new form template."""
		template = FormTemplate(
			tenant_id=tenant_id,
			name=name,
			category=category,
			is_multipage=is_multipage,
			page_count=page_count,
			is_active=True,
		)
		self.db.add(template)
		self.db.flush()

		# Add fields
		for idx, field_data in enumerate(fields):
			field = FormField(
				template_id=template.id,
				name=field_data["name"],
				field_type=field_data.get("type", "text"),
				label=field_data.get("label", field_data["name"]),
				page_number=field_data.get("page_number", 1),
				bounding_box=field_data.get("bounding_box"),
				anchor_text=field_data.get("anchor_text"),
				regex_pattern=field_data.get("regex_pattern"),
				is_required=field_data.get("is_required", False),
				order=idx,
			)
			self.db.add(field)

		self.db.commit()
		self.db.refresh(template)
		return template

	async def update_template_from_corrections(
		self,
		extraction_id: UUID,
		corrections: dict[str, Any],
	) -> None:
		"""Update template based on user corrections."""
		extraction = self.db.get(FormExtraction, extraction_id)
		if not extraction:
			return

		# Mark extraction as reviewed
		extraction.reviewed = True
		extraction.reviewed_at = datetime.now(timezone.utc)

		# Update field values with corrections
		for field_value in extraction.field_values:
			if field_value.field.name in corrections:
				corrected = corrections[field_value.field.name]
				field_value.corrected_value = corrected
				field_value.was_corrected = True

		self.db.commit()

	async def _get_templates(self, tenant_id: UUID) -> list[FormTemplate]:
		"""Get active templates for tenant."""
		stmt = select(FormTemplate).where(
			and_(
				FormTemplate.tenant_id == tenant_id,
				FormTemplate.is_active == True,
			)
		)
		return list(self.db.scalars(stmt))

	async def _match_template(
		self,
		template: FormTemplate,
		ocr_results: list[dict],
	) -> float:
		"""Calculate match score between document and template."""
		# Combine all OCR text
		full_text = " ".join(
			block.get("text", "") for page in ocr_results for block in page.get("blocks", [])
		)
		full_text_lower = full_text.lower()

		# Check for template identifiers
		identifiers = template.identifiers or []
		if not identifiers:
			return 0.0

		matches = sum(1 for ident in identifiers if ident.lower() in full_text_lower)
		return matches / len(identifiers) if identifiers else 0.0

	async def _extract_fields(
		self,
		template: FormTemplate,
		ocr_results: list[dict],
		page_images: list[bytes],
	) -> list[FieldMatch]:
		"""Extract field values from OCR results."""
		import re

		fields = []

		# Get template fields
		stmt = select(FormField).where(
			FormField.template_id == template.id
		).order_by(FormField.order)
		template_fields = list(self.db.scalars(stmt))

		for field in template_fields:
			value = None
			confidence = 0.0
			bounding_box = None

			# Get relevant page OCR results
			page_idx = (field.page_number or 1) - 1
			if page_idx >= len(ocr_results):
				continue

			page_ocr = ocr_results[page_idx]
			blocks = page_ocr.get("blocks", [])

			# Strategy 1: Use anchor text to find nearby value
			if field.anchor_text:
				value, confidence, bounding_box = self._find_value_by_anchor(
					blocks, field.anchor_text, field.field_type
				)

			# Strategy 2: Use bounding box region
			if not value and field.bounding_box:
				value, confidence, bounding_box = self._find_value_in_region(
					blocks, field.bounding_box
				)

			# Strategy 3: Use regex pattern
			if not value and field.regex_pattern:
				page_text = " ".join(b.get("text", "") for b in blocks)
				match = re.search(field.regex_pattern, page_text)
				if match:
					value = match.group(1) if match.groups() else match.group(0)
					confidence = 0.8

			if value:
				fields.append(FieldMatch(
					field_id=field.id,
					field_name=field.name,
					value=value,
					confidence=confidence,
					bounding_box=bounding_box,
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
				# Look for value in same block (after colon) or next block
				if ":" in block.get("text", ""):
					parts = block.get("text", "").split(":", 1)
					if len(parts) > 1 and parts[1].strip():
						return parts[1].strip(), 0.85, block.get("bbox")

				# Check next block
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

			# Check if block is within region
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

			# Look for signature indicators
			for idx, block in enumerate(blocks):
				text = block.get("text", "").lower()
				if any(kw in text for kw in ["signature", "sign here", "signed", "sign:"]):
					# The signature is likely below or next to this indicator
					bbox = block.get("bbox", {})
					if bbox:
						signatures.append({
							"page_number": page_idx + 1,
							"indicator_text": block.get("text", ""),
							"region": {
								"x1": bbox.get("x1", 0),
								"y1": bbox.get("y2", 0),  # Below indicator
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
			confidence=confidence,
			status="completed",
		)
		self.db.add(extraction)
		self.db.flush()

		# Save field values
		for field in fields:
			field_value = ExtractedFieldValue(
				extraction_id=extraction.id,
				field_id=field.field_id,
				extracted_value=str(field.value) if field.value else None,
				confidence=field.confidence,
				bounding_box=field.bounding_box,
			)
			self.db.add(field_value)

		# Save signatures
		for sig in signatures:
			signature = Signature(
				extraction_id=extraction.id,
				page_number=sig["page_number"],
				bounding_box=sig["region"],
				signature_type=sig.get("type", "handwritten"),
			)
			self.db.add(signature)

		self.db.commit()
		self.db.refresh(extraction)
		return extraction

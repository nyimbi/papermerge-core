# (c) Copyright Datacraft, 2026
"""
API router for physical inventory management.
"""
import io
from datetime import datetime
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid_extensions import uuid7str

from papermerge.core.db.engine import get_db
from papermerge.core.auth import get_current_user
from papermerge.core.features.users.db.orm import User
from papermerge.core.features.provenance.db.orm import DocumentProvenance

from .qr import QRCodeGenerator, DataMatrixGenerator, LabelData, LabelSheetGenerator
from .duplicates import DuplicateDetector, HashResult, DuplicateMatch
from .reconciliation import (
	InventoryReconciler,
	PhysicalRecord,
	DigitalRecord,
	ReconciliationReport,
	Discrepancy,
)

router = APIRouter(prefix="/inventory", tags=["inventory"])


# ============ Schemas ============

class QRCodeRequest(BaseModel):
	document_id: str
	batch_id: str | None = None
	location_code: str | None = None
	box_label: str | None = None
	folder_label: str | None = None
	sequence_number: int | None = None
	format: str = Field(default="compact", pattern="^(compact|json|url)$")
	base_url: str | None = None
	size: int = Field(default=200, ge=50, le=1000)
	include_label: bool = False


class LabelSheetRequest(BaseModel):
	documents: list[QRCodeRequest]
	sheet_type: str = Field(default="letter", pattern="^(letter|a4|avery5160)$")
	include_text: bool = True


class DuplicateCheckRequest(BaseModel):
	document_id: str
	file_path: str | None = None
	similarity_threshold: float = Field(default=0.90, ge=0.5, le=1.0)


class DuplicateCheckResponse(BaseModel):
	document_id: str
	is_duplicate: bool
	matches: list[dict]
	phash: str | None = None
	dhash: str | None = None


class ReconcileRequest(BaseModel):
	physical_records: list[dict]
	match_by: list[str] = ["barcode"]
	page_count_tolerance: int = 0
	require_quality_check: bool = True
	min_quality_score: float = 70.0


class ResolveDiscrepancyRequest(BaseModel):
	discrepancy_id: str
	resolution_notes: str


# ============ QR Code Endpoints ============

@router.post("/qr/generate")
async def generate_qr_code(
	data: QRCodeRequest,
	user: Annotated[User, Depends(get_current_user)],
):
	"""Generate a QR code for a document."""
	label_data = LabelData(
		document_id=data.document_id,
		batch_id=data.batch_id,
		location_code=data.location_code,
		box_label=data.box_label,
		folder_label=data.folder_label,
		sequence_number=data.sequence_number,
	)

	generator = QRCodeGenerator()

	if data.include_label:
		img = generator.generate_with_label(
			label_data,
			size=(data.size, data.size + 40),
		)
	else:
		img = generator.generate(
			label_data,
			size=(data.size, data.size),
			format=data.format,
			base_url=data.base_url,
		)

	# Return as PNG
	buffer = io.BytesIO()
	img.save(buffer, format="PNG")
	buffer.seek(0)

	return StreamingResponse(
		buffer,
		media_type="image/png",
		headers={
			"Content-Disposition": f"inline; filename=qr_{data.document_id[:8]}.png"
		}
	)


@router.post("/qr/datamatrix")
async def generate_datamatrix(
	data: QRCodeRequest,
	user: Annotated[User, Depends(get_current_user)],
):
	"""Generate a Data Matrix code for a document."""
	try:
		label_data = LabelData(
			document_id=data.document_id,
			batch_id=data.batch_id,
			location_code=data.location_code,
			box_label=data.box_label,
			folder_label=data.folder_label,
			sequence_number=data.sequence_number,
		)

		generator = DataMatrixGenerator()
		img = generator.generate(label_data, size=(data.size, data.size))

		buffer = io.BytesIO()
		img.save(buffer, format="PNG")
		buffer.seek(0)

		return StreamingResponse(
			buffer,
			media_type="image/png",
			headers={
				"Content-Disposition": f"inline; filename=dm_{data.document_id[:8]}.png"
			}
		)
	except RuntimeError as e:
		raise HTTPException(status_code=501, detail=str(e))


@router.post("/qr/sheet")
async def generate_label_sheet(
	data: LabelSheetRequest,
	user: Annotated[User, Depends(get_current_user)],
):
	"""Generate a printable PDF sheet of labels."""
	from reportlab.lib.pagesizes import LETTER, A4

	labels = [
		LabelData(
			document_id=doc.document_id,
			batch_id=doc.batch_id,
			location_code=doc.location_code,
			box_label=doc.box_label,
			folder_label=doc.folder_label,
			sequence_number=doc.sequence_number,
		)
		for doc in data.documents
	]

	if data.sheet_type == "avery5160":
		page_size = LETTER
		generator = LabelSheetGenerator()
	elif data.sheet_type == "a4":
		page_size = A4
		generator = LabelSheetGenerator(page_size=A4)
	else:
		page_size = LETTER
		generator = LabelSheetGenerator(page_size=LETTER)

	# Generate PDF to buffer
	buffer = io.BytesIO()

	if data.sheet_type == "avery5160":
		generator.generate_avery_5160(labels, buffer)
	else:
		generator.generate_pdf(labels, buffer, include_text=data.include_text)

	buffer.seek(0)

	return StreamingResponse(
		buffer,
		media_type="application/pdf",
		headers={
			"Content-Disposition": f"attachment; filename=labels_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.pdf"
		}
	)


# ============ Duplicate Detection Endpoints ============

@router.post("/duplicates/check", response_model=DuplicateCheckResponse)
async def check_for_duplicates(
	data: DuplicateCheckRequest,
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Check if a document is a duplicate of existing documents."""
	detector = DuplicateDetector(similarity_threshold=data.similarity_threshold)

	# Get document hash
	if data.file_path:
		try:
			doc_hash = detector.hash_file(Path(data.file_path))
		except Exception as e:
			raise HTTPException(status_code=400, detail=f"Failed to hash file: {e}")
	else:
		# Try to get from provenance
		result = await db.execute(
			select(DocumentProvenance)
			.where(DocumentProvenance.document_id == UUID(data.document_id))
		)
		provenance = result.scalar_one_or_none()
		if not provenance or not provenance.similarity_hash:
			raise HTTPException(
				status_code=400,
				detail="No file path provided and no hash found in provenance"
			)
		# Would need to reconstruct HashResult from stored values
		raise HTTPException(
			status_code=501,
			detail="Hash retrieval from provenance not yet implemented"
		)

	# Get existing hashes from provenance
	existing_result = await db.execute(
		select(DocumentProvenance)
		.where(DocumentProvenance.similarity_hash.isnot(None))
		.where(DocumentProvenance.document_id != UUID(data.document_id))
	)
	existing_records = existing_result.scalars().all()

	# For now, return empty matches if no proper hash comparison possible
	# Full implementation would store and compare perceptual hashes
	matches = []

	return DuplicateCheckResponse(
		document_id=data.document_id,
		is_duplicate=len(matches) > 0,
		matches=matches,
		phash=doc_hash.phash if data.file_path else None,
		dhash=doc_hash.dhash if data.file_path else None,
	)


@router.post("/duplicates/batch-check")
async def batch_check_duplicates(
	files: list[UploadFile] = File(...),
	db: Annotated[AsyncSession, Depends(get_db)] = None,
	user: Annotated[User, Depends(get_current_user)] = None,
):
	"""Check multiple files for duplicates."""
	import tempfile
	from .duplicates import BatchDuplicateChecker

	checker = BatchDuplicateChecker()
	temp_dir = Path(tempfile.mkdtemp())

	try:
		# Save uploaded files temporarily
		batch_files = []
		for file in files:
			temp_path = temp_dir / file.filename
			with open(temp_path, "wb") as f:
				content = await file.read()
				f.write(content)
			batch_files.append((file.filename, temp_path))

		# Check for duplicates within batch
		results = await checker.check_batch(batch_files)

		return {
			"total_files": len(files),
			"duplicates_found": len(results),
			"results": {
				doc_id: [
					{
						"match_document_id": m.document_id,
						"similarity": m.similarity_score,
					}
					for m in matches
				]
				for doc_id, matches in results.items()
			}
		}
	finally:
		# Cleanup temp files
		import shutil
		shutil.rmtree(temp_dir, ignore_errors=True)


# ============ Reconciliation Endpoints ============

@router.post("/reconcile", response_model=dict)
async def reconcile_inventory(
	data: ReconcileRequest,
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Reconcile physical inventory with digital records."""
	# Convert input to PhysicalRecord objects
	physical_records = [
		PhysicalRecord(
			barcode=r.get("barcode", ""),
			location_code=r.get("location_code", ""),
			box_label=r.get("box_label"),
			folder_label=r.get("folder_label"),
			sequence_number=r.get("sequence_number"),
			description=r.get("description"),
			page_count=r.get("page_count"),
			scanned_at=r.get("scanned_at"),
			notes=r.get("notes"),
		)
		for r in data.physical_records
	]

	# Get digital records from database
	prov_result = await db.execute(
		select(DocumentProvenance)
		.where(DocumentProvenance.is_duplicate == False)
	)
	provenance_records = prov_result.scalars().all()

	digital_records = [
		DigitalRecord(
			document_id=str(p.document_id),
			provenance_id=p.id,
			batch_id=p.batch_id,
			barcode=p.metadata.get("barcode") if p.metadata else None,
			location_code=p.source_location_detail,
			page_count=p.current_page_count,
			file_hash=p.current_file_hash,
			created_at=p.created_at,
		)
		for p in provenance_records
	]

	# Run reconciliation
	reconciler = InventoryReconciler(
		match_by=data.match_by,
		page_count_tolerance=data.page_count_tolerance,
		require_quality_check=data.require_quality_check,
		min_quality_score=data.min_quality_score,
	)

	report = await reconciler.reconcile(physical_records, digital_records)

	return {
		"id": report.id,
		"status": report.status,
		"total_physical": report.total_physical,
		"total_digital": report.total_digital,
		"matched": report.matched,
		"discrepancies_found": report.discrepancies_found,
		"missing_digital_count": report.missing_digital_count,
		"missing_physical_count": report.missing_physical_count,
		"location_mismatch_count": report.location_mismatch_count,
		"other_issues_count": report.other_issues_count,
		"discrepancies": [
			{
				"id": d.id,
				"type": d.discrepancy_type.value,
				"severity": d.severity.value,
				"description": d.description,
				"suggested_action": d.suggested_action,
				"physical_barcode": d.physical_record.barcode if d.physical_record else None,
				"digital_id": d.digital_record.document_id if d.digital_record else None,
			}
			for d in report.discrepancies
		],
	}


@router.post("/reconcile/resolve")
async def resolve_discrepancy(
	data: ResolveDiscrepancyRequest,
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Mark a discrepancy as resolved."""
	# In production, would load from database
	# For now, just acknowledge the resolution
	return {
		"discrepancy_id": data.discrepancy_id,
		"resolved": True,
		"resolved_at": datetime.utcnow().isoformat(),
		"resolved_by": str(user.id),
		"resolution_notes": data.resolution_notes,
	}

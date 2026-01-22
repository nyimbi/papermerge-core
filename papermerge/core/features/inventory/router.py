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
from .manifest_service import ManifestService
from .db.orm import (
	WarehouseLocation,
	PhysicalContainer,
	ContainerDocument,
	CustodyEvent,
	InventoryScan,
	ContainerType,
	InventoryStatus,
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
	blake3_hash: str | None = None
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


class ManifestCreateRequest(BaseModel):
	barcode: str
	description: str | None = None
	location_path: str | None = None
	responsible_person: str | None = None


class ManifestResponse(BaseModel):
	id: UUID
	barcode: str
	description: str | None = None
	location_path: str | None = None
	responsible_person: str | None = None
	created_at: datetime


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
		if not provenance:
			raise HTTPException(
				status_code=400,
				detail="No file path provided and document not found in provenance"
			)
		
		doc_hash = HashResult(
			file_hash=provenance.original_file_hash or "",
			blake3_hash=provenance.blake3_hash,
			phash=provenance.similarity_hash, # Assuming phash is stored here
			dhash=None,
			ahash=None,
			whash=None
		)
		
		if not doc_hash.blake3_hash and not doc_hash.phash:
			raise HTTPException(
				status_code=400,
				detail="No file path provided and no hashes found in provenance"
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
		blake3_hash=doc_hash.blake3_hash,
		phash=doc_hash.phash,
		dhash=doc_hash.dhash,
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


# ============ Manifest Endpoints ============

@router.post("/manifests", response_model=ManifestResponse)
async def create_manifest(
	data: ManifestCreateRequest,
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Create a new physical manifest."""
	service = ManifestService(db)
	manifest = await service.create_manifest(
		tenant_id=user.tenant_id,
		barcode=data.barcode,
		description=data.description,
		location_path=data.location_path,
		responsible_person=data.responsible_person,
	)
	return manifest


@router.get("/manifests/{manifest_id}/pdf")
async def get_manifest_pdf(
	manifest_id: UUID,
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Download the barcode manifest PDF."""
	service = ManifestService(db)
	try:
		pdf_buffer = await service.generate_manifest_pdf(manifest_id, user.tenant_id)
	except ValueError as e:
		raise HTTPException(status_code=404, detail=str(e))

	return StreamingResponse(
		pdf_buffer,
		media_type="application/pdf",
		headers={
			"Content-Disposition": f"attachment; filename=manifest_{manifest_id}.pdf"
		}
	)


# ============ Warehouse Location Schemas ============

class LocationCreateRequest(BaseModel):
	code: str = Field(..., min_length=1, max_length=50)
	name: str = Field(..., min_length=1, max_length=200)
	description: str | None = None
	parent_id: UUID | None = None
	capacity: int | None = None
	climate_controlled: bool = False
	fire_suppression: bool = False
	access_restricted: bool = False
	aisle: str | None = None
	bay: str | None = None
	shelf_number: str | None = None
	position: str | None = None


class LocationResponse(BaseModel):
	id: UUID
	code: str
	name: str
	description: str | None
	parent_id: UUID | None
	path: str
	level: int
	capacity: int | None
	current_count: int
	climate_controlled: bool
	fire_suppression: bool
	access_restricted: bool
	aisle: str | None
	bay: str | None
	shelf_number: str | None
	position: str | None
	created_at: datetime

	class Config:
		from_attributes = True


# ============ Container Schemas ============

class ContainerCreateRequest(BaseModel):
	barcode: str = Field(..., min_length=1, max_length=100)
	container_type: str = "box"
	label: str | None = None
	description: str | None = None
	location_id: UUID | None = None
	parent_container_id: UUID | None = None
	weight_kg: float | None = None
	dimensions: dict | None = None
	retention_date: datetime | None = None
	scanning_project_id: UUID | None = None


class ContainerResponse(BaseModel):
	id: UUID
	barcode: str
	container_type: str
	label: str | None
	description: str | None
	location_id: UUID | None
	parent_container_id: UUID | None
	status: str
	item_count: int
	weight_kg: float | None
	dimensions: dict | None
	retention_date: datetime | None
	destruction_eligible: bool
	legal_hold: bool
	current_custodian_id: UUID | None
	last_verified_at: datetime | None
	created_at: datetime
	scanning_project_id: UUID | None

	class Config:
		from_attributes = True


class ContainerMoveRequest(BaseModel):
	container_id: UUID
	to_location_id: UUID | None = None
	to_custodian_id: UUID | None = None
	reason: str | None = None
	notes: str | None = None


class CheckoutRequest(BaseModel):
	container_id: UUID
	to_user_id: UUID
	reason: str
	expected_return_date: datetime | None = None


class CheckinRequest(BaseModel):
	container_id: UUID
	to_location_id: UUID
	notes: str | None = None


class ScanRequest(BaseModel):
	scanned_code: str
	code_type: str = "qr"
	scan_purpose: str = "lookup"
	scanner_device_id: str | None = None
	latitude: float | None = None
	longitude: float | None = None


class ScanResponse(BaseModel):
	success: bool
	resolved_type: str | None  # container, document, location
	resolved_id: UUID | None
	resolved_data: dict | None
	error_message: str | None


class CustodyEventResponse(BaseModel):
	id: UUID
	container_id: UUID
	event_type: str
	from_user_id: UUID | None
	to_user_id: UUID | None
	performed_by_id: UUID
	from_location_id: UUID | None
	to_location_id: UUID | None
	reason: str | None
	notes: str | None
	signature_captured: bool
	created_at: datetime

	class Config:
		from_attributes = True


# ============ Warehouse Location Endpoints ============

@router.get("/locations", response_model=list[LocationResponse])
async def list_locations(
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
	parent_id: UUID | None = Query(default=None),
):
	"""List warehouse locations, optionally filtered by parent."""
	stmt = select(WarehouseLocation).where(WarehouseLocation.tenant_id == user.tenant_id)
	if parent_id:
		stmt = stmt.where(WarehouseLocation.parent_id == parent_id)
	else:
		stmt = stmt.where(WarehouseLocation.parent_id.is_(None))
	stmt = stmt.order_by(WarehouseLocation.path)

	result = await db.execute(stmt)
	return result.scalars().all()


@router.post("/locations", response_model=LocationResponse)
async def create_location(
	data: LocationCreateRequest,
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Create a new warehouse location."""
	# Build path from parent
	path = data.code
	level = 0
	if data.parent_id:
		parent_result = await db.execute(
			select(WarehouseLocation)
			.where(WarehouseLocation.id == data.parent_id)
			.where(WarehouseLocation.tenant_id == user.tenant_id)
		)
		parent = parent_result.scalar_one_or_none()
		if parent:
			path = f"{parent.path}/{data.code}"
			level = parent.level + 1

	location = WarehouseLocation(
		tenant_id=user.tenant_id,
		code=data.code,
		name=data.name,
		description=data.description,
		parent_id=data.parent_id,
		path=path,
		level=level,
		capacity=data.capacity,
		climate_controlled=data.climate_controlled,
		fire_suppression=data.fire_suppression,
		access_restricted=data.access_restricted,
		aisle=data.aisle,
		bay=data.bay,
		shelf_number=data.shelf_number,
		position=data.position,
	)
	db.add(location)
	await db.commit()
	await db.refresh(location)
	return location


@router.get("/locations/{location_id}", response_model=LocationResponse)
async def get_location(
	location_id: UUID,
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Get a specific warehouse location."""
	result = await db.execute(
		select(WarehouseLocation)
		.where(WarehouseLocation.id == location_id)
		.where(WarehouseLocation.tenant_id == user.tenant_id)
	)
	location = result.scalar_one_or_none()
	if not location:
		raise HTTPException(status_code=404, detail="Location not found")
	return location


@router.get("/locations/{location_id}/tree", response_model=list[LocationResponse])
async def get_location_tree(
	location_id: UUID,
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Get all descendants of a location."""
	parent_result = await db.execute(
		select(WarehouseLocation)
		.where(WarehouseLocation.id == location_id)
		.where(WarehouseLocation.tenant_id == user.tenant_id)
	)
	parent = parent_result.scalar_one_or_none()
	if not parent:
		raise HTTPException(status_code=404, detail="Location not found")

	result = await db.execute(
		select(WarehouseLocation)
		.where(WarehouseLocation.tenant_id == user.tenant_id)
		.where(WarehouseLocation.path.like(f"{parent.path}/%"))
		.order_by(WarehouseLocation.path)
	)
	return result.scalars().all()


# ============ Container Endpoints ============

@router.get("/containers", response_model=list[ContainerResponse])
async def list_containers(
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
	location_id: UUID | None = Query(default=None),
	status: str | None = Query(default=None),
	container_type: str | None = Query(default=None),
	limit: int = Query(default=100, le=500),
	offset: int = Query(default=0),
):
	"""List physical containers with filtering."""
	stmt = select(PhysicalContainer).where(PhysicalContainer.tenant_id == user.tenant_id)

	if location_id:
		stmt = stmt.where(PhysicalContainer.location_id == location_id)
	if status:
		stmt = stmt.where(PhysicalContainer.status == status)
	if container_type:
		stmt = stmt.where(PhysicalContainer.container_type == container_type)

	stmt = stmt.order_by(PhysicalContainer.created_at.desc()).offset(offset).limit(limit)

	result = await db.execute(stmt)
	return result.scalars().all()


@router.post("/containers", response_model=ContainerResponse)
async def create_container(
	data: ContainerCreateRequest,
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Create a new physical container."""
	container = PhysicalContainer(
		tenant_id=user.tenant_id,
		barcode=data.barcode,
		container_type=data.container_type,
		label=data.label,
		description=data.description,
		location_id=data.location_id,
		parent_container_id=data.parent_container_id,
		weight_kg=int(data.weight_kg * 100) if data.weight_kg else None,
		dimensions=data.dimensions,
		retention_date=data.retention_date,
		scanning_project_id=data.scanning_project_id,
	)
	db.add(container)
	await db.commit()
	await db.refresh(container)
	return container


@router.get("/containers/{container_id}", response_model=ContainerResponse)
async def get_container(
	container_id: UUID,
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Get a specific container."""
	result = await db.execute(
		select(PhysicalContainer)
		.where(PhysicalContainer.id == container_id)
		.where(PhysicalContainer.tenant_id == user.tenant_id)
	)
	container = result.scalar_one_or_none()
	if not container:
		raise HTTPException(status_code=404, detail="Container not found")
	return container


@router.get("/containers/barcode/{barcode}", response_model=ContainerResponse)
async def get_container_by_barcode(
	barcode: str,
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Get container by barcode."""
	result = await db.execute(
		select(PhysicalContainer)
		.where(PhysicalContainer.barcode == barcode)
		.where(PhysicalContainer.tenant_id == user.tenant_id)
	)
	container = result.scalar_one_or_none()
	if not container:
		raise HTTPException(status_code=404, detail="Container not found")
	return container


@router.post("/containers/{container_id}/move")
async def move_container(
	container_id: UUID,
	data: ContainerMoveRequest,
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Move a container to a new location or custodian."""
	result = await db.execute(
		select(PhysicalContainer)
		.where(PhysicalContainer.id == container_id)
		.where(PhysicalContainer.tenant_id == user.tenant_id)
	)
	container = result.scalar_one_or_none()
	if not container:
		raise HTTPException(status_code=404, detail="Container not found")

	# Record custody event
	event = CustodyEvent(
		tenant_id=user.tenant_id,
		container_id=container_id,
		event_type="move",
		from_location_id=container.location_id,
		to_location_id=data.to_location_id,
		from_user_id=container.current_custodian_id,
		to_user_id=data.to_custodian_id,
		performed_by_id=user.id,
		reason=data.reason,
		notes=data.notes,
	)
	db.add(event)

	# Update container
	if data.to_location_id:
		container.location_id = data.to_location_id
		container.status = InventoryStatus.IN_STORAGE
	if data.to_custodian_id:
		container.current_custodian_id = data.to_custodian_id

	await db.commit()

	return {"status": "moved", "container_id": str(container_id)}


@router.post("/containers/{container_id}/checkout")
async def checkout_container(
	container_id: UUID,
	data: CheckoutRequest,
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Check out a container to a user."""
	result = await db.execute(
		select(PhysicalContainer)
		.where(PhysicalContainer.id == container_id)
		.where(PhysicalContainer.tenant_id == user.tenant_id)
	)
	container = result.scalar_one_or_none()
	if not container:
		raise HTTPException(status_code=404, detail="Container not found")

	if container.status == InventoryStatus.CHECKED_OUT:
		raise HTTPException(status_code=400, detail="Container is already checked out")

	if container.legal_hold:
		raise HTTPException(status_code=400, detail="Container is under legal hold")

	# Record custody event
	event = CustodyEvent(
		tenant_id=user.tenant_id,
		container_id=container_id,
		event_type="checkout",
		from_user_id=container.current_custodian_id,
		to_user_id=data.to_user_id,
		from_location_id=container.location_id,
		performed_by_id=user.id,
		reason=data.reason,
	)
	db.add(event)

	# Update container
	container.status = InventoryStatus.CHECKED_OUT
	container.current_custodian_id = data.to_user_id
	container.location_id = None  # No longer in a location

	await db.commit()

	return {"status": "checked_out", "container_id": str(container_id)}


@router.post("/containers/{container_id}/checkin")
async def checkin_container(
	container_id: UUID,
	data: CheckinRequest,
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Check in a container back to a location."""
	result = await db.execute(
		select(PhysicalContainer)
		.where(PhysicalContainer.id == container_id)
		.where(PhysicalContainer.tenant_id == user.tenant_id)
	)
	container = result.scalar_one_or_none()
	if not container:
		raise HTTPException(status_code=404, detail="Container not found")

	# Record custody event
	event = CustodyEvent(
		tenant_id=user.tenant_id,
		container_id=container_id,
		event_type="checkin",
		from_user_id=container.current_custodian_id,
		to_location_id=data.to_location_id,
		performed_by_id=user.id,
		notes=data.notes,
	)
	db.add(event)

	# Update container
	container.status = InventoryStatus.IN_STORAGE
	container.location_id = data.to_location_id
	container.current_custodian_id = None

	await db.commit()

	return {"status": "checked_in", "container_id": str(container_id)}


@router.post("/containers/{container_id}/verify")
async def verify_container(
	container_id: UUID,
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Mark a container as verified (physical inventory check)."""
	result = await db.execute(
		select(PhysicalContainer)
		.where(PhysicalContainer.id == container_id)
		.where(PhysicalContainer.tenant_id == user.tenant_id)
	)
	container = result.scalar_one_or_none()
	if not container:
		raise HTTPException(status_code=404, detail="Container not found")

	# Record verification event
	event = CustodyEvent(
		tenant_id=user.tenant_id,
		container_id=container_id,
		event_type="verify",
		performed_by_id=user.id,
	)
	db.add(event)

	# Update container
	container.last_verified_at = datetime.utcnow()
	container.last_verified_by_id = user.id

	await db.commit()

	return {"status": "verified", "verified_at": container.last_verified_at.isoformat()}


@router.get("/containers/{container_id}/custody", response_model=list[CustodyEventResponse])
async def get_container_custody_history(
	container_id: UUID,
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Get chain of custody history for a container."""
	result = await db.execute(
		select(CustodyEvent)
		.where(CustodyEvent.container_id == container_id)
		.where(CustodyEvent.tenant_id == user.tenant_id)
		.order_by(CustodyEvent.created_at.desc())
	)
	return result.scalars().all()


# ============ Barcode Scanning Endpoints ============

@router.post("/scan", response_model=ScanResponse)
async def process_scan(
	data: ScanRequest,
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Process a barcode/QR scan and resolve the entity."""
	resolved_type = None
	resolved_id = None
	resolved_data = None
	success = False
	error_message = None

	# Try to resolve as container barcode
	container_result = await db.execute(
		select(PhysicalContainer)
		.where(PhysicalContainer.barcode == data.scanned_code)
		.where(PhysicalContainer.tenant_id == user.tenant_id)
	)
	container = container_result.scalar_one_or_none()

	if container:
		resolved_type = "container"
		resolved_id = container.id
		resolved_data = {
			"barcode": container.barcode,
			"type": container.container_type,
			"label": container.label,
			"status": container.status,
			"item_count": container.item_count,
		}
		success = True
	else:
		# Try to resolve as location code
		location_result = await db.execute(
			select(WarehouseLocation)
			.where(WarehouseLocation.code == data.scanned_code)
			.where(WarehouseLocation.tenant_id == user.tenant_id)
		)
		location = location_result.scalar_one_or_none()

		if location:
			resolved_type = "location"
			resolved_id = location.id
			resolved_data = {
				"code": location.code,
				"name": location.name,
				"path": location.path,
				"current_count": location.current_count,
			}
			success = True
		else:
			# Try to parse as QR code data
			if data.scanned_code.startswith("D:"):
				# Extract document ID from compact format
				parts = data.scanned_code.split("|")
				doc_id = parts[0].replace("D:", "")
				resolved_type = "document"
				try:
					resolved_id = UUID(doc_id)
					resolved_data = {"document_id": doc_id}
					success = True
				except ValueError:
					error_message = "Invalid document ID format"
			else:
				error_message = f"Could not resolve code: {data.scanned_code}"

	# Log the scan
	scan_record = InventoryScan(
		tenant_id=user.tenant_id,
		scanned_code=data.scanned_code,
		code_type=data.code_type,
		success=success,
		resolved_container_id=resolved_id if resolved_type == "container" else None,
		resolved_document_id=resolved_id if resolved_type == "document" else None,
		resolved_location_id=resolved_id if resolved_type == "location" else None,
		error_message=error_message,
		scan_purpose=data.scan_purpose,
		scanner_device_id=data.scanner_device_id,
		scanned_by_id=user.id,
		latitude=int(data.latitude * 1000000) if data.latitude else None,
		longitude=int(data.longitude * 1000000) if data.longitude else None,
	)
	db.add(scan_record)
	await db.commit()

	return ScanResponse(
		success=success,
		resolved_type=resolved_type,
		resolved_id=resolved_id,
		resolved_data=resolved_data,
		error_message=error_message,
	)


@router.get("/scan/history")
async def get_scan_history(
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
	limit: int = Query(default=50, le=200),
	offset: int = Query(default=0),
):
	"""Get scan history for audit purposes."""
	result = await db.execute(
		select(InventoryScan)
		.where(InventoryScan.tenant_id == user.tenant_id)
		.order_by(InventoryScan.created_at.desc())
		.offset(offset)
		.limit(limit)
	)
	scans = result.scalars().all()

	return [
		{
			"id": str(s.id),
			"scanned_code": s.scanned_code,
			"code_type": s.code_type,
			"success": s.success,
			"scan_purpose": s.scan_purpose,
			"created_at": s.created_at.isoformat(),
		}
		for s in scans
	]


# ============ Container-Document Association ============

@router.post("/containers/{container_id}/documents")
async def add_document_to_container(
	container_id: UUID,
	document_id: UUID = Query(...),
	sequence_number: int | None = Query(default=None),
	page_count: int | None = Query(default=None),
	db: Annotated[AsyncSession, Depends(get_db)] = None,
	user: Annotated[User, Depends(get_current_user)] = None,
):
	"""Associate a document with a container."""
	# Verify container exists
	container_result = await db.execute(
		select(PhysicalContainer)
		.where(PhysicalContainer.id == container_id)
		.where(PhysicalContainer.tenant_id == user.tenant_id)
	)
	container = container_result.scalar_one_or_none()
	if not container:
		raise HTTPException(status_code=404, detail="Container not found")

	# Create association
	assoc = ContainerDocument(
		tenant_id=user.tenant_id,
		container_id=container_id,
		document_id=document_id,
		sequence_number=sequence_number,
		page_count=page_count,
	)
	db.add(assoc)

	# Update container item count
	container.item_count += 1

	await db.commit()

	return {"status": "added", "container_id": str(container_id), "document_id": str(document_id)}


@router.get("/containers/{container_id}/documents")
async def list_container_documents(
	container_id: UUID,
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""List all documents in a container."""
	result = await db.execute(
		select(ContainerDocument)
		.where(ContainerDocument.container_id == container_id)
		.where(ContainerDocument.tenant_id == user.tenant_id)
		.order_by(ContainerDocument.sequence_number)
	)
	docs = result.scalars().all()

	return [
		{
			"id": str(d.id),
			"document_id": str(d.document_id),
			"sequence_number": d.sequence_number,
			"page_count": d.page_count,
			"has_physical": d.has_physical,
			"verified": d.verified,
		}
		for d in docs
	]


# ============ Inventory Reports ============

@router.get("/reports/summary")
async def get_inventory_summary(
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Get summary statistics for physical inventory."""
	from sqlalchemy import func

	# Total containers by status
	status_result = await db.execute(
		select(PhysicalContainer.status, func.count(PhysicalContainer.id))
		.where(PhysicalContainer.tenant_id == user.tenant_id)
		.group_by(PhysicalContainer.status)
	)
	status_counts = {row[0]: row[1] for row in status_result.all()}

	# Total containers by type
	type_result = await db.execute(
		select(PhysicalContainer.container_type, func.count(PhysicalContainer.id))
		.where(PhysicalContainer.tenant_id == user.tenant_id)
		.group_by(PhysicalContainer.container_type)
	)
	type_counts = {row[0]: row[1] for row in type_result.all()}

	# Total locations
	location_count_result = await db.execute(
		select(func.count(WarehouseLocation.id))
		.where(WarehouseLocation.tenant_id == user.tenant_id)
	)
	total_locations = location_count_result.scalar() or 0

	# Overdue retention
	overdue_result = await db.execute(
		select(func.count(PhysicalContainer.id))
		.where(PhysicalContainer.tenant_id == user.tenant_id)
		.where(PhysicalContainer.retention_date < datetime.utcnow())
		.where(PhysicalContainer.destruction_eligible == True)
	)
	overdue_retention = overdue_result.scalar() or 0

	# Legal holds
	legal_hold_result = await db.execute(
		select(func.count(PhysicalContainer.id))
		.where(PhysicalContainer.tenant_id == user.tenant_id)
		.where(PhysicalContainer.legal_hold == True)
	)
	legal_holds = legal_hold_result.scalar() or 0

	return {
		"containers_by_status": status_counts,
		"containers_by_type": type_counts,
		"total_locations": total_locations,
		"overdue_for_retention": overdue_retention,
		"legal_holds": legal_holds,
	}

# Document Serial Number Router
# GitHub Issue #132: Automatically assign document serial numbers after upload
import re
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db import get_session
from papermerge.core.features.auth import get_current_user
from papermerge.core.features.auth.schema import User

from .service import SerialNumberService, SerialNumberError, DuplicateSerialNumberError
from .views import (
	SerialNumberSequenceCreate, SerialNumberSequenceUpdate, SerialNumberSequenceOut,
	DocumentSerialNumberOut, ManualSerialAssignment, SerialNumberSearch,
	SerialPatternPreview, SerialPatternPreviewResult, SerialNumberBulkGenerate,
)

router = APIRouter(prefix="/serial-numbers", tags=["Serial Numbers"])


async def get_service(session: Annotated[AsyncSession, Depends(get_session)]) -> SerialNumberService:
	return SerialNumberService(session)


# --- Sequence Management ---

@router.get("/sequences", response_model=list[SerialNumberSequenceOut])
async def list_sequences(
	service: Annotated[SerialNumberService, Depends(get_service)],
	user: Annotated[User, Depends(get_current_user)],
	include_inactive: bool = Query(False),
):
	"""List all serial number sequences."""
	sequences = await service.list_sequences(
		tenant_id=user.tenant_id,
		include_inactive=include_inactive,
	)

	# Add next preview
	results = []
	for seq in sequences:
		out = SerialNumberSequenceOut.model_validate(seq)
		# Generate preview
		now = datetime.now()
		preview = seq.pattern
		preview = preview.replace("{YEAR}", str(now.year))
		preview = preview.replace("{YY}", str(now.year)[-2:])
		preview = preview.replace("{MONTH}", f"{now.month:02d}")
		preview = preview.replace("{DAY}", f"{now.day:02d}")
		preview = preview.replace("{PREFIX}", seq.prefix)
		preview = preview.replace("{DOCTYPE}", "DOC")
		preview = re.sub(r"\{SEQ(?::(\d+))?\}", lambda m: str(seq.current_value + 1).zfill(int(m.group(1) or 0)), preview)
		out.next_preview = preview
		results.append(out)

	return results


@router.get("/sequences/{sequence_id}", response_model=SerialNumberSequenceOut)
async def get_sequence(
	sequence_id: str,
	service: Annotated[SerialNumberService, Depends(get_service)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Get a specific serial number sequence."""
	sequence = await service.get_sequence(sequence_id, user.tenant_id)
	if not sequence:
		raise HTTPException(status_code=404, detail="Sequence not found")
	return SerialNumberSequenceOut.model_validate(sequence)


@router.post("/sequences", response_model=SerialNumberSequenceOut, status_code=201)
async def create_sequence(
	data: SerialNumberSequenceCreate,
	service: Annotated[SerialNumberService, Depends(get_service)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Create a new serial number sequence."""
	sequence = await service.create_sequence(
		data,
		tenant_id=user.tenant_id,
		created_by_id=user.id,
	)
	return SerialNumberSequenceOut.model_validate(sequence)


@router.patch("/sequences/{sequence_id}", response_model=SerialNumberSequenceOut)
async def update_sequence(
	sequence_id: str,
	data: SerialNumberSequenceUpdate,
	service: Annotated[SerialNumberService, Depends(get_service)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Update a serial number sequence."""
	sequence = await service.update_sequence(sequence_id, data, user.tenant_id)
	if not sequence:
		raise HTTPException(status_code=404, detail="Sequence not found")
	return SerialNumberSequenceOut.model_validate(sequence)


@router.delete("/sequences/{sequence_id}", status_code=204)
async def delete_sequence(
	sequence_id: str,
	service: Annotated[SerialNumberService, Depends(get_service)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Delete a serial number sequence."""
	deleted = await service.delete_sequence(sequence_id, user.tenant_id)
	if not deleted:
		raise HTTPException(status_code=404, detail="Sequence not found")


# --- Serial Number Assignment ---

@router.post("/assign/{document_id}", response_model=DocumentSerialNumberOut)
async def assign_serial_number(
	document_id: str,
	service: Annotated[SerialNumberService, Depends(get_service)],
	user: Annotated[User, Depends(get_current_user)],
	document_type_id: str | None = Query(None),
	document_type_name: str | None = Query(None),
):
	"""Generate and assign a serial number to a document."""
	try:
		assignment = await service.generate_serial_number(
			document_id=document_id,
			document_type_id=document_type_id,
			document_type_name=document_type_name,
			tenant_id=user.tenant_id,
			assigned_by_id=user.id,
		)
		return DocumentSerialNumberOut.model_validate(assignment)
	except SerialNumberError as e:
		raise HTTPException(status_code=400, detail=str(e))


@router.post("/assign-manual", response_model=DocumentSerialNumberOut)
async def assign_manual_serial(
	data: ManualSerialAssignment,
	service: Annotated[SerialNumberService, Depends(get_service)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Manually assign a serial number to a document."""
	try:
		assignment = await service.assign_manual_serial(
			data,
			tenant_id=user.tenant_id,
			assigned_by_id=user.id,
		)
		return DocumentSerialNumberOut.model_validate(assignment)
	except DuplicateSerialNumberError as e:
		raise HTTPException(status_code=409, detail=str(e))
	except SerialNumberError as e:
		raise HTTPException(status_code=400, detail=str(e))


@router.post("/assign-bulk", response_model=list[DocumentSerialNumberOut])
async def assign_bulk_serial_numbers(
	data: SerialNumberBulkGenerate,
	service: Annotated[SerialNumberService, Depends(get_service)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Generate and assign serial numbers to multiple documents."""
	results = []
	errors = []

	for doc_id in data.document_ids:
		try:
			assignment = await service.generate_serial_number(
				document_id=doc_id,
				tenant_id=user.tenant_id,
				assigned_by_id=user.id,
			)
			results.append(DocumentSerialNumberOut.model_validate(assignment))
		except SerialNumberError as e:
			errors.append({"document_id": doc_id, "error": str(e)})

	if errors and not results:
		raise HTTPException(status_code=400, detail={"errors": errors})

	return results


# --- Lookup ---

@router.get("/document/{document_id}", response_model=DocumentSerialNumberOut | None)
async def get_document_serial(
	document_id: str,
	service: Annotated[SerialNumberService, Depends(get_service)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Get the serial number for a document."""
	assignment = await service.get_serial_for_document(document_id)
	if assignment:
		return DocumentSerialNumberOut.model_validate(assignment)
	return None


@router.get("/lookup/{serial_number}", response_model=DocumentSerialNumberOut | None)
async def lookup_by_serial(
	serial_number: str,
	service: Annotated[SerialNumberService, Depends(get_service)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Find a document by its serial number."""
	assignment = await service.get_document_by_serial(serial_number, user.tenant_id)
	if assignment:
		return DocumentSerialNumberOut.model_validate(assignment)
	return None


@router.get("/search", response_model=list[DocumentSerialNumberOut])
async def search_serials(
	query: str = Query(..., min_length=1),
	service: Annotated[SerialNumberService, Depends(get_service)],
	user: Annotated[User, Depends(get_current_user)],
	limit: int = Query(20, ge=1, le=100),
):
	"""Search documents by serial number."""
	results = await service.search_by_serial(
		query=query,
		tenant_id=user.tenant_id,
		limit=limit,
	)
	return [DocumentSerialNumberOut.model_validate(r) for r in results]


@router.delete("/document/{document_id}", status_code=204)
async def remove_serial(
	document_id: str,
	service: Annotated[SerialNumberService, Depends(get_service)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Remove serial number from a document."""
	removed = await service.remove_serial(document_id)
	if not removed:
		raise HTTPException(status_code=404, detail="No serial number found for document")


# --- Utilities ---

@router.post("/preview-pattern", response_model=SerialPatternPreviewResult)
async def preview_pattern(
	data: SerialPatternPreview,
	user: Annotated[User, Depends(get_current_user)],
):
	"""Preview what a pattern would generate."""
	now = datetime.now()
	preview = data.pattern

	placeholders = []
	placeholder_patterns = [
		("{YEAR}", str(now.year)),
		("{YY}", str(now.year)[-2:]),
		("{MONTH}", f"{now.month:02d}"),
		("{DAY}", f"{now.day:02d}"),
		("{WEEK}", f"{now.isocalendar()[1]:02d}"),
		("{PREFIX}", data.prefix),
		("{DOCTYPE}", data.document_type_name or "DOC"),
	]

	for placeholder, value in placeholder_patterns:
		if placeholder in preview:
			placeholders.append(placeholder)
			preview = preview.replace(placeholder, value)

	# Handle SEQ
	seq_match = re.search(r"\{SEQ(?::(\d+))?\}", preview)
	if seq_match:
		placeholders.append("{SEQ}")
		padding = int(seq_match.group(1) or 0)
		seq_str = "1".zfill(padding) if padding else "1"
		preview = re.sub(r"\{SEQ(?::\d+)?\}", seq_str, preview)

	return SerialPatternPreviewResult(
		pattern=data.pattern,
		preview=preview,
		placeholders_used=placeholders,
	)

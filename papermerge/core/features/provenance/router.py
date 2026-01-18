# (c) Copyright Datacraft, 2026
"""
API router for document provenance.
"""
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from uuid_extensions import uuid7str

from papermerge.core.db.engine import get_db
from papermerge.core.auth import get_current_user
from papermerge.core.features.users.db.orm import User

from .db.orm import (
	DocumentProvenance,
	ProvenanceEvent,
	EventType,
	VerificationStatus,
)
from .schema import (
	DocumentProvenanceCreate,
	DocumentProvenanceUpdate,
	DocumentProvenance as ProvenanceSchema,
	DocumentProvenanceWithEvents,
	DocumentProvenanceSummary,
	ProvenanceEventCreate,
	ProvenanceEvent as EventSchema,
	ProvenanceEventSummary,
	VerifyDocumentRequest,
	VerificationResult,
	ChainOfCustody,
	ChainOfCustodyEntry,
	ProvenanceStats,
)

router = APIRouter(prefix="/provenance", tags=["provenance"])


# ============ Document Provenance ============

@router.get("", response_model=list[DocumentProvenanceSummary])
async def list_provenance(
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
	batch_id: str | None = None,
	verification_status: VerificationStatus | None = None,
	is_duplicate: bool | None = None,
	ingestion_source: str | None = None,
	skip: int = 0,
	limit: int = 50,
):
	"""List document provenance records with filtering."""
	query = select(DocumentProvenance)

	if batch_id:
		query = query.where(DocumentProvenance.batch_id == batch_id)
	if verification_status:
		query = query.where(DocumentProvenance.verification_status == verification_status)
	if is_duplicate is not None:
		query = query.where(DocumentProvenance.is_duplicate == is_duplicate)
	if ingestion_source:
		query = query.where(DocumentProvenance.ingestion_source == ingestion_source)

	query = query.order_by(DocumentProvenance.created_at.desc())
	query = query.offset(skip).limit(limit)

	result = await db.execute(query)
	records = result.scalars().all()

	# Get event counts
	summaries = []
	for record in records:
		event_count_result = await db.execute(
			select(func.count(ProvenanceEvent.id))
			.where(ProvenanceEvent.provenance_id == record.id)
		)
		event_count = event_count_result.scalar() or 0

		last_event_result = await db.execute(
			select(ProvenanceEvent.timestamp)
			.where(ProvenanceEvent.provenance_id == record.id)
			.order_by(ProvenanceEvent.timestamp.desc())
			.limit(1)
		)
		last_event = last_event_result.scalar_one_or_none()

		summaries.append(DocumentProvenanceSummary(
			id=record.id,
			document_id=record.document_id,
			batch_id=record.batch_id,
			ingestion_source=record.ingestion_source,
			verification_status=record.verification_status,
			is_duplicate=record.is_duplicate,
			event_count=event_count,
			last_event_at=last_event,
		))

	return summaries


@router.get("/stats", response_model=ProvenanceStats)
async def get_provenance_stats(
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Get provenance statistics."""
	# Total documents
	total_result = await db.execute(select(func.count(DocumentProvenance.id)))
	total_documents = total_result.scalar() or 0

	# By verification status
	status_result = await db.execute(
		select(DocumentProvenance.verification_status, func.count(DocumentProvenance.id))
		.group_by(DocumentProvenance.verification_status)
	)
	status_counts = {str(row[0].value): row[1] for row in status_result}

	# Duplicates
	dup_result = await db.execute(
		select(func.count(DocumentProvenance.id))
		.where(DocumentProvenance.is_duplicate == True)
	)
	duplicate_count = dup_result.scalar() or 0

	# By source
	source_result = await db.execute(
		select(DocumentProvenance.ingestion_source, func.count(DocumentProvenance.id))
		.where(DocumentProvenance.ingestion_source.isnot(None))
		.group_by(DocumentProvenance.ingestion_source)
	)
	documents_by_source = {row[0]: row[1] for row in source_result}

	# Recent events
	recent_events_result = await db.execute(
		select(ProvenanceEvent)
		.order_by(ProvenanceEvent.timestamp.desc())
		.limit(10)
	)
	recent_events = recent_events_result.scalars().all()

	return ProvenanceStats(
		total_documents=total_documents,
		verified_count=status_counts.get("verified", 0),
		pending_count=status_counts.get("pending", 0),
		unverified_count=status_counts.get("unverified", 0),
		duplicate_count=duplicate_count,
		documents_by_source=documents_by_source,
		documents_by_status=status_counts,
		recent_events=[
			ProvenanceEventSummary.model_validate(e) for e in recent_events
		],
	)


@router.post("", response_model=ProvenanceSchema, status_code=status.HTTP_201_CREATED)
async def create_provenance(
	data: DocumentProvenanceCreate,
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Create provenance record for a document."""
	# Check if provenance already exists
	existing = await db.execute(
		select(DocumentProvenance)
		.where(DocumentProvenance.document_id == data.document_id)
	)
	if existing.scalar_one_or_none():
		raise HTTPException(
			status_code=400,
			detail="Provenance record already exists for this document"
		)

	provenance = DocumentProvenance(
		id=uuid7str(),
		ingestion_timestamp=datetime.utcnow(),
		ingestion_user_id=user.id,
		**data.model_dump(),
	)
	db.add(provenance)

	# Create initial event
	event = ProvenanceEvent(
		id=uuid7str(),
		provenance_id=provenance.id,
		event_type=EventType.CREATED,
		actor_id=user.id,
		actor_type="user",
		description="Document provenance record created",
	)
	db.add(event)

	await db.commit()
	await db.refresh(provenance)
	return provenance


@router.get("/document/{document_id}", response_model=DocumentProvenanceWithEvents)
async def get_document_provenance(
	document_id: UUID,
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Get provenance record for a specific document."""
	result = await db.execute(
		select(DocumentProvenance)
		.where(DocumentProvenance.document_id == document_id)
	)
	provenance = result.scalar_one_or_none()
	if not provenance:
		raise HTTPException(status_code=404, detail="Provenance record not found")

	# Get events
	events_result = await db.execute(
		select(ProvenanceEvent)
		.where(ProvenanceEvent.provenance_id == provenance.id)
		.order_by(ProvenanceEvent.timestamp.desc())
	)
	events = events_result.scalars().all()

	return DocumentProvenanceWithEvents(
		**ProvenanceSchema.model_validate(provenance).model_dump(),
		events=[ProvenanceEventSummary.model_validate(e) for e in events],
	)


@router.get("/{provenance_id}", response_model=DocumentProvenanceWithEvents)
async def get_provenance(
	provenance_id: str,
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Get a specific provenance record."""
	result = await db.execute(
		select(DocumentProvenance)
		.where(DocumentProvenance.id == provenance_id)
	)
	provenance = result.scalar_one_or_none()
	if not provenance:
		raise HTTPException(status_code=404, detail="Provenance record not found")

	# Get events
	events_result = await db.execute(
		select(ProvenanceEvent)
		.where(ProvenanceEvent.provenance_id == provenance.id)
		.order_by(ProvenanceEvent.timestamp.desc())
	)
	events = events_result.scalars().all()

	return DocumentProvenanceWithEvents(
		**ProvenanceSchema.model_validate(provenance).model_dump(),
		events=[ProvenanceEventSummary.model_validate(e) for e in events],
	)


@router.patch("/{provenance_id}", response_model=ProvenanceSchema)
async def update_provenance(
	provenance_id: str,
	data: DocumentProvenanceUpdate,
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Update a provenance record."""
	result = await db.execute(
		select(DocumentProvenance)
		.where(DocumentProvenance.id == provenance_id)
	)
	provenance = result.scalar_one_or_none()
	if not provenance:
		raise HTTPException(status_code=404, detail="Provenance record not found")

	update_data = data.model_dump(exclude_unset=True)
	old_status = provenance.verification_status

	for key, value in update_data.items():
		setattr(provenance, key, value)

	provenance.updated_at = datetime.utcnow()

	# Track status change
	if data.verification_status and data.verification_status != old_status:
		event = ProvenanceEvent(
			id=uuid7str(),
			provenance_id=provenance.id,
			event_type=EventType.VERIFIED if data.verification_status == VerificationStatus.VERIFIED else EventType.EDITED,
			actor_id=user.id,
			actor_type="user",
			description=f"Verification status changed from {old_status.value} to {data.verification_status.value}",
			previous_state={"verification_status": old_status.value},
			new_state={"verification_status": data.verification_status.value},
		)
		db.add(event)

	await db.commit()
	await db.refresh(provenance)
	return provenance


@router.post("/{provenance_id}/verify", response_model=VerificationResult)
async def verify_document(
	provenance_id: str,
	data: VerifyDocumentRequest,
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Verify document integrity and mark as verified."""
	from papermerge.core.features.document.db.orm import Document, DocumentVersion

	result = await db.execute(
		select(DocumentProvenance)
		.where(DocumentProvenance.id == provenance_id)
	)
	provenance = result.scalar_one_or_none()
	if not provenance:
		raise HTTPException(status_code=404, detail="Provenance record not found")

	# Compute actual hash from document file
	current_hash = None
	hash_match = True

	# Get the document and its latest version
	doc_result = await db.execute(
		select(Document).where(Document.id == provenance.document_id)
	)
	document = doc_result.scalar_one_or_none()

	if document:
		# Get latest document version
		ver_result = await db.execute(
			select(DocumentVersion)
			.where(DocumentVersion.document_id == document.id)
			.order_by(DocumentVersion.number.desc())
			.limit(1)
		)
		version = ver_result.scalar_one_or_none()

		if version and version.file_path.exists():
			# Compute SHA-512 hash
			sha512 = hashlib.sha512()
			with open(version.file_path, 'rb') as f:
				for chunk in iter(lambda: f.read(8192), b''):
					sha512.update(chunk)
			current_hash = sha512.hexdigest()

			# Update stored current hash
			provenance.current_file_hash = current_hash

			# Compare with original hash
			if provenance.original_file_hash:
				hash_match = current_hash == provenance.original_file_hash

	# If no file found, use stored hash or indicate not verified
	if current_hash is None:
		current_hash = provenance.current_file_hash or "file_not_found"
		hash_match = False

	# Update provenance
	provenance.verification_status = VerificationStatus.VERIFIED
	provenance.verified_at = datetime.utcnow()
	provenance.verified_by_id = user.id
	provenance.verification_notes = data.verification_notes
	provenance.last_hash_verified_at = datetime.utcnow()
	provenance.updated_at = datetime.utcnow()

	# Add event
	event = ProvenanceEvent(
		id=uuid7str(),
		provenance_id=provenance.id,
		event_type=EventType.VERIFIED,
		actor_id=user.id,
		actor_type="user",
		description="Document verified",
		details={
			"hash_match": hash_match,
			"notes": data.verification_notes,
		},
	)
	db.add(event)

	await db.commit()
	await db.refresh(provenance)

	return VerificationResult(
		document_id=provenance.document_id,
		provenance_id=provenance.id,
		verification_status=provenance.verification_status,
		verified_at=provenance.verified_at,
		verified_by_id=user.id,
		integrity_check_passed=hash_match,
		hash_match=hash_match,
		current_hash=current_hash,
		original_hash=provenance.original_file_hash,
	)


@router.get("/{provenance_id}/chain", response_model=ChainOfCustody)
async def get_chain_of_custody(
	provenance_id: str,
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Get complete chain of custody for a document."""
	result = await db.execute(
		select(DocumentProvenance)
		.where(DocumentProvenance.id == provenance_id)
	)
	provenance = result.scalar_one_or_none()
	if not provenance:
		raise HTTPException(status_code=404, detail="Provenance record not found")

	# Get all events
	events_result = await db.execute(
		select(ProvenanceEvent)
		.where(ProvenanceEvent.provenance_id == provenance.id)
		.order_by(ProvenanceEvent.timestamp.asc())
	)
	events = events_result.scalars().all()

	# Build chain entries
	entries = []
	for event in events:
		entries.append(ChainOfCustodyEntry(
			timestamp=event.timestamp,
			event_type=event.event_type,
			actor_id=event.actor_id,
			actor_name=None,  # Would need to join with users table
			description=event.description or f"{event.event_type.value} event",
			verified=event.event_type == EventType.VERIFIED,
		))

	return ChainOfCustody(
		document_id=provenance.document_id,
		provenance_id=provenance.id,
		original_source=provenance.ingestion_source,
		ingestion_timestamp=provenance.ingestion_timestamp,
		entries=entries,
		current_verification_status=provenance.verification_status,
		is_complete=len(events) > 0,
	)


# ============ Provenance Events ============

@router.post("/events", response_model=EventSchema, status_code=status.HTTP_201_CREATED)
async def create_event(
	data: ProvenanceEventCreate,
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Create a new provenance event."""
	# Verify provenance exists
	prov_result = await db.execute(
		select(DocumentProvenance)
		.where(DocumentProvenance.id == data.provenance_id)
	)
	if not prov_result.scalar_one_or_none():
		raise HTTPException(status_code=404, detail="Provenance record not found")

	# Get previous event for hash chain
	prev_event_result = await db.execute(
		select(ProvenanceEvent)
		.where(ProvenanceEvent.provenance_id == data.provenance_id)
		.order_by(ProvenanceEvent.timestamp.desc())
		.limit(1)
	)
	prev_event = prev_event_result.scalar_one_or_none()

	event = ProvenanceEvent(
		id=uuid7str(),
		actor_id=user.id,
		previous_event_hash=prev_event.event_hash if prev_event else None,
		**data.model_dump(),
	)

	# Compute event hash for chain integrity
	hash_data = f"{event.id}|{event.provenance_id}|{event.event_type}|{event.timestamp}|{event.previous_event_hash or ''}"
	event.event_hash = hashlib.sha256(hash_data.encode()).hexdigest()

	db.add(event)
	await db.commit()
	await db.refresh(event)
	return event


@router.get("/events/{event_id}", response_model=EventSchema)
async def get_event(
	event_id: str,
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Get a specific provenance event."""
	result = await db.execute(
		select(ProvenanceEvent)
		.where(ProvenanceEvent.id == event_id)
	)
	event = result.scalar_one_or_none()
	if not event:
		raise HTTPException(status_code=404, detail="Event not found")
	return event


@router.get("/{provenance_id}/events", response_model=list[EventSchema])
async def list_provenance_events(
	provenance_id: str,
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
	event_type: EventType | None = None,
	skip: int = 0,
	limit: int = 100,
):
	"""List events for a provenance record."""
	query = select(ProvenanceEvent).where(
		ProvenanceEvent.provenance_id == provenance_id
	)

	if event_type:
		query = query.where(ProvenanceEvent.event_type == event_type)

	query = query.order_by(ProvenanceEvent.timestamp.desc())
	query = query.offset(skip).limit(limit)

	result = await db.execute(query)
	return result.scalars().all()

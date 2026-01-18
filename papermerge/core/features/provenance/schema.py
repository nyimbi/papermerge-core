# (c) Copyright Datacraft, 2026
"""
Pydantic schemas for document provenance.
"""
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
from uuid import UUID

from .db.orm import EventType, VerificationStatus


# Provenance Event schemas
class ProvenanceEventBase(BaseModel):
	event_type: EventType
	description: str | None = None
	actor_type: str | None = Field(None, max_length=50)
	previous_state: dict | None = None
	new_state: dict | None = None
	related_document_id: UUID | None = None
	workflow_id: str | None = None
	workflow_step_id: str | None = None
	details: dict | None = None


class ProvenanceEventCreate(ProvenanceEventBase):
	provenance_id: str


class ProvenanceEvent(ProvenanceEventBase):
	model_config = ConfigDict(from_attributes=True)

	id: str
	provenance_id: str
	timestamp: datetime
	actor_id: UUID | None = None
	ip_address: str | None = None
	user_agent: str | None = None
	event_hash: str | None = None
	previous_event_hash: str | None = None


class ProvenanceEventSummary(BaseModel):
	model_config = ConfigDict(from_attributes=True)

	id: str
	event_type: EventType
	timestamp: datetime
	description: str | None = None
	actor_id: UUID | None = None


# Document Provenance schemas
class DocumentProvenanceBase(BaseModel):
	batch_id: str | None = None
	original_filename: str | None = Field(None, max_length=500)
	source_location_detail: str | None = None
	physical_reference: str | None = Field(None, max_length=255)
	ingestion_source: str | None = Field(None, max_length=50)
	scanner_model: str | None = Field(None, max_length=200)
	scan_resolution_dpi: int | None = None
	scan_color_mode: str | None = Field(None, max_length=50)
	scan_settings: dict | None = None
	metadata: dict | None = None


class DocumentProvenanceCreate(DocumentProvenanceBase):
	document_id: UUID


class DocumentProvenanceUpdate(BaseModel):
	batch_id: str | None = None
	source_location_detail: str | None = None
	physical_reference: str | None = Field(None, max_length=255)
	verification_status: VerificationStatus | None = None
	verification_notes: str | None = None
	metadata: dict | None = None


class DocumentProvenance(DocumentProvenanceBase):
	model_config = ConfigDict(from_attributes=True)

	id: str
	document_id: UUID
	original_file_hash: str | None
	original_file_size: int | None
	original_mime_type: str | None
	current_file_hash: str | None
	last_hash_verified_at: datetime | None
	ingestion_timestamp: datetime | None
	ingestion_user_id: UUID | None
	original_page_count: int | None
	current_page_count: int | None
	verification_status: VerificationStatus
	verified_at: datetime | None
	verified_by_id: UUID | None
	verification_notes: str | None
	digital_signature: str | None
	signature_algorithm: str | None
	signature_timestamp: datetime | None
	is_duplicate: bool
	duplicate_of_id: str | None
	similarity_hash: str | None
	tenant_id: UUID | None
	created_at: datetime
	updated_at: datetime


class DocumentProvenanceWithEvents(DocumentProvenance):
	events: list[ProvenanceEventSummary] = []


class DocumentProvenanceSummary(BaseModel):
	model_config = ConfigDict(from_attributes=True)

	id: str
	document_id: UUID
	batch_id: str | None
	ingestion_source: str | None
	verification_status: VerificationStatus
	is_duplicate: bool
	event_count: int = 0
	last_event_at: datetime | None = None


# Verification schemas
class VerifyDocumentRequest(BaseModel):
	verification_notes: str | None = None


class VerificationResult(BaseModel):
	document_id: UUID
	provenance_id: str
	verification_status: VerificationStatus
	verified_at: datetime
	verified_by_id: UUID
	integrity_check_passed: bool
	hash_match: bool
	current_hash: str
	original_hash: str | None


# Chain of custody
class ChainOfCustodyEntry(BaseModel):
	timestamp: datetime
	event_type: EventType
	actor_id: UUID | None
	actor_name: str | None
	description: str
	location: str | None = None
	verified: bool = False


class ChainOfCustody(BaseModel):
	document_id: UUID
	provenance_id: str
	original_source: str | None
	ingestion_timestamp: datetime | None
	entries: list[ChainOfCustodyEntry]
	current_verification_status: VerificationStatus
	is_complete: bool = True


# Statistics
class ProvenanceStats(BaseModel):
	total_documents: int
	verified_count: int
	pending_count: int
	unverified_count: int
	duplicate_count: int
	documents_by_source: dict[str, int]
	documents_by_status: dict[str, int]
	recent_events: list[ProvenanceEventSummary]

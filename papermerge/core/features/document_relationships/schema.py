from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RelationshipType = Literal[
	"related",
	"supersedes",
	"amendment_of",
	"attachment_to",
	"version_of",
]


class DocumentRelationshipBase(BaseModel):
	relationship_type: RelationshipType
	note: str | None = None


class CreateDocumentRelationship(DocumentRelationshipBase):
	target_document_id: uuid.UUID

	model_config = ConfigDict(from_attributes=True)


class DocumentRelationshipOut(DocumentRelationshipBase):
	id: uuid.UUID
	source_document_id: uuid.UUID
	target_document_id: uuid.UUID
	tenant_id: str | None = None
	created_by_id: uuid.UUID
	created_at: datetime

	# Minimal denormalised target doc info (populated by router via join)
	target_title: str | None = Field(default=None)
	source_title: str | None = Field(default=None)

	model_config = ConfigDict(from_attributes=True)


class DocumentRelationshipGroup(BaseModel):
	"""Relationships for a document grouped by type."""

	relationship_type: RelationshipType
	items: list[DocumentRelationshipOut]

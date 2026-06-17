"""
Duplicate detection API.

Routes:
  GET  /documents/{document_id}/duplicates   — list duplicates for an existing doc
  POST /documents/check-duplicate            — pre-upload check by file_hash
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.engine import get_db
from papermerge.core.features.auth.dependencies import require_scopes
from papermerge.core.features.auth import scopes
from papermerge.core.features.dedup import service

logger = logging.getLogger(__name__)

router = APIRouter(
	prefix="/documents",
	tags=["dedup"],
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class DuplicateEntry(BaseModel):
	document_id: str
	title: str | None
	created_at: str | None
	match_type: str  # "exact" | "content"

	model_config = {"from_attributes": True}

	@classmethod
	def from_dict(cls, d: dict) -> "DuplicateEntry":
		created_at = d.get("created_at")
		return cls(
			document_id=d["document_id"],
			title=d.get("title"),
			created_at=created_at.isoformat() if created_at else None,
			match_type=d["match_type"],
		)


class CheckDuplicateRequest(BaseModel):
	file_hash: str


class CheckDuplicateResponse(BaseModel):
	is_duplicate: bool
	existing_documents: list[DuplicateEntry]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get(
	"/{document_id}/duplicates",
	response_model=list[DuplicateEntry],
	summary="List potential duplicates for a document",
)
async def list_duplicates(
	document_id: uuid.UUID,
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
) -> list[DuplicateEntry]:
	tenant_id = getattr(user, "tenant_id", None) or ""
	results = await service.find_duplicates(
		document_id=str(document_id),
		tenant_id=tenant_id,
		session=db_session,
	)
	return [DuplicateEntry.from_dict(r) for r in results]


@router.post(
	"/check-duplicate",
	response_model=CheckDuplicateResponse,
	summary="Check if a file hash matches an existing document (pre-upload)",
)
async def check_duplicate(
	body: CheckDuplicateRequest,
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
) -> CheckDuplicateResponse:
	if not body.file_hash or len(body.file_hash) != 64:
		raise HTTPException(
			status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
			detail="file_hash must be a 64-character SHA-256 hex string",
		)

	tenant_id = getattr(user, "tenant_id", None) or ""
	matches = await service.check_file_hash_duplicate(
		file_hash=body.file_hash,
		tenant_id=tenant_id,
		session=db_session,
	)
	return CheckDuplicateResponse(
		is_duplicate=len(matches) > 0,
		existing_documents=[DuplicateEntry.from_dict(m) for m in matches],
	)

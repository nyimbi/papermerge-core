"""Document relationship linking API.

Routes:
  GET  /documents/{document_id}/relationships        — list (both directions)
  POST /documents/{document_id}/relationships        — create
  DELETE /documents/{document_id}/relationships/{id} — delete
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, or_, delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.engine import get_db
from papermerge.core.features.auth.dependencies import require_scopes
from papermerge.core.features.auth import scopes
from papermerge.core.features.document_relationships.db.orm import DocumentRelationship
from papermerge.core.features.document_relationships.schema import (
	CreateDocumentRelationship,
	DocumentRelationshipOut,
)

logger = logging.getLogger(__name__)

router = APIRouter(
	prefix="/documents",
	tags=["document-relationships"],
)

VALID_TYPES = {"related", "supersedes", "amendment_of", "attachment_to", "version_of"}


async def _get_node_title(session: AsyncSession, node_id: uuid.UUID) -> str | None:
	"""Return the title of a node by id, or None if not found."""
	from sqlalchemy import text
	row = await session.execute(
		text("SELECT title FROM nodes WHERE id = :nid"),
		{"nid": node_id},
	)
	r = row.fetchone()
	return r[0] if r else None


def _to_out(rel: DocumentRelationship, source_title: str | None, target_title: str | None) -> DocumentRelationshipOut:
	return DocumentRelationshipOut(
		id=rel.id,
		source_document_id=rel.source_document_id,
		target_document_id=rel.target_document_id,
		relationship_type=rel.relationship_type,  # type: ignore[arg-type]
		note=rel.note,
		tenant_id=rel.tenant_id,
		created_by_id=rel.created_by_id,
		created_at=rel.created_at,
		source_title=source_title,
		target_title=target_title,
	)


@router.get(
	"/{document_id}/relationships",
	response_model=list[DocumentRelationshipOut],
	summary="List all relationships for a document (both directions)",
)
async def list_relationships(
	document_id: uuid.UUID,
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
) -> list[DocumentRelationshipOut]:
	stmt = select(DocumentRelationship).where(
		or_(
			DocumentRelationship.source_document_id == document_id,
			DocumentRelationship.target_document_id == document_id,
		)
	).order_by(DocumentRelationship.created_at.desc())

	result = await db_session.execute(stmt)
	rels = result.scalars().all()

	# Batch-fetch titles for all referenced document node IDs
	node_ids: set[uuid.UUID] = set()
	for rel in rels:
		node_ids.add(rel.source_document_id)
		node_ids.add(rel.target_document_id)

	titles: dict[uuid.UUID, str | None] = {}
	for nid in node_ids:
		titles[nid] = await _get_node_title(db_session, nid)

	return [_to_out(rel, titles.get(rel.source_document_id), titles.get(rel.target_document_id)) for rel in rels]


@router.post(
	"/{document_id}/relationships",
	response_model=DocumentRelationshipOut,
	status_code=status.HTTP_201_CREATED,
	summary="Create a relationship between two documents",
)
async def create_relationship(
	document_id: uuid.UUID,
	body: CreateDocumentRelationship,
	user: require_scopes(scopes.NODE_UPDATE),
	db_session: AsyncSession = Depends(get_db),
) -> DocumentRelationshipOut:
	if body.relationship_type not in VALID_TYPES:
		raise HTTPException(
			status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
			detail=f"Invalid relationship_type. Must be one of: {sorted(VALID_TYPES)}",
		)

	if body.target_document_id == document_id:
		raise HTTPException(
			status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
			detail="source and target document must differ",
		)

	# Idempotency: return existing if already linked with same type
	existing_stmt = select(DocumentRelationship).where(
		DocumentRelationship.source_document_id == document_id,
		DocumentRelationship.target_document_id == body.target_document_id,
		DocumentRelationship.relationship_type == body.relationship_type,
	)
	existing = (await db_session.execute(existing_stmt)).scalar_one_or_none()
	if existing:
		source_title = await _get_node_title(db_session, existing.source_document_id)
		target_title = await _get_node_title(db_session, existing.target_document_id)
		return _to_out(existing, source_title, target_title)

	rel = DocumentRelationship(
		source_document_id=document_id,
		target_document_id=body.target_document_id,
		relationship_type=body.relationship_type,
		note=body.note,
		tenant_id=getattr(user, "tenant_id", None),
		created_by_id=user.id,
	)
	db_session.add(rel)
	await db_session.commit()
	await db_session.refresh(rel)

	source_title = await _get_node_title(db_session, rel.source_document_id)
	target_title = await _get_node_title(db_session, rel.target_document_id)
	return _to_out(rel, source_title, target_title)


@router.delete(
	"/{document_id}/relationships/{relationship_id}",
	status_code=status.HTTP_204_NO_CONTENT,
	summary="Delete a document relationship",
)
async def delete_relationship(
	document_id: uuid.UUID,
	relationship_id: uuid.UUID,
	user: require_scopes(scopes.NODE_UPDATE),
	db_session: AsyncSession = Depends(get_db),
) -> None:
	stmt = select(DocumentRelationship).where(
		DocumentRelationship.id == relationship_id,
		or_(
			DocumentRelationship.source_document_id == document_id,
			DocumentRelationship.target_document_id == document_id,
		),
	)
	rel = (await db_session.execute(stmt)).scalar_one_or_none()
	if not rel:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Relationship not found")

	await db_session.execute(
		sa_delete(DocumentRelationship).where(DocumentRelationship.id == relationship_id)
	)
	await db_session.commit()

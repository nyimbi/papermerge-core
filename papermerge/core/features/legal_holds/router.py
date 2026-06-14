# (c) Copyright Datacraft, 2026
"""Document legal holds and retention management API."""
import logging
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.features.auth import get_current_user
from papermerge.core.features.users.schema import User
from papermerge.core.db.engine import get_db
from papermerge.core.features.document.db.orm import Document

logger = logging.getLogger(__name__)

router = APIRouter(
	prefix="/legal-holds",
	tags=["legal-holds"],
)


class LegalHoldRequest(BaseModel):
	reason: str | None = None


class RetentionRequest(BaseModel):
	retention_date: datetime | None = None
	retention_policy: str | None = None


class DocumentHoldStatus(BaseModel):
	document_id: str
	legal_hold: bool
	retention_date: datetime | None
	retention_policy: str | None


@router.get("/{document_id}", response_model=DocumentHoldStatus)
async def get_hold_status(
	document_id: UUID,
	user: Annotated[User, Depends(get_current_user)],
	db: AsyncSession = Depends(get_db),
) -> DocumentHoldStatus:
	"""Get legal hold and retention status for a document."""
	doc = await db.get(Document, document_id)
	if not doc:
		raise HTTPException(status_code=404, detail="Document not found")
	return DocumentHoldStatus(
		document_id=str(doc.id),
		legal_hold=doc.legal_hold,
		retention_date=doc.retention_date,
		retention_policy=doc.retention_policy,
	)


@router.put("/{document_id}/hold")
async def set_legal_hold(
	document_id: UUID,
	body: LegalHoldRequest,
	user: Annotated[User, Depends(get_current_user)],
	db: AsyncSession = Depends(get_db),
) -> DocumentHoldStatus:
	"""Place a legal hold on a document. Prevents deletion and expiry."""
	doc = await db.get(Document, document_id)
	if not doc:
		raise HTTPException(status_code=404, detail="Document not found")
	doc.legal_hold = True
	await db.commit()
	logger.info(f"Legal hold set on document {document_id} by user {user.id}")
	return DocumentHoldStatus(
		document_id=str(doc.id),
		legal_hold=True,
		retention_date=doc.retention_date,
		retention_policy=doc.retention_policy,
	)


@router.delete("/{document_id}/hold", status_code=200)
async def lift_legal_hold(
	document_id: UUID,
	user: Annotated[User, Depends(get_current_user)],
	db: AsyncSession = Depends(get_db),
) -> DocumentHoldStatus:
	"""Lift the legal hold on a document."""
	doc = await db.get(Document, document_id)
	if not doc:
		raise HTTPException(status_code=404, detail="Document not found")
	doc.legal_hold = False
	await db.commit()
	logger.info(f"Legal hold lifted on document {document_id} by user {user.id}")
	return DocumentHoldStatus(
		document_id=str(doc.id),
		legal_hold=False,
		retention_date=doc.retention_date,
		retention_policy=doc.retention_policy,
	)


@router.put("/{document_id}/retention")
async def set_retention(
	document_id: UUID,
	body: RetentionRequest,
	user: Annotated[User, Depends(get_current_user)],
	db: AsyncSession = Depends(get_db),
) -> DocumentHoldStatus:
	"""Set the retention date and policy for a document."""
	doc = await db.get(Document, document_id)
	if not doc:
		raise HTTPException(status_code=404, detail="Document not found")
	doc.retention_date = body.retention_date
	doc.retention_policy = body.retention_policy
	await db.commit()
	return DocumentHoldStatus(
		document_id=str(doc.id),
		legal_hold=doc.legal_hold,
		retention_date=doc.retention_date,
		retention_policy=doc.retention_policy,
	)


@router.post("/expire", status_code=200)
async def expire_documents(
	user: Annotated[User, Depends(get_current_user)],
	db: AsyncSession = Depends(get_db),
	dry_run: bool = True,
) -> dict:
	"""
	Find and (optionally) delete documents past their retention date.

	Documents with legal_hold=True are never deleted regardless of retention_date.
	Set dry_run=false to actually delete expired documents.
	"""
	now = datetime.utcnow()
	stmt = select(Document).where(
		Document.retention_date != None,  # noqa: E711
		Document.retention_date < now,
		Document.legal_hold == False,  # noqa: E712
	)
	result = await db.execute(stmt)
	expired = result.scalars().all()

	if not dry_run:
		for doc in expired:
			await db.delete(doc)
		await db.commit()
		logger.info(f"Expired {len(expired)} documents (user={user.id})")

	return {
		"expired_count": len(expired),
		"dry_run": dry_run,
		"document_ids": [str(d.id) for d in expired],
	}

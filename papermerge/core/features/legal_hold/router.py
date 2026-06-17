# (c) Copyright Datacraft, 2026
"""Named legal hold REST endpoints — auto-discovered by router_loader."""
import logging
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.engine import get_db
from papermerge.core.features.auth import get_current_user
from papermerge.core.features.users.schema import User
from papermerge.core.utils.tz import utc_now

from .db.orm import LegalHold

_log = logging.getLogger(__name__)

router = APIRouter(tags=["legal-hold"])


# ── Pydantic I/O schemas ──────────────────────────────────────────────────────

class PlaceHoldIn(BaseModel):
	hold_name: str
	hold_reason: str


class LegalHoldOut(BaseModel):
	id: str
	document_id: str
	hold_name: str
	hold_reason: str
	held_by_id: str
	released_by_id: str | None
	held_at: datetime
	released_at: datetime | None
	tenant_id: str

	class Config:
		from_attributes = True


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get(
	"/documents/{document_id}/legal-holds",
	response_model=list[LegalHoldOut],
	summary="List all legal holds for a document (active and released)",
)
async def list_legal_holds(
	document_id: UUID,
	user: Annotated[User, Depends(get_current_user)],
	db: AsyncSession = Depends(get_db),
) -> list[LegalHoldOut]:
	stmt = (
		select(LegalHold)
		.where(LegalHold.document_id == str(document_id))
		.order_by(LegalHold.held_at.desc())
	)
	result = await db.execute(stmt)
	holds = result.scalars().all()
	return [LegalHoldOut.model_validate(h) for h in holds]


@router.post(
	"/documents/{document_id}/legal-holds",
	response_model=LegalHoldOut,
	status_code=status.HTTP_201_CREATED,
	summary="Place a named legal hold on a document",
)
async def place_legal_hold(
	document_id: UUID,
	body: PlaceHoldIn,
	user: Annotated[User, Depends(get_current_user)],
	db: AsyncSession = Depends(get_db),
) -> LegalHoldOut:
	tenant_id = str(getattr(user, "tenant_id", None) or user.id)
	hold = LegalHold(
		document_id=str(document_id),
		hold_name=body.hold_name.strip(),
		hold_reason=body.hold_reason.strip(),
		held_by_id=str(user.id),
		tenant_id=tenant_id,
	)
	db.add(hold)
	await db.commit()
	await db.refresh(hold)
	_log.info("Legal hold %r placed on document %s by user %s", hold.hold_name, document_id, user.id)
	return LegalHoldOut.model_validate(hold)


@router.delete(
	"/legal-holds/{hold_id}",
	response_model=LegalHoldOut,
	summary="Release a legal hold (sets released_at; does not delete the record)",
)
async def release_legal_hold(
	hold_id: UUID,
	user: Annotated[User, Depends(get_current_user)],
	db: AsyncSession = Depends(get_db),
) -> LegalHoldOut:
	hold = await db.get(LegalHold, str(hold_id))
	if hold is None:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Legal hold not found")
	if hold.released_at is not None:
		raise HTTPException(
			status_code=status.HTTP_409_CONFLICT,
			detail="Legal hold is already released",
		)
	hold.released_at = utc_now()
	hold.released_by_id = str(user.id)
	await db.commit()
	await db.refresh(hold)
	_log.info("Legal hold %r on document %s released by user %s", hold.hold_name, hold.document_id, user.id)
	return LegalHoldOut.model_validate(hold)

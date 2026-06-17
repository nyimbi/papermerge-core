# (c) Copyright Datacraft, 2026
"""Legal hold service — query and enforcement helpers."""
import logging

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db.orm import LegalHold

_log = logging.getLogger(__name__)


async def is_document_on_hold(document_id: str, session: AsyncSession) -> bool:
	"""Return True if the document has at least one active (unreleased) hold."""
	stmt = (
		select(LegalHold.id)
		.where(
			LegalHold.document_id == document_id,
			LegalHold.released_at.is_(None),
		)
		.limit(1)
	)
	result = await session.execute(stmt)
	return result.scalar_one_or_none() is not None


async def check_hold_before_delete(document_id: str, session: AsyncSession) -> None:
	"""Raise HTTP 403 if the document has any active legal hold.

	Intended to be called at the top of any delete path before making
	any destructive change.
	"""
	stmt = (
		select(LegalHold.hold_name)
		.where(
			LegalHold.document_id == document_id,
			LegalHold.released_at.is_(None),
		)
		.limit(1)
	)
	result = await session.execute(stmt)
	hold_name = result.scalar_one_or_none()
	if hold_name is not None:
		_log.warning(
			"Delete blocked by legal hold %r on document %s", hold_name, document_id
		)
		raise HTTPException(
			status_code=status.HTTP_403_FORBIDDEN,
			detail=f"Document is under legal hold: {hold_name}",
		)

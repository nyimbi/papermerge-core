# (c) Copyright Datacraft, 2026
"""Classification feedback API — captures human corrections to AI document classification."""
import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.engine import get_db
from papermerge.core.features.auth.dependencies import require_scopes
from papermerge.core.features.auth import scopes
from .db.orm import ClassificationFeedback

logger = logging.getLogger(__name__)

router = APIRouter(tags=["classification-feedback"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class FeedbackCreate(BaseModel):
	corrected_type: str
	predicted_type: str | None = None
	predicted_confidence: float | None = None


class FeedbackRecord(BaseModel):
	id: str
	document_id: str
	predicted_type: str | None
	predicted_confidence: float | None
	corrected_type: str
	feedback_by_id: str
	created_at: datetime

	model_config = {"from_attributes": True}


class CorrectionByType(BaseModel):
	predicted: str | None
	corrected: str
	count: int


class FeedbackStats(BaseModel):
	total_corrections: int
	accuracy_rate: float
	corrections_by_type: list[CorrectionByType]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/documents/{document_id}/classification-feedback", status_code=201)
async def submit_classification_feedback(
	document_id: uuid.UUID,
	body: FeedbackCreate,
	user: require_scopes(scopes.NODE_UPDATE),
	db_session: AsyncSession = Depends(get_db),
) -> FeedbackRecord:
	"""Record a human correction to the document's classification and update the document type."""

	# Save feedback record
	feedback = ClassificationFeedback(
		document_id=document_id,
		predicted_type=body.predicted_type,
		predicted_confidence=body.predicted_confidence,
		corrected_type=body.corrected_type,
		feedback_by_id=str(user.id),
		tenant_id=user.tenant_id,
	)
	db_session.add(feedback)

	# Update the document's document_type_id if a matching DocumentType exists.
	# Resolve name → UUID so the FK column stays consistent.
	try:
		from papermerge.core.features.document_types.db.orm import DocumentType
		from sqlalchemy import and_

		dt_stmt = select(DocumentType).where(
			and_(
				DocumentType.name == body.corrected_type,
				DocumentType.user_id == user.id,
			)
		)
		dt_result = await db_session.execute(dt_stmt)
		doc_type = dt_result.scalar()

		if doc_type:
			from papermerge.core.features.document.db.orm import Document
			upd = (
				update(Document)
				.where(Document.id == document_id)
				.values(document_type_id=doc_type.id)
			)
			await db_session.execute(upd)
	except Exception as exc:
		# Don't fail the whole request if document_type resolution fails;
		# the feedback record itself is the primary value here.
		logger.warning("classification_feedback: could not update document_type_id: %s", exc)

	await db_session.commit()
	await db_session.refresh(feedback)

	return FeedbackRecord(
		id=str(feedback.id),
		document_id=str(feedback.document_id),
		predicted_type=feedback.predicted_type,
		predicted_confidence=feedback.predicted_confidence,
		corrected_type=feedback.corrected_type,
		feedback_by_id=feedback.feedback_by_id,
		created_at=feedback.created_at,
	)


@router.get("/documents/{document_id}/classification-feedback")
async def get_document_feedback(
	document_id: uuid.UUID,
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
) -> list[FeedbackRecord]:
	"""Return correction history for a document, newest first."""
	stmt = (
		select(ClassificationFeedback)
		.where(
			ClassificationFeedback.document_id == document_id,
			ClassificationFeedback.tenant_id == user.tenant_id,
		)
		.order_by(ClassificationFeedback.created_at.desc())
	)
	result = await db_session.execute(stmt)
	rows = result.scalars().all()

	return [
		FeedbackRecord(
			id=str(r.id),
			document_id=str(r.document_id),
			predicted_type=r.predicted_type,
			predicted_confidence=r.predicted_confidence,
			corrected_type=r.corrected_type,
			feedback_by_id=r.feedback_by_id,
			created_at=r.created_at,
		)
		for r in rows
	]


@router.get("/classification/feedback-stats")
async def get_feedback_stats(
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
) -> FeedbackStats:
	"""Aggregate correction statistics for the tenant."""
	tenant_filter = ClassificationFeedback.tenant_id == user.tenant_id

	# Total corrections
	total_stmt = select(func.count()).select_from(ClassificationFeedback).where(tenant_filter)
	total: int = await db_session.scalar(total_stmt) or 0

	# Accuracy rate: fraction of records where predicted_type == corrected_type
	# (i.e. the model was already right and the user just confirmed)
	correct_stmt = (
		select(func.count())
		.select_from(ClassificationFeedback)
		.where(
			tenant_filter,
			ClassificationFeedback.predicted_type == ClassificationFeedback.corrected_type,
			ClassificationFeedback.predicted_type.isnot(None),
		)
	)
	correct: int = await db_session.scalar(correct_stmt) or 0
	accuracy_rate = round(correct / total, 4) if total > 0 else 0.0

	# Group corrections by (predicted_type, corrected_type)
	group_stmt = (
		select(
			ClassificationFeedback.predicted_type,
			ClassificationFeedback.corrected_type,
			func.count().label("count"),
		)
		.where(tenant_filter)
		.group_by(
			ClassificationFeedback.predicted_type,
			ClassificationFeedback.corrected_type,
		)
		.order_by(func.count().desc())
	)
	group_result = await db_session.execute(group_stmt)
	corrections_by_type = [
		CorrectionByType(predicted=row[0], corrected=row[1], count=row[2])
		for row in group_result.fetchall()
	]

	return FeedbackStats(
		total_corrections=total,
		accuracy_rate=accuracy_rate,
		corrections_by_type=corrections_by_type,
	)

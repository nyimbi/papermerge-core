import logging
import uuid
from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.engine import get_db
from papermerge.core.features.auth import scopes
from papermerge.core.features.auth.dependencies import require_scopes
from papermerge.core.features.annotations.db.orm import DocumentAnnotation

logger = logging.getLogger(__name__)

router = APIRouter(
	prefix="/documents",
	tags=["annotations"],
)


# ---------------------------------------------------------------------------
# Pydantic schemas (local — not worth a separate schema.py for 4 models)
# ---------------------------------------------------------------------------

class AnnotationOut(BaseModel):
	id: uuid.UUID
	document_id: uuid.UUID
	page_number: int
	annotation_type: str
	x: float
	y: float
	width: float
	height: float
	content: Optional[str]
	color: str
	created_by_id: str
	tenant_id: str
	created_at: datetime
	updated_at: datetime

	model_config = {"from_attributes": True}


class AnnotationCreate(BaseModel):
	page_number: int
	annotation_type: str = Field(pattern="^(highlight|note|redaction)$")
	x: float = Field(ge=0.0, le=1.0)
	y: float = Field(ge=0.0, le=1.0)
	width: float = Field(ge=0.0, le=1.0)
	height: float = Field(ge=0.0, le=1.0)
	content: Optional[str] = None
	color: str = "#FFD700"


class AnnotationUpdate(BaseModel):
	x: Optional[float] = Field(default=None, ge=0.0, le=1.0)
	y: Optional[float] = Field(default=None, ge=0.0, le=1.0)
	width: Optional[float] = Field(default=None, ge=0.0, le=1.0)
	height: Optional[float] = Field(default=None, ge=0.0, le=1.0)
	content: Optional[str] = None
	color: Optional[str] = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get(
	"/{document_id}/annotations",
	response_model=list[AnnotationOut],
	summary="List annotations for a document page",
)
async def list_annotations(
	document_id: uuid.UUID,
	user: Annotated[object, Depends(require_scopes(scopes.NODE_VIEW))],
	db_session: AsyncSession = Depends(get_db),
	page_number: Optional[int] = Query(default=None, ge=1),
) -> list[AnnotationOut]:
	stmt = select(DocumentAnnotation).where(
		DocumentAnnotation.document_id == document_id
	)
	if page_number is not None:
		stmt = stmt.where(DocumentAnnotation.page_number == page_number)
	stmt = stmt.order_by(DocumentAnnotation.created_at)

	result = await db_session.execute(stmt)
	rows = result.scalars().all()
	return [AnnotationOut.model_validate(r) for r in rows]


@router.post(
	"/{document_id}/annotations",
	response_model=AnnotationOut,
	status_code=status.HTTP_201_CREATED,
	summary="Create an annotation on a document page",
)
async def create_annotation(
	document_id: uuid.UUID,
	body: AnnotationCreate,
	user: Annotated[object, Depends(require_scopes(scopes.NODE_UPDATE))],
	db_session: AsyncSession = Depends(get_db),
) -> AnnotationOut:
	annotation = DocumentAnnotation(
		document_id=document_id,
		page_number=body.page_number,
		annotation_type=body.annotation_type,
		x=body.x,
		y=body.y,
		width=body.width,
		height=body.height,
		content=body.content,
		color=body.color,
		created_by_id=str(user.id),
		tenant_id=str(getattr(user, "tenant_id", user.id)),
	)
	db_session.add(annotation)
	try:
		await db_session.commit()
		await db_session.refresh(annotation)
	except Exception as e:
		await db_session.rollback()
		logger.error("Failed to create annotation: %s", e, exc_info=True)
		raise HTTPException(status_code=500, detail="Failed to create annotation")

	return AnnotationOut.model_validate(annotation)


@router.patch(
	"/{document_id}/annotations/{annotation_id}",
	response_model=AnnotationOut,
	summary="Update an annotation",
)
async def update_annotation(
	document_id: uuid.UUID,
	annotation_id: uuid.UUID,
	body: AnnotationUpdate,
	user: Annotated[object, Depends(require_scopes(scopes.NODE_UPDATE))],
	db_session: AsyncSession = Depends(get_db),
) -> AnnotationOut:
	result = await db_session.execute(
		select(DocumentAnnotation).where(
			DocumentAnnotation.id == annotation_id,
			DocumentAnnotation.document_id == document_id,
		)
	)
	annotation = result.scalar_one_or_none()
	if annotation is None:
		raise HTTPException(status_code=404, detail="Annotation not found")

	# Only the creator may mutate
	if annotation.created_by_id != str(user.id):
		raise HTTPException(status_code=403, detail="Not allowed to edit this annotation")

	update_data = body.model_dump(exclude_none=True)
	for field, value in update_data.items():
		setattr(annotation, field, value)

	try:
		await db_session.commit()
		await db_session.refresh(annotation)
	except Exception as e:
		await db_session.rollback()
		logger.error("Failed to update annotation %s: %s", annotation_id, e, exc_info=True)
		raise HTTPException(status_code=500, detail="Failed to update annotation")

	return AnnotationOut.model_validate(annotation)


@router.delete(
	"/{document_id}/annotations/{annotation_id}",
	status_code=status.HTTP_204_NO_CONTENT,
	summary="Delete an annotation",
)
async def delete_annotation(
	document_id: uuid.UUID,
	annotation_id: uuid.UUID,
	user: Annotated[object, Depends(require_scopes(scopes.NODE_UPDATE))],
	db_session: AsyncSession = Depends(get_db),
) -> None:
	result = await db_session.execute(
		select(DocumentAnnotation).where(
			DocumentAnnotation.id == annotation_id,
			DocumentAnnotation.document_id == document_id,
		)
	)
	annotation = result.scalar_one_or_none()
	if annotation is None:
		raise HTTPException(status_code=404, detail="Annotation not found")

	if annotation.created_by_id != str(user.id):
		raise HTTPException(status_code=403, detail="Not allowed to delete this annotation")

	await db_session.delete(annotation)
	try:
		await db_session.commit()
	except Exception as e:
		await db_session.rollback()
		logger.error("Failed to delete annotation %s: %s", annotation_id, e, exc_info=True)
		raise HTTPException(status_code=500, detail="Failed to delete annotation")

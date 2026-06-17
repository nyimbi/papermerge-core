import logging
import uuid
from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.engine import get_db
from papermerge.core.features.auth import scopes
from papermerge.core.features.auth.dependencies import require_scopes
from papermerge.core.features.comments.orm import DocumentComment

logger = logging.getLogger(__name__)

router = APIRouter(
	prefix="/documents",
	tags=["comments"],
)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class CommentOut(BaseModel):
	id: str
	document_id: str
	page_number: Optional[int]
	author_id: str
	author_name: str
	content: str
	is_resolved: bool
	parent_id: Optional[str]
	created_at: datetime
	updated_at: datetime

	model_config = {"from_attributes": True}


class CreateCommentIn(BaseModel):
	content: str
	page_number: Optional[int] = None
	parent_id: Optional[str] = None


class UpdateCommentIn(BaseModel):
	content: Optional[str] = None
	is_resolved: Optional[bool] = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get(
	"/{document_id}/comments",
	response_model=list[CommentOut],
	summary="List comments for a document",
)
async def list_comments(
	document_id: str,
	user: Annotated[object, Depends(require_scopes(scopes.NODE_VIEW))],
	db_session: AsyncSession = Depends(get_db),
	page_number: Optional[int] = Query(default=None, ge=1),
) -> list[CommentOut]:
	stmt = select(DocumentComment).where(
		DocumentComment.document_id == document_id
	)
	if page_number is not None:
		stmt = stmt.where(DocumentComment.page_number == page_number)
	stmt = stmt.order_by(DocumentComment.created_at)

	result = await db_session.execute(stmt)
	rows = result.scalars().all()
	return [CommentOut.model_validate(r) for r in rows]


@router.post(
	"/{document_id}/comments",
	response_model=CommentOut,
	status_code=status.HTTP_201_CREATED,
	summary="Add a comment to a document",
)
async def create_comment(
	document_id: str,
	body: CreateCommentIn,
	user: Annotated[object, Depends(require_scopes(scopes.NODE_VIEW))],
	db_session: AsyncSession = Depends(get_db),
) -> CommentOut:
	comment = DocumentComment(
		id=str(uuid.uuid4()),
		document_id=document_id,
		page_number=body.page_number,
		author_id=str(user.id),
		author_name=getattr(user, "username", str(user.id)),
		content=body.content,
		is_resolved=False,
		parent_id=body.parent_id,
	)
	db_session.add(comment)
	try:
		await db_session.commit()
		await db_session.refresh(comment)
	except Exception as e:
		await db_session.rollback()
		logger.error("Failed to create comment: %s", e, exc_info=True)
		raise HTTPException(status_code=500, detail="Failed to create comment")

	return CommentOut.model_validate(comment)


@router.patch(
	"/{document_id}/comments/{comment_id}",
	response_model=CommentOut,
	summary="Update a comment",
)
async def update_comment(
	document_id: str,
	comment_id: str,
	body: UpdateCommentIn,
	user: Annotated[object, Depends(require_scopes(scopes.NODE_VIEW))],
	db_session: AsyncSession = Depends(get_db),
) -> CommentOut:
	result = await db_session.execute(
		select(DocumentComment).where(
			DocumentComment.id == comment_id,
			DocumentComment.document_id == document_id,
		)
	)
	comment = result.scalar_one_or_none()
	if comment is None:
		raise HTTPException(status_code=404, detail="Comment not found")

	update_data = body.model_dump(exclude_none=True)
	for field, value in update_data.items():
		setattr(comment, field, value)

	try:
		await db_session.commit()
		await db_session.refresh(comment)
	except Exception as e:
		await db_session.rollback()
		logger.error("Failed to update comment %s: %s", comment_id, e, exc_info=True)
		raise HTTPException(status_code=500, detail="Failed to update comment")

	return CommentOut.model_validate(comment)


@router.delete(
	"/{document_id}/comments/{comment_id}",
	status_code=status.HTTP_204_NO_CONTENT,
	summary="Delete a comment",
)
async def delete_comment(
	document_id: str,
	comment_id: str,
	user: Annotated[object, Depends(require_scopes(scopes.NODE_VIEW))],
	db_session: AsyncSession = Depends(get_db),
) -> None:
	result = await db_session.execute(
		select(DocumentComment).where(
			DocumentComment.id == comment_id,
			DocumentComment.document_id == document_id,
		)
	)
	comment = result.scalar_one_or_none()
	if comment is None:
		raise HTTPException(status_code=404, detail="Comment not found")

	await db_session.delete(comment)
	try:
		await db_session.commit()
	except Exception as e:
		await db_session.rollback()
		logger.error("Failed to delete comment %s: %s", comment_id, e, exc_info=True)
		raise HTTPException(status_code=500, detail="Failed to delete comment")

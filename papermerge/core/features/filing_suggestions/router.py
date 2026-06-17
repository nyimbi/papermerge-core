"""Filing suggestions router — auto-discovered by router_loader.py."""
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.engine import get_db
from papermerge.core.db import common as dbapi_common
from papermerge.core import exceptions as exc
from papermerge.core.features.auth.dependencies import require_scopes
from papermerge.core.features.auth import scopes
from papermerge.core.features.audit.db.audit_context import AsyncAuditContext

from .service import get_filing_suggestions

logger = logging.getLogger(__name__)

router = APIRouter(
	prefix="/documents",
	tags=["filing-suggestions"],
)


# ---------------------------------------------------------------------------
# Response / request models
# ---------------------------------------------------------------------------

class SuggestedFolder(BaseModel):
	folder_id: str
	folder_path: str
	confidence: float
	document_count: int


class SuggestedTag(BaseModel):
	tag_id: str
	tag_name: str
	tag_color: str
	confidence: float
	document_count: int


class FilingSuggestionsResponse(BaseModel):
	suggested_folders: list[SuggestedFolder]
	suggested_tags: list[SuggestedTag]
	suggested_document_type: str | None
	based_on_type: str | None
	peer_count: int


class ApplyFilingSuggestionRequest(BaseModel):
	folder_id: str | None = None
	tag_ids: list[str] = []


class ApplyFilingSuggestionResponse(BaseModel):
	moved: bool
	tags_added: int
	folder_id: str | None
	tag_ids: list[str]


# ---------------------------------------------------------------------------
# GET /documents/{document_id}/filing-suggestions
# ---------------------------------------------------------------------------

@router.get(
	"/{document_id}/filing-suggestions",
	response_model=FilingSuggestionsResponse,
	responses={
		status.HTTP_403_FORBIDDEN: {"description": "Insufficient permissions"},
		status.HTTP_404_NOT_FOUND: {"description": "Document not found"},
	},
)
async def get_document_filing_suggestions(
	document_id: uuid.UUID,
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
) -> FilingSuggestionsResponse:
	"""
	Return smart folder and tag suggestions for a document.

	Suggestions are derived from peer documents that share the same
	document_type and are owned by the same user.  Confidence is the
	fraction of peers that ended up in the suggested folder / had the
	suggested tag applied.

	Returns an empty suggestion list (not 404) when the document has no
	document_type assigned yet.
	"""
	if not await dbapi_common.has_node_perm(
		db_session,
		node_id=document_id,
		codename=scopes.NODE_VIEW,
		user_id=user.id,
	):
		raise exc.HTTP403Forbidden()

	result = await get_filing_suggestions(
		document_id=document_id,
		user_id=user.id,
		session=db_session,
	)
	return FilingSuggestionsResponse(**result)


# ---------------------------------------------------------------------------
# POST /documents/{document_id}/apply-filing-suggestion
# ---------------------------------------------------------------------------

@router.post(
	"/{document_id}/apply-filing-suggestion",
	response_model=ApplyFilingSuggestionResponse,
	responses={
		status.HTTP_403_FORBIDDEN: {"description": "Insufficient permissions"},
		status.HTTP_404_NOT_FOUND: {"description": "Document not found"},
		status.HTTP_400_BAD_REQUEST: {"description": "Invalid folder_id or tag_ids"},
	},
)
async def apply_filing_suggestion(
	document_id: uuid.UUID,
	body: ApplyFilingSuggestionRequest,
	user: require_scopes(scopes.NODE_UPDATE),
	db_session: AsyncSession = Depends(get_db),
) -> ApplyFilingSuggestionResponse:
	"""
	Apply a filing suggestion: move document to folder and/or add tags.

	Both operations are optional — supply only the ones you want applied.
	Tag application is additive (existing tags are preserved).
	"""
	from sqlalchemy import select, update
	from papermerge.core import orm as _orm

	if not await dbapi_common.has_node_perm(
		db_session,
		node_id=document_id,
		codename=scopes.NODE_UPDATE,
		user_id=user.id,
	):
		raise exc.HTTP403Forbidden()

	moved = False
	tags_added = 0

	async with AsyncAuditContext(db_session, user_id=user.id, username=user.username):
		# ----------------------------------------------------------------
		# Move to folder
		# ----------------------------------------------------------------
		if body.folder_id:
			try:
				folder_uuid = uuid.UUID(body.folder_id)
			except ValueError:
				raise HTTPException(
					status_code=status.HTTP_400_BAD_REQUEST,
					detail=f"Invalid folder_id: {body.folder_id!r}",
				)

			if not await dbapi_common.has_node_perm(
				db_session,
				node_id=folder_uuid,
				codename=scopes.NODE_VIEW,
				user_id=user.id,
			):
				raise HTTPException(
					status_code=status.HTTP_403_FORBIDDEN,
					detail="No permission on target folder",
				)

			result = await db_session.execute(
				update(_orm.Node)
				.where(_orm.Node.id == document_id)
				.values(parent_id=folder_uuid)
			)
			moved = result.rowcount > 0

		# ----------------------------------------------------------------
		# Add tags
		# ----------------------------------------------------------------
		if body.tag_ids:
			tag_uuids: list[uuid.UUID] = []
			for raw in body.tag_ids:
				try:
					tag_uuids.append(uuid.UUID(raw))
				except ValueError:
					raise HTTPException(
						status_code=status.HTTP_400_BAD_REQUEST,
						detail=f"Invalid tag_id: {raw!r}",
					)

			tag_stmt = select(_orm.Tag).where(_orm.Tag.id.in_(tag_uuids))
			tags = list((await db_session.scalars(tag_stmt)).all())

			node_stmt = select(_orm.Node).where(_orm.Node.id == document_id)
			node = (await db_session.scalars(node_stmt)).one_or_none()
			if node is None:
				raise exc.HTTP404NotFound()

			await db_session.refresh(node, ["tags"])
			existing_ids = {t.id for t in node.tags}
			new_tags = [t for t in tags if t.id not in existing_ids]
			node.tags = list(node.tags) + new_tags
			await db_session.flush()
			tags_added = len(new_tags)

	await db_session.commit()

	return ApplyFilingSuggestionResponse(
		moved=moved,
		tags_added=tags_added,
		folder_id=body.folder_id,
		tag_ids=body.tag_ids,
	)

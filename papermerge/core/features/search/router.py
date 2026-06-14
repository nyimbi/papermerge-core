import logging
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status
from typing import Annotated

from papermerge.core import scopes, db
from papermerge.core.features.auth import get_current_user
from papermerge.core.db.engine import get_db
from papermerge.core import schema as core_schema
from .schema import SearchQueryParams, SearchDocumentsResponse
from .db.orm import SavedSearch, DocumentSearchIndex

router = APIRouter(
    prefix="/search",
    tags=["search"]
)


logger = logging.getLogger(__name__)



@router.post(
    "/",
    response_model=SearchDocumentsResponse,
    responses={
        400: {
            "description": "Invalid search parameters (e.g., invalid date range, non-existent document type)"
        },
        403: {
            "description": "Insufficient permissions - missing required scope: node:view"
        },
        500: {
            "description": "Internal server error - search operation failed"
        }
    }
)
async def documents_search(
    user: scopes.ViewNode,
    params: SearchQueryParams,
    db_session: AsyncSession = Depends(db.get_db)
):
    """
    Advanced document search and filtering.

    **Search capabilities:**
    - Full-text search across document titles and content
    - Filter by document type (category), tags, or custom metadata
    - Filter by custom field values (works with any custom field)
    - Sort by relevance, date, title, or custom field values
    - Paginated results

    **Custom Fields in Response:**
    The response includes custom field metadata and values based on:
    1. Document types specified in category filters → all their custom fields
    2. Custom fields referenced in custom_field filters → those specific fields

    The custom_fields in response is the union of all relevant fields (deduplicated).

    **Parameters:**
    - `filters.fts`: Full-text search terms
    - `filters.categories`: Filter by category/document type
    - `filters.tags`: Filter by tags
    - `filters.custom_fields`: Filter by custom field values
    - `page_number`: Page number for pagination (default: 1)
    - `page_size`: Results per page (default: 20, max: 100)
    - `sort_by`: Field to sort by (can be custom field name)
    - `sort_direction`: asc or desc (default: desc)

    **Response:**
    - `items`: List of documents with their custom field values
    - `custom_fields`: Metadata about custom fields included in response
    - `document_type_id`: Set when filtering by exactly one document type
    """
    try:
        logger.info(
            f"User {user.id} searching documents",
            extra={
                "filters": params.filters.model_dump() if params.filters else None,
                "page": params.page_number
            }
        )
        # Use unified search function
        result = await db.search_documents(
            db_session=db_session,
            user_id=user.id,
            params=params
        )

        logger.debug(f"Search returned {len(result.items)} results for user {user.id}")
        return result

    except ValueError as e:
        logger.warning(f"Invalid search parameters for user {user.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except PermissionError as e:
        logger.warning(f"Permission denied for user {user.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access these documents"
        )
    except Exception as e:
        logger.error(
            f"Search failed for user {user.id}: {e}",
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Search operation failed. Please try again later."
        )


@router.get("/suggestions")
async def get_search_suggestions(
	user: Annotated[core_schema.User, Depends(get_current_user)],
	q: str = Query(default="", min_length=0),
	limit: int = Query(default=10, ge=1, le=50),
	db_session: AsyncSession = Depends(get_db),
) -> list[dict]:
	"""Return document title suggestions matching the query prefix."""
	if not q:
		return []
	stmt = (
		select(DocumentSearchIndex.title, DocumentSearchIndex.document_id)
		.where(
			DocumentSearchIndex.owner_id == user.id,
			DocumentSearchIndex.title.ilike(f"%{q}%"),
		)
		.order_by(DocumentSearchIndex.last_updated.desc())
		.limit(limit)
	)
	rows = (await db_session.execute(stmt)).all()
	return [{"text": r.title, "documentId": str(r.document_id)} for r in rows if r.title]


@router.get("/saved")
async def list_saved_searches(
	user: Annotated[core_schema.User, Depends(get_current_user)],
	db_session: AsyncSession = Depends(get_db),
) -> list[dict]:
	"""List saved searches for the current user."""
	rows = (await db_session.execute(
		select(SavedSearch)
		.where(SavedSearch.user_id == user.id)
		.order_by(SavedSearch.created_at.desc())
	)).scalars().all()
	return [{"id": str(s.id), "name": s.name, "query": s.query, "createdAt": s.created_at.isoformat()} for s in rows]


@router.post("/saved", status_code=201)
async def create_saved_search(
	body: dict,
	user: Annotated[core_schema.User, Depends(get_current_user)],
	db_session: AsyncSession = Depends(get_db),
) -> dict:
	"""Save a search query."""
	from datetime import datetime
	name = (body.get("name") or "").strip()
	query = (body.get("query") or "").strip()
	if not name or not query:
		raise HTTPException(status_code=422, detail="name and query are required.")
	saved = SavedSearch(
		id=uuid.uuid4(),
		user_id=user.id,
		name=name,
		query=query,
		created_at=datetime.utcnow(),
	)
	db_session.add(saved)
	await db_session.commit()
	return {"id": str(saved.id), "name": saved.name, "query": saved.query, "createdAt": saved.created_at.isoformat()}


@router.delete("/saved/{search_id}", status_code=204)
async def delete_saved_search(
	search_id: uuid.UUID,
	user: Annotated[core_schema.User, Depends(get_current_user)],
	db_session: AsyncSession = Depends(get_db),
) -> None:
	"""Delete a saved search."""
	result = await db_session.execute(
		sa_delete(SavedSearch).where(
			SavedSearch.id == search_id,
			SavedSearch.user_id == user.id,
		).returning(SavedSearch.id)
	)
	await db_session.commit()
	if not result.fetchall():
		raise HTTPException(status_code=404, detail="Saved search not found.")


@router.get("/semantic")
async def semantic_search(
	user: Annotated[core_schema.User, Depends(get_current_user)],
	q: str = Query(min_length=1, description="Natural-language query"),
	limit: int = Query(default=20, ge=1, le=100),
	threshold: float = Query(default=0.5, ge=0.0, le=1.0),
) -> dict:
	"""
	Semantic (vector) search using document embeddings.

	Returns documents ranked by cosine similarity to the query.
	Requires semantic_search_enabled=true in settings.
	"""
	from papermerge.core.config import get_settings
	from papermerge.core.db.engine import get_async_session_maker
	from papermerge.core.search.semantic import SemanticSearch
	from papermerge.core.search.embeddings.ollama import OllamaEmbeddings

	cfg = get_settings()
	if not cfg.semantic_search_enabled:
		raise HTTPException(
			status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
			detail="Semantic search is not enabled. Set SEMANTIC_SEARCH_ENABLED=true.",
		)

	base_url = getattr(cfg, "embedding_base_url", "http://localhost:11434")
	model = getattr(cfg, "embedding_model", "nomic-embed-text")
	embedding_svc = OllamaEmbeddings(base_url=base_url, model=model)
	searcher = SemanticSearch(
		embedding_service=embedding_svc,
		session_factory=get_async_session_maker(),
	)

	result = await searcher.search(
		query=q,
		user_id=user.id,
		limit=limit,
		threshold=threshold,
	)
	return {
		"hits": [
			{
				"documentId": str(h.document_id),
				"title": h.title,
				"score": h.score,
				"snippet": h.snippet,
			}
			for h in result.hits
		],
		"total": result.total,
		"timings": {
			"embedMs": round(result.query_embedding_time_ms, 1),
			"searchMs": round(result.search_time_ms, 1),
			"totalMs": round(result.total_time_ms, 1),
		},
	}

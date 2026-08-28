import logging
import time
import uuid
from enum import Enum

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status
from typing import Annotated

from papermerge.core import scopes, db
from papermerge.core.features.auth import get_current_user
from papermerge.core.db.engine import get_db
from papermerge.core import schema as core_schema
from .schema import SearchQueryParams, SearchDocumentsResponse, SearchFacetsResponse
from .db.orm import SavedSearch, DocumentSearchIndex
from .db.api import get_search_facets, semantic_search_db, hybrid_search_db, get_similar_documents_db


EMBEDDING_MODEL = "text-embedding-3-small"


class SearchMode(str, Enum):
    keyword = "keyword"
    semantic = "semantic"
    hybrid = "hybrid"


def _embed_query(query_text: str) -> list[float]:
    """Synchronous call to LiteLLM embedding endpoint. Called in a thread pool."""
    from openai import OpenAI
    from papermerge.core.config import get_settings
    cfg = get_settings()
    client = OpenAI(base_url=cfg.litellm_base_url, api_key=cfg.litellm_api_key)
    resp = client.embeddings.create(model=EMBEDDING_MODEL, input=query_text)
    return resp.data[0].embedding


async def _get_query_vector(query_text: str) -> list[float]:
    """Async wrapper — runs the blocking OpenAI SDK call in threadpool."""
    import asyncio
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _embed_query, query_text)

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
    mode: SearchMode = Query(default=SearchMode.keyword, description="Search mode: keyword | semantic | hybrid"),
    db_session: AsyncSession = Depends(db.get_db)
):
    """
    Advanced document search and filtering.

    **Search modes** (query param `mode`):
    - `keyword` (default) — BM25 full-text search via tsvector @@
    - `semantic` — vector cosine similarity via pgvector
    - `hybrid` — reciprocal rank fusion of BM25 + cosine ranks

    **Search capabilities:**
    - Full-text search across document titles and content
    - Filter by document type (category), tags, or custom metadata
    - Filter by custom field values (works with any custom field)
    - Sort by relevance, date, title, or custom field values
    - Paginated results

    **Parameters:**
    - `filters.fts`: Full-text search terms (also used as semantic query text)
    - `mode`: keyword | semantic | hybrid (default: keyword)
    - `filters.categories`: Filter by category/document type
    - `filters.tags`: Filter by tags
    - `filters.custom_fields`: Filter by custom field values
    - `page_number`: Page number for pagination (default: 1)
    - `page_size`: Results per page (default: 20, max: 100)
    - `sort_by`: Field to sort by (can be custom field name)
    - `sort_direction`: asc or desc (default: desc)
    """
    try:
        logger.info(
            f"User {user.id} searching documents mode={mode}",
            extra={
                "filters": params.filters.model_dump() if params.filters else None,
                "page": params.page_number,
                "mode": mode,
            }
        )

        # ------------------------------------------------------------------
        # Semantic / hybrid: extract query text, embed, then search
        # ------------------------------------------------------------------
        if mode in (SearchMode.semantic, SearchMode.hybrid):
            query_text = ""
            if params.filters and params.filters.fts and params.filters.fts.terms:
                query_text = " ".join(params.filters.fts.terms)

            if not query_text:
                raise ValueError("semantic/hybrid search requires filters.fts.terms")

            t0 = time.monotonic()
            query_vector = await _get_query_vector(query_text)
            embed_ms = (time.monotonic() - t0) * 1000

            t1 = time.monotonic()
            if mode == SearchMode.semantic:
                hits = await semantic_search_db(
                    db_session,
                    user_id=user.id,
                    query_vector=query_vector,
                    limit=params.page_size,
                    threshold=0.0,
                )
            else:
                hits = await hybrid_search_db(
                    db_session,
                    user_id=user.id,
                    query_text=query_text,
                    query_vector=query_vector,
                    limit=params.page_size,
                    lang=params.lang or "eng",
                )
            search_ms = (time.monotonic() - t1) * 1000

            logger.info(
                f"Vector search returned {len(hits)} hits "
                f"(embed={embed_ms:.1f}ms search={search_ms:.1f}ms)"
            )

            # Wrap into SearchDocumentsResponse format so the frontend stays uniform
            from .schema import DocumentCFV, SearchDocumentsResponse, Category
            from papermerge.core.schemas.common import OwnedBy
            import math

            items = []
            for h in hits:
                items.append(
                    DocumentCFV(
                        id=uuid.UUID(h["document_id"]),
                        title=h["title"] or "(untitled)",
                        category=None,
                        tags=[],
                        custom_fields=[],
                        lang="eng",
                        owned_by=OwnedBy(id=user.id, name="", type="user"),
                        created_at=__import__("datetime").datetime.utcnow(),
                        updated_at=__import__("datetime").datetime.utcnow(),
                        created_by=None,
                        updated_by=None,
                    )
                )

            return SearchDocumentsResponse(
                items=items,
                page_number=params.page_number,
                page_size=params.page_size,
                num_pages=1,
                total_items=len(hits),
                custom_fields=[],
                document_type_id=None,
            )

        # ------------------------------------------------------------------
        # Keyword (default) — existing path
        # ------------------------------------------------------------------
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


@router.get(
    "/facets",
    response_model=SearchFacetsResponse,
    responses={
        403: {"description": "Insufficient permissions"},
        500: {"description": "Facet computation failed"},
    },
)
async def search_facets(
    user: scopes.ViewNode,
    q: str = Query(default="", description="Optional search query to scope facets"),
    db_session: AsyncSession = Depends(db.get_db),
) -> SearchFacetsResponse:
    """
    Return facet counts for the advanced search sidebar.

    Facets are scoped to documents the current user can access.
    Optionally pass `q` to narrow facets to a full-text search query.
    """
    try:
        return await get_search_facets(
            db_session=db_session,
            user_id=user.id,
            q=q or None,
        )
    except Exception as e:
        logger.error(f"Facet computation failed for user {user.id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Facet computation failed.",
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


# ---------------------------------------------------------------------------
# GET /documents/{document_id}/similar
# Mounted under a separate prefix so the path becomes /documents/{id}/similar.
# We attach it to `router` via include_router at module load time below.
# ---------------------------------------------------------------------------

similar_router = APIRouter(
    prefix="/documents",
    tags=["search"],
)


@similar_router.get(
    "/{document_id}/similar",
    responses={
        404: {"description": "Document has no embeddings yet"},
        403: {"description": "Insufficient permissions"},
    },
)
async def get_similar_documents(
    document_id: uuid.UUID,
    user: Annotated[core_schema.User, Depends(get_current_user)],
    limit: int = Query(default=5, ge=1, le=20),
    db_session: AsyncSession = Depends(get_db),
) -> dict:
    """
    Return up to `limit` documents most similar to `document_id` by cosine
    distance, computed across the document's stored embedding chunks.

    Requires the document to have been embedded (document_embeddings table).
    Returns similarity scores as 0–100 percentages.
    """
    try:
        hits = await get_similar_documents_db(
            db_session,
            document_id=document_id,
            user_id=user.id,
            limit=limit,
        )
    except Exception as e:
        logger.error(f"Similar-documents query failed for {document_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Similar documents query failed.",
        )

    if not hits:
        return {"similar": []}

    return {
        "similar": [
            {
                "document_id": h["document_id"],
                "title": h["title"],
                "score": round(h["score"] * 100, 1),   # 0-100 %
                "snippet": h["snippet"],
            }
            for h in hits
        ]
    }


# Register similar_router into the main search router so it is auto-discovered
# by discover_routers() which looks for module.router.
router.include_router(similar_router)

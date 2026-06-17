import logging
import uuid
from collections import defaultdict
from datetime import datetime
from itertools import combinations
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.engine import get_db
from papermerge.core.features.auth import scopes
from papermerge.core.features.auth.dependencies import require_scopes

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/entities", tags=["entity-graph"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class EntityNodeOut(BaseModel):
    id: str
    label: str
    type: str
    document_count: int


class EntityEdgeOut(BaseModel):
    source: str
    target: str
    weight: float
    co_document_count: int


class EntityGraphOut(BaseModel):
    nodes: list[EntityNodeOut]
    edges: list[EntityEdgeOut]


class DocumentBriefOut(BaseModel):
    id: str
    title: str
    created_at: str


class EntityDocumentsOut(BaseModel):
    documents: list[DocumentBriefOut]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _entity_node_id(entity_type: str, value: str) -> str:
    """Stable synthetic id for an entity (type:value)."""
    return str(uuid.uuid5(uuid.NAMESPACE_OID, f"{entity_type}:{value.lower().strip()}"))


# ---------------------------------------------------------------------------
# GET /entities/graph
# ---------------------------------------------------------------------------

@router.get("/graph", response_model=EntityGraphOut, summary="Entity co-occurrence graph")
async def get_entity_graph(
    user: Annotated[object, Depends(require_scopes(scopes.NODE_VIEW))],
    db_session: AsyncSession = Depends(get_db),
    entity_type: Optional[str] = Query(default=None, description="Filter by entity type"),
) -> EntityGraphOut:
    """
    Aggregate entity annotations across documents and return a co-occurrence graph.

    Nodes = unique entities (id, label, type, document_count).
    Edges = entity pairs that appear in the same document, weight = co-occurrence count.

    Falls back to an empty graph if the document_annotations table doesn't exist yet.
    """
    try:
        # Pull entity-type annotations.
        # DocumentAnnotation stores entity extractions as annotation_type='entity'
        # with the entity value in `content` and entity sub-type encoded as color
        # field convention: color="#entity_type" — or we parse content as "type:value".
        # We support both: if content contains ":" treat first segment as sub-type,
        # otherwise fall back to the annotation color field as a tag.

        stmt = (
            select(
                # columns we need
                text("document_annotations.id"),
                text("document_annotations.document_id"),
                text("document_annotations.content"),
                text("document_annotations.color"),
                text("document_annotations.created_at"),
            )
            .where(text("document_annotations.annotation_type = 'entity'"))
        )

        if entity_type:
            # We'll filter in Python after parsing content since type is embedded
            pass

        result = await db_session.execute(stmt)
        rows = result.fetchall()

    except Exception as exc:
        # Table might not exist yet — return empty graph gracefully
        logger.warning("entity_graph: could not query document_annotations: %s", exc)
        return EntityGraphOut(nodes=[], edges=[])

    # Parse rows: derive entity type + value from content
    # Convention: content = "<entity_type>:<value>"  e.g. "person:John Doe"
    # Fallback: content = raw value, entity sub-type = color stripped of "#"

    # Map: entity_id -> {label, type, doc_ids: set}
    entity_info: dict[str, dict] = {}
    # Map: document_id -> list[entity_id]
    doc_to_entities: dict[str, list[str]] = defaultdict(list)

    for row in rows:
        content: str = row.content or ""
        raw_color: str = row.color or ""
        doc_id = str(row.document_id)

        if ":" in content:
            parts = content.split(":", 1)
            etype = parts[0].strip().lower()
            evalue = parts[1].strip()
        else:
            # Treat color field as entity type tag (strip "#" prefix convention)
            etype = raw_color.lstrip("#").lower() if raw_color.startswith("#") else "other"
            evalue = content.strip()

        if not evalue:
            continue

        # Normalise type to known set
        known_types = {"person", "organization", "location", "date", "money"}
        if etype not in known_types:
            etype = "other"

        # Apply entity_type filter
        if entity_type and etype != entity_type.lower():
            continue

        eid = _entity_node_id(etype, evalue)

        if eid not in entity_info:
            entity_info[eid] = {"label": evalue, "type": etype, "doc_ids": set()}
        entity_info[eid]["doc_ids"].add(doc_id)
        doc_to_entities[doc_id].append(eid)

    # Build nodes
    nodes = [
        EntityNodeOut(
            id=eid,
            label=info["label"],
            type=info["type"],
            document_count=len(info["doc_ids"]),
        )
        for eid, info in entity_info.items()
    ]

    # Build edges: co-occurrence within the same document
    co_counts: dict[tuple[str, str], int] = defaultdict(int)
    for entity_ids in doc_to_entities.values():
        unique_ids = list(set(entity_ids))
        for a, b in combinations(sorted(unique_ids), 2):
            co_counts[(a, b)] += 1

    max_co = max(co_counts.values(), default=1)
    edges = [
        EntityEdgeOut(
            source=pair[0],
            target=pair[1],
            weight=count / max_co,
            co_document_count=count,
        )
        for pair, count in co_counts.items()
    ]

    return EntityGraphOut(nodes=nodes, edges=edges)


# ---------------------------------------------------------------------------
# GET /entities/{entity_id}/documents
# ---------------------------------------------------------------------------

@router.get(
    "/{entity_id}/documents",
    response_model=EntityDocumentsOut,
    summary="Documents that mention a given entity",
)
async def get_entity_documents(
    entity_id: str,
    user: Annotated[object, Depends(require_scopes(scopes.NODE_VIEW))],
    db_session: AsyncSession = Depends(get_db),
) -> EntityDocumentsOut:
    """
    Return the list of documents that contain an annotation matching the given entity id.

    entity_id is a UUID5 derived from type:value (see _entity_node_id).
    We reconstruct the match by re-scanning annotations and collecting documents
    whose annotations hash to the requested entity_id.
    """
    try:
        stmt = select(
            text("document_annotations.document_id"),
            text("document_annotations.content"),
            text("document_annotations.color"),
            text("document_annotations.created_at"),
        ).where(text("document_annotations.annotation_type = 'entity'"))

        result = await db_session.execute(stmt)
        rows = result.fetchall()
    except Exception as exc:
        logger.warning("entity_graph: could not query annotations for entity %s: %s", entity_id, exc)
        return EntityDocumentsOut(documents=[])

    matched_docs: dict[str, datetime] = {}

    for row in rows:
        content: str = row.content or ""
        raw_color: str = row.color or ""

        if ":" in content:
            parts = content.split(":", 1)
            etype = parts[0].strip().lower()
            evalue = parts[1].strip()
        else:
            etype = raw_color.lstrip("#").lower() if raw_color.startswith("#") else "other"
            evalue = content.strip()

        if not evalue:
            continue

        known_types = {"person", "organization", "location", "date", "money"}
        if etype not in known_types:
            etype = "other"

        eid = _entity_node_id(etype, evalue)
        if eid == entity_id:
            doc_id = str(row.document_id)
            matched_docs[doc_id] = row.created_at

    # Fetch document titles from nodes table (documents are nodes)
    documents: list[DocumentBriefOut] = []
    if matched_docs:
        try:
            doc_ids = list(matched_docs.keys())
            id_list = ", ".join(f"'{d}'" for d in doc_ids)
            title_result = await db_session.execute(
                text(f"SELECT id, title, created_at FROM nodes WHERE id IN ({id_list}) AND ctype = 'document'")
            )
            title_rows = title_result.fetchall()
            title_map = {str(r.id): (r.title, r.created_at) for r in title_rows}

            for doc_id, created_at in matched_docs.items():
                title, node_created_at = title_map.get(doc_id, (doc_id, created_at))
                documents.append(DocumentBriefOut(
                    id=doc_id,
                    title=title or doc_id,
                    created_at=node_created_at.isoformat() if hasattr(node_created_at, 'isoformat') else str(node_created_at),
                ))
        except Exception as exc:
            logger.warning("entity_graph: could not fetch document titles: %s", exc)
            # Fallback: return doc ids without titles
            for doc_id, created_at in matched_docs.items():
                documents.append(DocumentBriefOut(
                    id=doc_id,
                    title=doc_id,
                    created_at=created_at.isoformat() if hasattr(created_at, 'isoformat') else str(created_at),
                ))

    return EntityDocumentsOut(documents=documents)

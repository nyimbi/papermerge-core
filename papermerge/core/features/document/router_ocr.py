"""OCR quality and re-OCR management router.

Auto-discovered by router_loader as router_ocr.py → registered under /documents prefix.

Endpoints:
  GET  /documents/{document_id}/ocr-quality
  POST /documents/{document_id}/re-ocr
  GET  /ocr/quality-report
"""
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select as sa_select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core import exceptions as exc
from papermerge.core.features.auth.dependencies import require_scopes
from papermerge.core.features.auth import scopes
from papermerge.core.db import common as dbapi_common
from papermerge.core.db.engine import get_db
from papermerge.core.routers.common import OPEN_API_GENERIC_JSON_DETAIL
from papermerge.core.tasks import send_task
from papermerge.core.pathlib import abs_page_hocr_path

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/documents",
    tags=["ocr"],
)

# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class PageQualityScore(BaseModel):
    page_number: int
    word_count: int
    estimated_confidence: float  # 0.0–1.0


class OcrQualityResponse(BaseModel):
    document_id: uuid.UUID
    ocr_status: str
    overall_confidence: float
    page_count: int
    pages_with_text: int
    page_scores: list[PageQualityScore]
    low_confidence_pages: list[int]


class ReOcrResponse(BaseModel):
    task_id: str
    status: str  # "queued"


class QualityReportItem(BaseModel):
    document_id: uuid.UUID
    title: str
    estimated_quality: float
    page_count: int
    low_confidence_pages: list[int]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _confidence_from_hocr(hocr_path) -> tuple[float, int]:
    """Return (mean_confidence, word_count) from an hOCR file.

    Uses real Tesseract x_wconf values when available.
    Falls back to text-length proxy if hOCR cannot be parsed.
    """
    try:
        from papermerge.core.lib import extract_words_from
        words = extract_words_from(hocr_path)
        if not words:
            return 0.0, 0
        wconfs = [w["wconf"] for w in words if isinstance(w.get("wconf"), (int, float))]
        if not wconfs:
            return 0.5, len(words)
        mean_conf = sum(wconfs) / len(wconfs) / 100.0
        return round(min(1.0, max(0.0, mean_conf)), 4), len(words)
    except Exception:
        return 0.0, 0


def _confidence_from_text(text: str | None) -> tuple[float, int]:
    """Proxy confidence when no hOCR file exists.

    Formula: min(1.0, len(text)/500) * 0.8 + 0.2
    Returns (confidence, word_count).
    """
    if not text:
        return 0.0, 0
    words = text.split()
    word_count = len(words)
    conf = min(1.0, word_count / 500) * 0.8 + 0.2
    return round(conf, 4), word_count


def _page_quality(page_orm) -> PageQualityScore:
    """Compute quality score for a single Page ORM object."""
    hocr_path = abs_page_hocr_path(page_orm.id)
    if hocr_path.exists():
        confidence, word_count = _confidence_from_hocr(hocr_path)
    else:
        confidence, word_count = _confidence_from_text(page_orm.text)
    return PageQualityScore(
        page_number=page_orm.number,
        word_count=word_count,
        estimated_confidence=confidence,
    )


# ---------------------------------------------------------------------------
# GET /documents/{document_id}/ocr-quality
# ---------------------------------------------------------------------------

@router.get(
    "/{document_id}/ocr-quality",
    response_model=OcrQualityResponse,
    responses={
        status.HTTP_403_FORBIDDEN: {
            "description": f"No `{scopes.NODE_VIEW}` permission on the node",
            "content": OPEN_API_GENERIC_JSON_DETAIL,
        },
        status.HTTP_404_NOT_FOUND: {
            "description": "Document not found",
            "content": OPEN_API_GENERIC_JSON_DETAIL,
        },
    },
)
async def get_ocr_quality(
    document_id: uuid.UUID,
    user: require_scopes(scopes.NODE_VIEW),
    db_session: AsyncSession = Depends(get_db),
) -> OcrQualityResponse:
    """Return per-page OCR quality scores for a document.

    Uses real Tesseract x_wconf values from hOCR files when available;
    falls back to a word-count proxy for text-only imports.
    """
    from papermerge.core import orm as core_orm

    if not await dbapi_common.has_node_perm(
        db_session,
        node_id=document_id,
        codename=scopes.NODE_VIEW,
        user_id=user.id,
    ):
        raise exc.HTTP403Forbidden()

    # Load document with latest version + pages
    stmt = (
        sa_select(core_orm.Document)
        .options(
            selectinload(core_orm.Document.versions).selectinload(
                core_orm.DocumentVersion.pages
            )
        )
        .where(core_orm.Document.id == document_id)
    )
    result = await db_session.execute(stmt)
    doc = result.scalar_one_or_none()
    if doc is None:
        raise exc.HTTP404NotFound()

    # Pick the latest version
    versions = sorted(doc.versions, key=lambda v: v.number, reverse=True)
    if not versions:
        return OcrQualityResponse(
            document_id=document_id,
            ocr_status=doc.ocr_status,
            overall_confidence=0.0,
            page_count=0,
            pages_with_text=0,
            page_scores=[],
            low_confidence_pages=[],
        )

    latest = versions[0]
    pages = sorted(latest.pages, key=lambda p: p.number)

    page_scores: list[PageQualityScore] = [_page_quality(p) for p in pages]
    pages_with_text = sum(1 for s in page_scores if s.word_count > 0)
    low_confidence_pages = [s.page_number for s in page_scores if s.estimated_confidence < 0.7]

    if page_scores:
        overall = sum(s.estimated_confidence for s in page_scores) / len(page_scores)
        overall = round(overall, 4)
    else:
        overall = 0.0

    return OcrQualityResponse(
        document_id=document_id,
        ocr_status=doc.ocr_status,
        overall_confidence=overall,
        page_count=len(pages),
        pages_with_text=pages_with_text,
        page_scores=page_scores,
        low_confidence_pages=low_confidence_pages,
    )


# ---------------------------------------------------------------------------
# POST /documents/{document_id}/re-ocr
# ---------------------------------------------------------------------------

@router.post(
    "/{document_id}/re-ocr",
    response_model=ReOcrResponse,
    responses={
        status.HTTP_403_FORBIDDEN: {
            "description": f"No `{scopes.NODE_UPDATE}` permission on the node",
            "content": OPEN_API_GENERIC_JSON_DETAIL,
        },
        status.HTTP_404_NOT_FOUND: {
            "description": "Document not found",
            "content": OPEN_API_GENERIC_JSON_DETAIL,
        },
    },
)
async def re_ocr_document(
    document_id: uuid.UUID,
    user: require_scopes(scopes.NODE_UPDATE),
    db_session: AsyncSession = Depends(get_db),
) -> ReOcrResponse:
    """Queue re-OCR for a document.

    Resets ocr_status to RECEIVED and dispatches a new process_upload task
    so the OCR worker picks it up again.
    """
    from papermerge.core import orm as core_orm
    from sqlalchemy import update as sa_update
    from papermerge.core.types import OCRStatusEnum

    if not await dbapi_common.has_node_perm(
        db_session,
        node_id=document_id,
        codename=scopes.NODE_UPDATE,
        user_id=user.id,
    ):
        raise exc.HTTP403Forbidden()

    # Fetch document + latest version (need version_id and lang for task args)
    stmt = (
        sa_select(core_orm.Document)
        .options(selectinload(core_orm.Document.versions))
        .where(core_orm.Document.id == document_id)
    )
    result = await db_session.execute(stmt)
    doc = result.scalar_one_or_none()
    if doc is None:
        raise exc.HTTP404NotFound()

    versions = sorted(doc.versions, key=lambda v: v.number, reverse=True)
    if not versions:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document has no versions to re-OCR",
        )
    latest = versions[0]

    # Reset OCR status so UI reflects in-progress state immediately
    await db_session.execute(
        sa_update(core_orm.Document)
        .where(core_orm.Document.id == document_id)
        .values(ocr_status=OCRStatusEnum.received)
    )
    await db_session.commit()

    task_id = str(uuid.uuid4())

    send_task(
        "process_upload",
        kwargs={
            "document_id": str(document_id),
            "document_version_id": str(latest.id),
            "lang": latest.lang or "eng",
            "user_id": str(user.id),
        },
        route_name="s3",
    )

    logger.info(
        f"Re-OCR queued for document {document_id} (version {latest.id})"
    )

    return ReOcrResponse(task_id=task_id, status="queued")


# ---------------------------------------------------------------------------
# GET /ocr/quality-report  — NOTE: separate prefix, mounted via sub-router
# ---------------------------------------------------------------------------

# Separate router with prefix=/ocr so the path /ocr/quality-report doesn't
# collide with /documents/{document_id}/... path parameter matching.

ocr_report_router = APIRouter(
    prefix="/ocr",
    tags=["ocr"],
)


@ocr_report_router.get(
    "/quality-report",
    response_model=list[QualityReportItem],
    responses={
        status.HTTP_403_FORBIDDEN: {
            "description": "Authentication required",
            "content": OPEN_API_GENERIC_JSON_DETAIL,
        },
    },
)
async def get_ocr_quality_report(
    user: require_scopes(scopes.NODE_VIEW),
    threshold: float = Query(0.7, ge=0.0, le=1.0, description="Confidence threshold"),
    limit: int = Query(50, ge=1, le=500),
    db_session: AsyncSession = Depends(get_db),
) -> list[QualityReportItem]:
    """Return documents whose estimated OCR quality is below threshold.

    Scans the user's owned documents (via Ownership table, same pattern as
    GET /documents/), computes per-document quality, and returns those below
    the requested threshold (default 0.7). Results sorted ascending by
    quality (worst first).
    """
    from papermerge.core import orm as core_orm
    from papermerge.core.features.ownership.db.orm import Ownership
    from papermerge.core.types import OwnerType

    # Subquery: document node_ids accessible to the user via Ownership table.
    # Mirrors the pattern in features/document/db/api.py::get_documents.
    user_groups_sq = sa_select(core_orm.UserGroup.group_id).where(
        core_orm.UserGroup.user_id == user.id
    )
    access_condition = sa_select(Ownership.resource_id).where(
        Ownership.resource_type == "node",
        (
            (Ownership.owner_type == OwnerType.USER.value)
            & (Ownership.owner_id == user.id)
        )
        | (
            (Ownership.owner_type == OwnerType.GROUP.value)
            & (Ownership.owner_id.in_(user_groups_sq))
        ),
    )

    stmt = (
        sa_select(core_orm.Document)
        .options(
            selectinload(core_orm.Document.versions).selectinload(
                core_orm.DocumentVersion.pages
            )
        )
        .where(core_orm.Document.id.in_(access_condition))
        .where(core_orm.Document.deleted_at.is_(None))
        .limit(limit * 5)  # over-fetch; filter below threshold in Python
    )

    result = await db_session.execute(stmt)
    docs = result.scalars().all()

    items: list[QualityReportItem] = []
    for doc in docs:
        versions = sorted(doc.versions, key=lambda v: v.number, reverse=True)
        if not versions:
            continue
        latest = versions[0]
        pages = sorted(latest.pages, key=lambda p: p.number)
        if not pages:
            continue

        page_scores = [_page_quality(p) for p in pages]
        overall = sum(s.estimated_confidence for s in page_scores) / len(page_scores)
        overall = round(overall, 4)

        if overall < threshold:
            low_pages = [s.page_number for s in page_scores if s.estimated_confidence < threshold]
            items.append(QualityReportItem(
                document_id=doc.id,
                title=doc.title,
                estimated_quality=overall,
                page_count=len(pages),
                low_confidence_pages=low_pages,
            ))

    # Sort worst first, cap at limit
    items.sort(key=lambda x: x.estimated_quality)
    return items[:limit]

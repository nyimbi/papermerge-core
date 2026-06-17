"""
Page-level operations: rotate, delete, reorder.

Auto-discovered by router_loader.discover_routers() via the router_*.py glob.
Mounted under the /api/v1/documents prefix (inherited from the document feature).
"""
import logging
import os
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from papermerge.core import orm
from papermerge.core.db import common as dbapi_common
from papermerge.core.db.engine import get_db
from papermerge.core.features.auth.dependencies import require_scopes
from papermerge.core.features.auth import scopes
from papermerge.core.features.document.db import api as doc_dbapi
from papermerge.core.features.audit.db.audit_context import AsyncAuditContext
from papermerge.core import exceptions as exc
from papermerge.core.pathlib import abs_docver_path, docver_path

try:
    from pikepdf import Pdf as _Pdf
    _PIKEPDF_AVAILABLE = True
except ImportError:
    _PIKEPDF_AVAILABLE = False

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/documents",
    tags=["documents"],
)


# ---------------------------------------------------------------------------
# Response / request models
# ---------------------------------------------------------------------------

class PageOpResult(BaseModel):
    version: int
    page_count: int


class RotatePageRequest(BaseModel):
    degrees: int  # 90, 180, or 270


class ReorderPagesRequest(BaseModel):
    page_order: list[int]  # 1-based page numbers in desired output order


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_pikepdf():
    if not _PIKEPDF_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Page operations require pikepdf which is not installed",
        )


async def _load_latest_version(
    db_session: AsyncSession,
    document_id: uuid.UUID,
) -> orm.DocumentVersion:
    """Return the latest DocumentVersion ORM object for document_id."""
    stmt = (
        select(orm.DocumentVersion)
        .where(orm.DocumentVersion.document_id == document_id)
        .order_by(orm.DocumentVersion.number.desc())
        .limit(1)
    )
    result = await db_session.execute(stmt)
    ver = result.scalar_one_or_none()
    if ver is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document {document_id} not found or has no versions",
        )
    if not ver.file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document file not available locally (still processing?)",
        )
    return ver


async def _commit_new_version(
    db_session: AsyncSession,
    document_id: uuid.UUID,
    src_ver: orm.DocumentVersion,
    new_pdf: "_Pdf",
    page_count: int,
    user_id: uuid.UUID,
    short_description: str,
) -> orm.DocumentVersion:
    """
    Persist new_pdf to storage and create a new DocumentVersion row.
    Returns the new DocumentVersion ORM object.
    """
    new_ver_id = uuid.uuid4()
    file_name = src_ver.file_name or "document.pdf"
    new_path = abs_docver_path(new_ver_id, file_name)
    os.makedirs(new_path.parent, exist_ok=True)

    new_pdf.save(str(new_path))
    new_pdf.close()

    file_size = os.path.getsize(new_path)

    # Load the document ORM object (needed by create_next_version)
    doc = await db_session.get(orm.Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    # Eagerly load versions so len(doc.versions) is accurate
    await db_session.refresh(doc, ["versions"])

    new_ver = orm.DocumentVersion(
        id=new_ver_id,
        document_id=document_id,
        number=src_ver.number + 1,
        file_name=file_name,
        size=file_size,
        page_count=page_count,
        lang=src_ver.lang,
        mime_type=src_ver.mime_type,
        short_description=short_description,
        creation_reason="page_edit",
        source_version_id=src_ver.id,
        created_by=user_id,
        updated_by=user_id,
    )
    db_session.add(new_ver)

    for page_number in range(1, page_count + 1):
        db_page = orm.Page(
            document_version=new_ver,
            number=page_number,
            page_count=page_count,
            lang=src_ver.lang,
        )
        db_session.add(db_page)

    await db_session.flush()

    # Upload to storage backend (no-op for local, non-fatal for S3)
    try:
        from papermerge.storage.base import get_storage_backend
        storage = get_storage_backend()
        with open(new_path, "rb") as _f:
            _bytes = _f.read()
        await storage.upload_bytes(
            data=_bytes,
            object_key=str(docver_path(new_ver_id, file_name=file_name)),
            content_type="application/pdf",
        )
    except Exception as _ue:
        logger.warning(f"Storage upload of page-op PDF failed (non-fatal for local): {_ue}")

    await db_session.commit()
    return new_ver


# ---------------------------------------------------------------------------
# POST /documents/{document_id}/pages/{page_num}/rotate
# ---------------------------------------------------------------------------

@router.post(
    "/{document_id}/pages/{page_num}/rotate",
    response_model=PageOpResult,
    status_code=200,
    responses={
        status.HTTP_403_FORBIDDEN: {"description": "Insufficient permissions"},
        status.HTTP_404_NOT_FOUND: {"description": "Document or page not found"},
        status.HTTP_409_CONFLICT: {"description": "Document file not ready"},
        status.HTTP_501_NOT_IMPLEMENTED: {"description": "pikepdf not installed"},
    },
)
async def rotate_page(
    document_id: uuid.UUID,
    page_num: int,
    body: RotatePageRequest,
    user: require_scopes(scopes.NODE_UPDATE),
    db_session: AsyncSession = Depends(get_db),
) -> PageOpResult:
    """Rotate a single page by 90, 180, or 270 degrees and save as a new document version.

    page_num is 1-indexed.
    degrees: positive = clockwise, negative = counterclockwise (pikepdf convention).
    """
    _require_pikepdf()

    if body.degrees not in (90, 180, 270, -90, -180, -270):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="degrees must be one of 90, 180, 270 (or negative equivalents)",
        )

    if not await dbapi_common.has_node_perm(
        db_session, node_id=document_id, codename=scopes.NODE_UPDATE, user_id=user.id
    ):
        raise exc.HTTP403Forbidden()

    src_ver = await _load_latest_version(db_session, document_id)
    total_pages = src_ver.page_count or 0

    if page_num < 1 or page_num > total_pages:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Page {page_num} does not exist (document has {total_pages} pages)",
        )

    try:
        src_pdf = _Pdf.open(src_ver.file_path)
        new_pdf = _Pdf.new()
        for i, page in enumerate(src_pdf.pages):
            new_pdf.pages.append(page)
        # Apply rotation to the target page (0-indexed internally)
        target = new_pdf.pages[page_num - 1]
        current_rotation = int(target.get("/Rotate", 0))
        new_rotation = (current_rotation + body.degrees) % 360
        target["/Rotate"] = new_rotation
        src_pdf.close()
    except Exception as e:
        logger.error(f"Rotate page failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"PDF rotation failed: {e}",
        )

    async with AsyncAuditContext(db_session, user_id=user.id, username=user.username):
        new_ver = await _commit_new_version(
            db_session=db_session,
            document_id=document_id,
            src_ver=src_ver,
            new_pdf=new_pdf,
            page_count=total_pages,
            user_id=user.id,
            short_description=f"Rotate page {page_num} by {body.degrees}°",
        )

    logger.info(f"Rotated page {page_num} of document {document_id} by {body.degrees}°, new version {new_ver.number}")
    return PageOpResult(version=new_ver.number, page_count=new_ver.page_count)


# ---------------------------------------------------------------------------
# DELETE /documents/{document_id}/pages/{page_num}
# ---------------------------------------------------------------------------

@router.delete(
    "/{document_id}/pages/{page_num}",
    response_model=PageOpResult,
    status_code=200,
    responses={
        status.HTTP_400_BAD_REQUEST: {"description": "Cannot delete the only page"},
        status.HTTP_403_FORBIDDEN: {"description": "Insufficient permissions"},
        status.HTTP_404_NOT_FOUND: {"description": "Document or page not found"},
        status.HTTP_409_CONFLICT: {"description": "Document file not ready"},
        status.HTTP_501_NOT_IMPLEMENTED: {"description": "pikepdf not installed"},
    },
)
async def delete_page(
    document_id: uuid.UUID,
    page_num: int,
    user: require_scopes(scopes.NODE_UPDATE),
    db_session: AsyncSession = Depends(get_db),
) -> PageOpResult:
    """Delete a single page from a document and save the result as a new version.

    page_num is 1-indexed. Rejected if the document has only one page.
    """
    _require_pikepdf()

    if not await dbapi_common.has_node_perm(
        db_session, node_id=document_id, codename=scopes.NODE_UPDATE, user_id=user.id
    ):
        raise exc.HTTP403Forbidden()

    src_ver = await _load_latest_version(db_session, document_id)
    total_pages = src_ver.page_count or 0

    if total_pages <= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete the only page of a document",
        )

    if page_num < 1 or page_num > total_pages:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Page {page_num} does not exist (document has {total_pages} pages)",
        )

    try:
        src_pdf = _Pdf.open(src_ver.file_path)
        new_pdf = _Pdf.new()
        for i, page in enumerate(src_pdf.pages):
            if i != page_num - 1:  # skip the deleted page (0-indexed)
                new_pdf.pages.append(page)
        src_pdf.close()
    except Exception as e:
        logger.error(f"Delete page failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"PDF page deletion failed: {e}",
        )

    new_page_count = total_pages - 1

    async with AsyncAuditContext(db_session, user_id=user.id, username=user.username):
        new_ver = await _commit_new_version(
            db_session=db_session,
            document_id=document_id,
            src_ver=src_ver,
            new_pdf=new_pdf,
            page_count=new_page_count,
            user_id=user.id,
            short_description=f"Delete page {page_num}",
        )

    logger.info(f"Deleted page {page_num} of document {document_id}, new version {new_ver.number}")
    return PageOpResult(version=new_ver.number, page_count=new_ver.page_count)


# ---------------------------------------------------------------------------
# POST /documents/{document_id}/pages/reorder
# ---------------------------------------------------------------------------

@router.post(
    "/{document_id}/pages/reorder",
    response_model=PageOpResult,
    status_code=200,
    responses={
        status.HTTP_400_BAD_REQUEST: {"description": "Invalid page_order"},
        status.HTTP_403_FORBIDDEN: {"description": "Insufficient permissions"},
        status.HTTP_404_NOT_FOUND: {"description": "Document not found"},
        status.HTTP_409_CONFLICT: {"description": "Document file not ready"},
        status.HTTP_501_NOT_IMPLEMENTED: {"description": "pikepdf not installed"},
    },
)
async def reorder_pages(
    document_id: uuid.UUID,
    body: ReorderPagesRequest,
    user: require_scopes(scopes.NODE_UPDATE),
    db_session: AsyncSession = Depends(get_db),
) -> PageOpResult:
    """Reorder pages of a document and save the result as a new version.

    page_order: 1-based page numbers in the desired output order.
    Example: [3, 1, 2] puts page 3 first, then page 1, then page 2.
    All page numbers must appear exactly once.
    """
    _require_pikepdf()

    if not await dbapi_common.has_node_perm(
        db_session, node_id=document_id, codename=scopes.NODE_UPDATE, user_id=user.id
    ):
        raise exc.HTTP403Forbidden()

    src_ver = await _load_latest_version(db_session, document_id)
    total_pages = src_ver.page_count or 0

    # Validate page_order
    expected = set(range(1, total_pages + 1))
    given = set(body.page_order)

    if len(body.page_order) != total_pages:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"page_order must contain exactly {total_pages} entries, got {len(body.page_order)}",
        )

    if given != expected:
        missing = expected - given
        extra = given - expected
        details = []
        if missing:
            details.append(f"missing pages: {sorted(missing)}")
        if extra:
            details.append(f"unknown pages: {sorted(extra)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid page_order — {'; '.join(details)}",
        )

    # Check for duplicates even if set sizes match
    if len(body.page_order) != len(set(body.page_order)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="page_order contains duplicate page numbers",
        )

    try:
        src_pdf = _Pdf.open(src_ver.file_path)
        new_pdf = _Pdf.new()
        for page_num in body.page_order:
            new_pdf.pages.append(src_pdf.pages[page_num - 1])
        src_pdf.close()
    except Exception as e:
        logger.error(f"Reorder pages failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"PDF page reorder failed: {e}",
        )

    async with AsyncAuditContext(db_session, user_id=user.id, username=user.username):
        new_ver = await _commit_new_version(
            db_session=db_session,
            document_id=document_id,
            src_ver=src_ver,
            new_pdf=new_pdf,
            page_count=total_pages,
            user_id=user.id,
            short_description=f"Reorder pages: {body.page_order}",
        )

    logger.info(f"Reordered pages of document {document_id}, new version {new_ver.number}")
    return PageOpResult(version=new_ver.number, page_count=new_ver.page_count)

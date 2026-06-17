"""
Download and print endpoints for documents.

Auto-discovered by router_loader.py (matches router_*.py pattern).

Routes added under /documents prefix:
  GET /{document_id}/download
  GET /{document_id}/download/pages?pages=1,3-5,8
  GET /{document_id}/pages/{page_num}/image
  GET /{document_id}/download/images
"""
import io
import logging
import re
import uuid
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core import exceptions as exc
from papermerge.core.db import common as dbapi_common
from papermerge.core.db.engine import get_db
from papermerge.core.features.auth import scopes
from papermerge.core.features.auth.dependencies import require_scopes
from papermerge.core.routers.common import OPEN_API_GENERIC_JSON_DETAIL

router = APIRouter(
    prefix="/documents",
    tags=["documents"],
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PAGE_RANGE_RE = re.compile(r"^\d+(-\d+)?$")


def _parse_page_ranges(pages_param: str) -> list[int]:
    """
    Parse a page-range string like "1,3-5,8" into a sorted, deduplicated
    list of 1-based page numbers.

    Raises ValueError on malformed input.
    """
    result: set[int] = set()
    for part in pages_param.split(","):
        part = part.strip()
        if not part:
            continue
        if not _PAGE_RANGE_RE.match(part):
            raise ValueError(f"Invalid page range token: {part!r}")
        if "-" in part:
            start_s, end_s = part.split("-", 1)
            start, end = int(start_s), int(end_s)
            if start > end:
                raise ValueError(f"Range start > end in: {part!r}")
            result.update(range(start, end + 1))
        else:
            result.add(int(part))
    return sorted(result)


def _safe_filename(title: str) -> str:
    """Strip/replace characters unsafe for Content-Disposition filenames."""
    return re.sub(r'[^\w\s\-.]', '_', title).strip()


async def _resolve_latest_doc_ver(db_session: AsyncSession, document_id: uuid.UUID):
    """
    Return the latest DocumentVersion ORM object for the given document.

    Raises HTTPException 404 if not found.
    """
    from papermerge.core import orm as _orm

    stmt = (
        sa_select(_orm.DocumentVersion)
        .where(_orm.DocumentVersion.document_id == document_id)
        .order_by(_orm.DocumentVersion.number.desc())
        .limit(1)
    )
    result = await db_session.execute(stmt)
    doc_ver = result.scalar_one_or_none()
    if doc_ver is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document {document_id} not found or has no versions",
        )
    return doc_ver


async def _resolve_doc_title(db_session: AsyncSession, document_id: uuid.UUID) -> str:
    """Return the node title for a document."""
    from papermerge.core import orm as _orm

    stmt = sa_select(_orm.Document).where(_orm.Document.id == document_id)
    result = await db_session.execute(stmt)
    doc = result.scalar_one_or_none()
    return doc.title if doc else str(document_id)


def _open_fitz(path: Path):
    """Open a PDF with fitz (PyMuPDF). Raises 503 if not installed, 409 if file missing."""
    try:
        import fitz  # noqa: PLC0415 — optional dep
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PDF rendering requires PyMuPDF (fitz). Install with: pip install pymupdf",
        )
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document file not available locally (still processing?)",
        )
    return fitz.open(str(path))


# ---------------------------------------------------------------------------
# GET /documents/{document_id}/download   — full PDF
# ---------------------------------------------------------------------------

@router.get(
    "/{document_id}/download",
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
async def download_document(
    document_id: uuid.UUID,
    user: require_scopes(scopes.NODE_VIEW),
    db_session: AsyncSession = Depends(get_db),
) -> Response:
    """Stream the full PDF for download / browser-print."""
    if not await dbapi_common.has_node_perm(
        db_session,
        node_id=document_id,
        codename=scopes.NODE_VIEW,
        user_id=user.id,
    ):
        raise exc.HTTP403Forbidden()

    doc_ver = await _resolve_latest_doc_ver(db_session, document_id)
    title = await _resolve_doc_title(db_session, document_id)
    file_path: Path = doc_ver.file_path

    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document file not available locally (still processing?)",
        )

    safe_title = _safe_filename(title)
    pdf_bytes = file_path.read_bytes()

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_title}.pdf"',
            "Content-Length": str(len(pdf_bytes)),
            "Cache-Control": "no-store",
        },
    )


# ---------------------------------------------------------------------------
# GET /documents/{document_id}/download/pages?pages=1,3-5,8
# ---------------------------------------------------------------------------

@router.get(
    "/{document_id}/download/pages",
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "description": "Invalid page range syntax",
            "content": OPEN_API_GENERIC_JSON_DETAIL,
        },
        status.HTTP_403_FORBIDDEN: {
            "description": f"No `{scopes.NODE_VIEW}` permission on the node",
            "content": OPEN_API_GENERIC_JSON_DETAIL,
        },
    },
)
async def download_document_pages(
    document_id: uuid.UUID,
    user: require_scopes(scopes.NODE_VIEW),
    pages: str = Query(
        ...,
        description="Comma-separated 1-based page numbers or ranges, e.g. '1,3-5,8'",
        example="1,3-5,8",
    ),
    db_session: AsyncSession = Depends(get_db),
) -> Response:
    """
    Download a subset of pages from a document as a new PDF.

    Page numbers are 1-based. Ranges are inclusive (e.g. "3-5" = pages 3, 4, 5).
    """
    if not await dbapi_common.has_node_perm(
        db_session,
        node_id=document_id,
        codename=scopes.NODE_VIEW,
        user_id=user.id,
    ):
        raise exc.HTTP403Forbidden()

    try:
        page_numbers = _parse_page_ranges(pages)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    if not page_numbers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No pages specified",
        )

    doc_ver = await _resolve_latest_doc_ver(db_session, document_id)
    title = await _resolve_doc_title(db_session, document_id)
    src_path: Path = doc_ver.file_path

    src_doc = _open_fitz(src_path)

    total = src_doc.page_count
    invalid = [p for p in page_numbers if p < 1 or p > total]
    if invalid:
        src_doc.close()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Page numbers out of range (document has {total} pages): "
                + ", ".join(str(p) for p in invalid)
            ),
        )

    # Build subset PDF using fitz
    try:
        import fitz  # noqa: PLC0415

        out_doc = fitz.open()
        # fitz uses 0-based page indices
        out_doc.insert_pdf(src_doc, from_page=0, to_page=-1, start_at=-1)
        # select() keeps only the listed 0-based indices
        out_doc.select([p - 1 for p in page_numbers])
        pdf_bytes = out_doc.tobytes(garbage=4, deflate=True)
        out_doc.close()
    except Exception as e:
        logger.error(f"Page-subset PDF generation failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to build page-subset PDF: {e}",
        )
    finally:
        src_doc.close()

    safe_title = _safe_filename(title)
    # Build a compact page-descriptor for the filename, e.g. "1_3-5_8"
    pages_slug = pages.replace(",", "_").replace(" ", "")
    filename = f"{safe_title}_pages_{pages_slug}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(pdf_bytes)),
            "Cache-Control": "no-store",
        },
    )


# ---------------------------------------------------------------------------
# GET /documents/{document_id}/pages/{page_num}/image
# ---------------------------------------------------------------------------

@router.get(
    "/{document_id}/pages/{page_num}/image",
    responses={
        status.HTTP_403_FORBIDDEN: {
            "description": f"No `{scopes.NODE_VIEW}` permission on the node",
            "content": OPEN_API_GENERIC_JSON_DETAIL,
        },
        status.HTTP_404_NOT_FOUND: {
            "description": "Page not found",
            "content": OPEN_API_GENERIC_JSON_DETAIL,
        },
    },
)
async def get_page_image(
    document_id: uuid.UUID,
    page_num: int,
    user: require_scopes(scopes.NODE_VIEW),
    format: str = Query("png", pattern="^(png|jpeg|jpg)$", description="Output image format"),
    dpi: int = Query(150, ge=72, le=600, description="Render DPI"),
    db_session: AsyncSession = Depends(get_db),
) -> Response:
    """
    Render a single page to a raster image (PNG or JPEG).

    Returns the image bytes with a 1-hour cache header.
    """
    if not await dbapi_common.has_node_perm(
        db_session,
        node_id=document_id,
        codename=scopes.NODE_VIEW,
        user_id=user.id,
    ):
        raise exc.HTTP403Forbidden()

    doc_ver = await _resolve_latest_doc_ver(db_session, document_id)
    src_path: Path = doc_ver.file_path
    pdf_doc = _open_fitz(src_path)

    total = pdf_doc.page_count
    if page_num < 1 or page_num > total:
        pdf_doc.close()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Page {page_num} does not exist (document has {total} pages)",
        )

    try:
        import fitz  # noqa: PLC0415

        page = pdf_doc.load_page(page_num - 1)
        zoom = dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)

        fmt_lower = format.lower()
        if fmt_lower in ("jpeg", "jpg"):
            img_bytes = pix.tobytes("jpeg")
            media_type = "image/jpeg"
        else:
            img_bytes = pix.tobytes("png")
            media_type = "image/png"
    except Exception as e:
        logger.error(f"Page image render failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to render page image: {e}",
        )
    finally:
        pdf_doc.close()

    return Response(
        content=img_bytes,
        media_type=media_type,
        headers={
            "Cache-Control": "public, max-age=3600",
            "Content-Length": str(len(img_bytes)),
        },
    )


# ---------------------------------------------------------------------------
# GET /documents/{document_id}/download/images  — ZIP of all pages as PNG
# ---------------------------------------------------------------------------

@router.get(
    "/{document_id}/download/images",
    responses={
        status.HTTP_403_FORBIDDEN: {
            "description": f"No `{scopes.NODE_VIEW}` permission on the node",
            "content": OPEN_API_GENERIC_JSON_DETAIL,
        },
    },
)
async def download_document_as_images(
    document_id: uuid.UUID,
    user: require_scopes(scopes.NODE_VIEW),
    dpi: int = Query(150, ge=72, le=300, description="Render DPI for each page image"),
    db_session: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """
    Render all pages to PNG and return them as a ZIP archive.

    Each file inside the ZIP is named page_001.png, page_002.png, etc.
    """
    if not await dbapi_common.has_node_perm(
        db_session,
        node_id=document_id,
        codename=scopes.NODE_VIEW,
        user_id=user.id,
    ):
        raise exc.HTTP403Forbidden()

    doc_ver = await _resolve_latest_doc_ver(db_session, document_id)
    title = await _resolve_doc_title(db_session, document_id)
    src_path: Path = doc_ver.file_path
    pdf_doc = _open_fitz(src_path)

    try:
        import fitz  # noqa: PLC0415

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            zoom = dpi / 72.0
            mat = fitz.Matrix(zoom, zoom)
            for i in range(pdf_doc.page_count):
                page = pdf_doc.load_page(i)
                pix = page.get_pixmap(matrix=mat, alpha=False)
                png_bytes = pix.tobytes("png")
                zf.writestr(f"page_{i + 1:03d}.png", png_bytes)
        zip_bytes = buf.getvalue()
    except Exception as e:
        logger.error(f"Image ZIP generation failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate image ZIP: {e}",
        )
    finally:
        pdf_doc.close()

    safe_title = _safe_filename(title)

    def _iter():
        yield zip_bytes

    return StreamingResponse(
        _iter(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_title}_images.zip"',
            "Content-Length": str(len(zip_bytes)),
            "Cache-Control": "no-store",
        },
    )

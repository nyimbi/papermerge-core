import difflib
import logging
import os
import uuid
from typing import Any

try:
    import pikepdf
    from pikepdf import Pdf as _Pdf
    _PIKEPDF_AVAILABLE = True
except ImportError:
    _PIKEPDF_AVAILABLE = False

from fastapi import (
    APIRouter,
    HTTPException,
    UploadFile,
    status,
    Query,
    Depends,
    Form
)
from pydantic import BaseModel
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.features.auth.dependencies import require_scopes
from papermerge.core import exceptions as exc
from papermerge.core import constants as const
from papermerge.core import dbapi
from papermerge.core.features.auth import scopes
from papermerge.core.features.document.schema import (
    DocumentTypeArg,
)
from papermerge.core import schema, pathlib, types
from papermerge.core.config import get_settings
from papermerge.core.tasks import send_task
from papermerge.core.features.document.db import api as doc_dbapi
from papermerge.core.db import common as dbapi_common
from papermerge.core.routers.common import OPEN_API_GENERIC_JSON_DETAIL
from papermerge.core.db.engine import get_db
from papermerge.core.features.audit.db.audit_context import AsyncAuditContext
from .schema import DocumentParams, AnomalyResult
from .anomaly import AnomalyDetectionService
from .mime_detection import (
    UnsupportedFileTypeError,
    InvalidFileError,
    detect_and_validate_mime_type,
)

router = APIRouter(
    prefix="/documents",
    tags=["documents"],
)

logger = logging.getLogger(__name__)
config = get_settings()


@router.get("/")
async def get_documents(
        user: require_scopes(scopes.NODE_VIEW),
        params: DocumentParams = Depends(),
        db_session: AsyncSession = Depends(get_db)
) -> schema.PaginatedResponse[schema.FlatDocument]:
    """Gets paginated list of documents"""
    try:
        filters = params.to_filters()
        result = await dbapi.get_documents(
            db_session,
            user_id=user.id,
            page_size=params.page_size,
            page_number=params.page_number,
            sort_by=params.sort_by,
            sort_direction=params.sort_direction,
            filters=filters
        )
    except Exception as e:
        logger.error(
            f"Error fetching documents by the user {user.id}: {e}",
            exc_info=True
        )
        raise HTTPException(status_code=500, detail="Internal server error")

    return result


@router.patch(
    "/{document_id}/custom-fields/values/bulk",
    responses={
        status.HTTP_403_FORBIDDEN: {
            "description": f"No `{scopes.NODE_UPDATE}` permission on the node",
            "content": OPEN_API_GENERIC_JSON_DETAIL,
        }
    },
)
async def bulk_set_document_custom_field_values(
        document_id: uuid.UUID,
        values: dict[uuid.UUID, Any],
        user: require_scopes(scopes.NODE_UPDATE),
        db_session: AsyncSession = Depends(get_db),
) -> list[schema.CustomFieldValue]:
    """Update document's custom fields"""
    if not await dbapi_common.has_node_perm(
            db_session,
            node_id=document_id,
            codename=scopes.NODE_UPDATE,
            user_id=user.id,
    ):
        raise exc.HTTP403Forbidden()

    try:
        async with AsyncAuditContext(
                db_session,
                user_id=user.id,
                username=user.username
        ):
            updated_entries = await dbapi.bulk_set_custom_field_values(
                db_session,
                document_id=document_id,
                values=values
            )
    except NoResultFound:
        raise exc.HTTP404NotFound()

    send_task(
        const.PATH_TMPL_MOVE_DOCUMENT,
        kwargs={"document_id": str(document_id)},
        route_name="path_tmpl",
    )

    return updated_entries


@router.get(
    "/{document_id}/custom-fields",
    response_model=list[schema.CustomFieldWithValue],
    responses={
        status.HTTP_403_FORBIDDEN: {
            "description": f"No `{scopes.NODE_VIEW}` permission on the node",
            "content": OPEN_API_GENERIC_JSON_DETAIL,
        }
    },
)
async def get_document_custom_field_values(
        document_id: uuid.UUID,
        user: require_scopes(scopes.NODE_VIEW),
        db_session: AsyncSession = Depends(get_db),
) -> list[schema.CustomFieldWithValue]:
    """Get document custom field values"""
    if not await dbapi_common.has_node_perm(
            db_session,
            node_id=document_id,
            codename=scopes.NODE_VIEW,
            user_id=user.id,
    ):
        raise exc.HTTP403Forbidden()

    try:
        doc = await dbapi.get_document_custom_field_values(
            db_session,
            document_id=document_id,
        )
    except NoResultFound:
        raise exc.HTTP404NotFound()

    return doc


@router.post(
    "/upload",
    status_code=201,
    response_model=schema.DocumentUploadResponse,
    responses={
        status.HTTP_403_FORBIDDEN: {
            "description": f"No `{scopes.NODE_CREATE}` or `{scopes.DOCUMENT_UPLOAD}` permission",
            "content": OPEN_API_GENERIC_JSON_DETAIL,
        }
    },
)
async def upload_document(
    user: require_scopes(scopes.NODE_CREATE, scopes.DOCUMENT_UPLOAD),
    file: UploadFile,
    title: str | None = Form(None),
    parent_id: uuid.UUID | None = Form(None),
    document_id: uuid.UUID | None = Form(None),
    ocr: bool = Form(False),
    lang: str | None = Form(None),
    db_session: AsyncSession = Depends(get_db),
):
    """
    Creates a document model and uploads file in same time.

    Usage with cURL:

            $ curl <server url>/api/documents/upload -F "file=@booking.pdf"
                -F "title=coco.pdf"
                -F "lang=eng"
                -F "parent_id=<UUID of parent folder>"

    The only required field is `file`:

            $ curl <server url>/api/documents/upload -F "file=@booking.pdf"

    If parent_id is not provided, the document will be uploaded to the user's inbox.
    If title is not provided, the filename will be used as the title.
    User needs as well `NODE_VIEW` permission on the parent folder.
    (Users of course have `NODE_VIEW` permission on their own inbox folder)
    """
    if parent_id is None:
        parent_id = user.inbox_folder_id

    if not title:
        title = file.filename

    # Check permission on parent
    if not await dbapi_common.has_node_perm(
            db_session,
            node_id=parent_id,
            codename=scopes.NODE_VIEW,
            user_id=user.id,
    ):
        raise exc.HTTP403Forbidden()

    # At this point user has
    # 1. NODE_VIEW perm on the parent node
    # 2. CREATE_NODE and DOCUMENT_UPLOAD perms

    # Use user's default language if not specified
    if lang is None:
        default_value = config.default_lang
        # take value from user preferences if present or from
        # global application config otherwise
        lang = user.preferences.document_default_lang or default_value

    # Generate document ID early (needed for R2 object key)
    doc_id = document_id if document_id is not None else uuid.uuid4()
    document_version_id = uuid.uuid4()

    # ============================================================
    # Validate file WITHOUT reading entire content
    # ============================================================
    # Read only first chunk for mime type detection
    first_chunk = await file.read(8192)  # Read 8KB for magic number detection
    await file.seek(0)  # Reset file pointer

    client_content_type = file.headers.get("content-type")

    # Detect and validate mime type
    try:
        mime_type = detect_and_validate_mime_type(
            first_chunk,
            file.filename,
            client_content_type=client_content_type,
            validate_structure=False
        )
    except UnsupportedFileTypeError as e:
        logger.warning(f"Unsupported file type for '{file.filename}': {e}")
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {e}"
        )
    except InvalidFileError as e:
        logger.warning(f"Invalid file structure for '{file.filename}': {e}")
        raise HTTPException(
            status_code=400,  # Payload Too Large
            detail=f"File is corrupted or invalid: {e}"
        )

    max_file_size = config.max_file_size_mb * 1024 * 1024
    if file.size > max_file_size:
        raise HTTPException(
            status_code=413,  # Payload Too Large
            detail=f"File too large. Maximum size is {max_file_size / (1024*1024)}MB"
        )
    from papermerge.storage.base import get_storage_backend
    from papermerge.storage.exc import StorageUploadError, FileTooLargeError

    storage = get_storage_backend()

    object_key = str(pathlib.docver_path(
        document_version_id,
        file_name=file.filename)
    )

    try:
        await storage.upload_file(
            file=file,
            object_key=object_key,
            content_type=mime_type,
            max_file_size=max_file_size
        )
    except FileTooLargeError as e:
        raise HTTPException(status_code=413, detail=str(e))
    except StorageUploadError as e:
        logger.error(f"Storage upload failed for document {doc_id}: {e}")
        raise HTTPException(status_code=500, detail="File upload failed")

    async with AsyncAuditContext(
        db_session,
        user_id=user.id,
        username=user.username
    ):

        new_document = schema.NewDocument(
            id=doc_id,
            title=title,
            lang=lang,
            parent_id=parent_id,
            size=0,
            page_count=0,
            ocr=ocr,
            file_name=file.filename or title,
            ctype="document",
            created_by=user.id,
            updated_by=user.id
        )

        try:
            doc = await doc_dbapi.create_document(
                db_session,
                new_document,
                mime_type=mime_type,
                document_version_id=document_version_id
            )
        except Exception as e:
            try:
                await storage.delete_file(object_key)
            except Exception as clean_ex:
                logger.warning(f"Failed to cleanup uploaded file {object_key}: {clean_ex}")
            raise HTTPException(status_code=400, detail=str(e))

    send_task(
        "process_upload",
        kwargs={
            "document_id": str(doc.id),
            "document_version_id": str(document_version_id),
            "lang": str(lang),
            "user_id": str(user.id),
        },
        route_name="s3"
    )

    # Queue embedding indexing and entity extraction after OCR completes
    send_task(
        "darchiva.documents.index_embeddings",
        kwargs={"document_id": str(doc.id), "user_id": str(user.id)},
        countdown=120,
    )
    send_task(
        "darchiva.documents.extract_entities",
        kwargs={"document_id": str(doc.id), "user_id": str(user.id)},
        countdown=130,
    )

    # Dispatch document.created webhook event
    try:
        from papermerge.core.tasks import dispatch_webhook_event
        _tid = str(getattr(user, "tenant_id", None) or user.id)
        dispatch_webhook_event(
            "document.created",
            {
                "document_id": str(doc.id),
                "tenant_id": _tid,
                "title": doc.title,
                "user_id": str(user.id),
            },
            tenant_id=_tid,
        )
        # ocr_complete fires after a delay matching the embedding/entity countdown
        send_task(
            "darchiva.webhooks.deliver_ocr_complete",
            kwargs={
                "document_id": str(doc.id),
                "tenant_id": _tid,
                "user_id": str(user.id),
            },
            countdown=135,
        )
    except Exception as _wh_err:
        logger.warning(f"webhook dispatch failed (non-fatal): {_wh_err}")

    logger.info(f"Document {doc.id} uploaded, queued for processing")

    return doc


@router.post(
    "/upload-scan",
    status_code=201,
    response_model=schema.DocumentUploadResponse,
    responses={
        status.HTTP_403_FORBIDDEN: {
            "description": f"No `{scopes.NODE_CREATE}` or `{scopes.DOCUMENT_UPLOAD}` permission",
            "content": OPEN_API_GENERIC_JSON_DETAIL,
        }
    },
)
async def upload_scanned_document(
    user: require_scopes(scopes.NODE_CREATE, scopes.DOCUMENT_UPLOAD),
    file: UploadFile,
    project_id: str | None = Form(None),
    batch_id: str | None = Form(None),
    parent_id: uuid.UUID | None = Form(None),
    db_session: AsyncSession = Depends(get_db),
):
    """
    Upload a scanned document from browser-based scanning.

    This endpoint is used when the frontend directly scans from a local
    network scanner and needs to upload the result to the backend.

    The scanned image is stored and associated with the given project/batch
    if provided.
    """
    # Default to user's inbox if no parent specified
    if parent_id is None:
        parent_id = user.inbox_folder_id

    # Generate filename from timestamp
    import time
    ext = file.filename.split('.')[-1] if file.filename and '.' in file.filename else 'jpg'
    title = f"scan_{int(time.time())}.{ext}"

    # Check permission on parent
    if not await dbapi_common.has_node_perm(
            db_session,
            node_id=parent_id,
            codename=scopes.NODE_VIEW,
            user_id=user.id,
    ):
        raise exc.HTTP403Forbidden()

    # Use default language
    lang = user.preferences.document_default_lang or config.default_lang

    # Generate IDs
    doc_id = uuid.uuid4()
    document_version_id = uuid.uuid4()

    # Read first chunk for mime type detection
    first_chunk = await file.read(8192)
    await file.seek(0)

    client_content_type = file.headers.get("content-type")

    # Detect and validate mime type
    try:
        mime_type = detect_and_validate_mime_type(
            first_chunk,
            title,
            client_content_type=client_content_type,
            validate_structure=False
        )
    except UnsupportedFileTypeError as e:
        logger.warning(f"Unsupported file type for scan: {e}")
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {e}"
        )
    except InvalidFileError as e:
        logger.warning(f"Invalid file structure for scan: {e}")
        raise HTTPException(
            status_code=400,
            detail=f"File is corrupted or invalid: {e}"
        )

    max_file_size = config.max_file_size_mb * 1024 * 1024
    if file.size and file.size > max_file_size:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size is {max_file_size / (1024*1024)}MB"
        )

    from papermerge.storage.base import get_storage_backend
    from papermerge.storage.exc import StorageUploadError, FileTooLargeError

    storage = get_storage_backend()

    object_key = str(pathlib.docver_path(
        document_version_id,
        file_name=title)
    )

    try:
        await storage.upload_file(
            file=file,
            object_key=object_key,
            content_type=mime_type,
            max_file_size=max_file_size
        )
    except FileTooLargeError as e:
        raise HTTPException(status_code=413, detail=str(e))
    except StorageUploadError as e:
        logger.error(f"Storage upload failed for scanned document {doc_id}: {e}")
        raise HTTPException(status_code=500, detail="File upload failed")

    async with AsyncAuditContext(
        db_session,
        user_id=user.id,
        username=user.username
    ):
        new_document = schema.NewDocument(
            id=doc_id,
            title=title,
            lang=lang,
            parent_id=parent_id,
            size=file.size or 0,
            page_count=1,  # Single page for scanned images
            ocr=False,
            file_name=title,
            ctype="document",
            created_by=user.id,
            updated_by=user.id
        )

        try:
            doc = await doc_dbapi.create_document(
                db_session,
                new_document,
                mime_type=mime_type,
                document_version_id=document_version_id
            )
        except Exception as e:
            try:
                await storage.delete_file(object_key)
            except Exception as clean_ex:
                logger.warning(f"Failed to cleanup uploaded scan {object_key}: {clean_ex}")
            raise HTTPException(status_code=400, detail=str(e))

    # Process the upload for thumbnail generation
    send_task(
        "process_upload",
        kwargs={
            "document_id": str(doc.id),
            "document_version_id": str(document_version_id),
            "lang": str(lang),
            "user_id": str(user.id),
        },
        route_name="s3"
    )

    # If batch tracking is enabled, add to batch documents
    if project_id and batch_id:
        try:
            from papermerge.core.features.scanning_projects.db import api as scanning_dbapi
            await scanning_dbapi.add_batch_document(
                db_session,
                batch_id=uuid.UUID(batch_id),
                document_id=doc.id,
                page_number=1,
                quality_score=90,  # Default quality for browser scans
            )
        except Exception as e:
            logger.warning(f"Failed to add document to batch: {e}")

    logger.info(f"Scanned document {doc.id} uploaded from browser")

    return doc


@router.get(
    "/{doc_id}/last-version/",
    responses={
        status.HTTP_403_FORBIDDEN: {
            "description": f"No `{scopes.NODE_VIEW}` permission on the node",
            "content": OPEN_API_GENERIC_JSON_DETAIL,
        }
    },
)
async def get_document_last_version(
        doc_id: uuid.UUID,
        user: require_scopes(scopes.NODE_VIEW),
        db_session: AsyncSession = Depends(get_db),
) -> schema.DocumentVersion:
    """Returns document's last version"""
    try:
        if not await dbapi_common.has_node_perm(
                db_session,
                node_id=doc_id,
                codename=scopes.NODE_VIEW,
                user_id=user.id,
        ):
            raise exc.HTTP403Forbidden()

        result = await dbapi.get_last_doc_ver(
            db_session,
            doc_id=doc_id,
        )
    except NoResultFound:
        raise exc.HTTP404NotFound()

    return result


@router.get(
    "/{doc_id}/versions",
    responses={
        status.HTTP_403_FORBIDDEN: {
            "description": f"No `{scopes.NODE_VIEW}` permission on the node",
            "content": OPEN_API_GENERIC_JSON_DETAIL,
        }
    },
)
async def get_doc_versions_list(
        doc_id: uuid.UUID,
        user: require_scopes(scopes.NODE_VIEW),
        db_session: AsyncSession = Depends(get_db),
) -> list[schema.DocVerListItem]:
    """
    Returns versions list for given document ID

    Returned versions are sorted descending by version number.
    """
    try:
        if not await dbapi_common.has_node_perm(
                db_session,
                node_id=doc_id,
                codename=scopes.NODE_VIEW,
                user_id=user.id,
        ):
            raise exc.HTTP403Forbidden()

        result = await dbapi.get_doc_versions_list(
            db_session,
            doc_id=doc_id,
        )
    except NoResultFound:
        raise exc.HTTP404NotFound()

    return result


@router.get(
    "/{document_id}",
    responses={
        status.HTTP_403_FORBIDDEN: {
            "description": f"No `{scopes.NODE_VIEW}` permission on the node",
            "content": OPEN_API_GENERIC_JSON_DETAIL,
        }
    },
)
async def get_document_details(
        document_id: uuid.UUID,
        user: require_scopes(scopes.NODE_VIEW),
        db_session: AsyncSession = Depends(get_db),
) -> schema.DocumentWithoutVersions:
    """Get document details"""
    try:
        if not await dbapi_common.has_node_perm(
                db_session,
                node_id=document_id,
                codename=scopes.NODE_VIEW,
                user_id=user.id,
        ):
            raise exc.HTTP403Forbidden()

        doc = await dbapi.get_doc(db_session, id=document_id, user_id=user.id)
    except NoResultFound:
        raise exc.HTTP404NotFound()
    return doc


class OcrWord(BaseModel):
    """Per-word OCR data with fractional page coordinates."""
    text: str
    confidence: float        # 0.0 – 1.0
    x: float                 # left edge, fraction of page width
    y: float                 # top edge, fraction of page height
    width: float             # fraction of page width
    height: float            # fraction of page height


class OcrWordsResponse(BaseModel):
    words: list[OcrWord]
    source: str              # "hocr" | "placeholder"
    page_number: int


@router.get(
    "/{document_id}/pages/{page_number}/ocr-words",
    responses={
        status.HTTP_403_FORBIDDEN: {
            "description": f"No `{scopes.NODE_VIEW}` permission on the node",
            "content": OPEN_API_GENERIC_JSON_DETAIL,
        }
    },
)
async def get_page_ocr_words(
        document_id: uuid.UUID,
        page_number: int,
        user: require_scopes(scopes.NODE_VIEW),
        db_session: AsyncSession = Depends(get_db),
) -> OcrWordsResponse:
    """Return per-word OCR data for a single page.

    Coordinates (x, y, width, height) are fractions of the page image
    dimensions (0.0–1.0), suitable for CSS `position: absolute` overlays.

    When an hOCR file exists for the page the real Tesseract word
    confidence values are returned.  When no hOCR file is present
    (e.g. the document was imported as plain text), a placeholder
    response is returned with uniform 0.85 confidence so the overlay
    renders without error.
    """
    from sqlalchemy import select as sa_select
    from papermerge.core import orm as core_orm
    from papermerge.core.pathlib import abs_page_hocr_path
    from papermerge.core.lib import extract_words_from

    # Permission check
    if not await dbapi_common.has_node_perm(
            db_session,
            node_id=document_id,
            codename=scopes.NODE_VIEW,
            user_id=user.id,
    ):
        raise exc.HTTP403Forbidden()

    # Resolve the page ID from document_id + page_number (last version)
    stmt = (
        sa_select(core_orm.Page)
        .join(core_orm.DocumentVersion,
              core_orm.Page.document_version_id == core_orm.DocumentVersion.id)
        .where(core_orm.DocumentVersion.document_id == document_id)
        .where(core_orm.Page.number == page_number)
        .order_by(core_orm.DocumentVersion.number.desc())
        .limit(1)
    )
    result = await db_session.execute(stmt)
    page_orm = result.scalar_one_or_none()

    if page_orm is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Page {page_number} not found for document {document_id}",
        )

    hocr_path = abs_page_hocr_path(page_orm.id)

    if not hocr_path.exists():
        # No hOCR: return placeholder so the overlay still renders
        return OcrWordsResponse(
            words=[],
            source="placeholder",
            page_number=page_number,
        )

    # Parse hOCR — extract_words_from returns pixel coords; we need the
    # page image dimensions to normalise them.  The hOCR file itself
    # carries the page bbox in the ocr_page span, so we read it directly.
    import re as _re
    import lxml.html as _lhtml

    hocr_bytes = hocr_path.read_bytes()
    html_root = _lhtml.fromstring(hocr_bytes)

    # Page dimensions from the ocr_page element
    page_width_px = 1.0
    page_height_px = 1.0
    for page_span in html_root.xpath("//*[@class='ocr_page']"):
        title_attr = page_span.attrib.get('title', '')
        m = _re.search(r'bbox\s+\d+\s+\d+\s+(\d+)\s+(\d+)', title_attr)
        if m:
            page_width_px = float(m.group(1)) or 1.0
            page_height_px = float(m.group(2)) or 1.0
            break

    raw_words = extract_words_from(hocr_path)
    words: list[OcrWord] = []
    for w in raw_words:
        x1, y1, x2, y2 = w['x1'], w['y1'], w['x2'], w['y2']
        fw = (x2 - x1) / page_width_px
        fh = (y2 - y1) / page_height_px
        if fw <= 0 or fh <= 0:
            continue
        words.append(OcrWord(
            text=w['text'],
            confidence=w['wconf'] / 100.0,
            x=x1 / page_width_px,
            y=y1 / page_height_px,
            width=fw,
            height=fh,
        ))

    return OcrWordsResponse(
        words=words,
        source="hocr",
        page_number=page_number,
    )


# ---------------------------------------------------------------------------
# Named entity extraction endpoints
# ---------------------------------------------------------------------------

class EntityItem(BaseModel):
    entity_type: str
    value: str
    confidence: float | None = None
    page_number: int | None = None
    bbox: dict | None = None


class EntitiesResponse(BaseModel):
    entities: list[EntityItem]


class ReExtractResponse(BaseModel):
    queued: bool
    message: str


@router.get(
    "/{document_id}/entities",
    response_model=EntitiesResponse,
    responses={
        status.HTTP_403_FORBIDDEN: {
            "description": f"No `{scopes.NODE_VIEW}` permission on the node",
            "content": OPEN_API_GENERIC_JSON_DETAIL,
        }
    },
)
async def get_document_entities(
        document_id: uuid.UUID,
        user: require_scopes(scopes.NODE_VIEW),
        db_session: AsyncSession = Depends(get_db),
) -> EntitiesResponse:
    """
    Return named entities extracted from a document.

    Entities are stored in the document_metadata JSONB column under the
    'entities' key, populated by the darchiva.documents.extract_entities
    Celery task after OCR completes.

    The raw storage shape (from the LLM extraction task) is a flat dict:
      {vendor, invoice_number, invoice_date, due_date, total_amount, currency, document_type}

    This endpoint normalises that into a list of EntityItem objects so the
    frontend can render them uniformly regardless of document type.
    """
    if not await dbapi_common.has_node_perm(
            db_session,
            node_id=document_id,
            codename=scopes.NODE_VIEW,
            user_id=user.id,
    ):
        raise exc.HTTP403Forbidden()

    from sqlalchemy import select as _sa_select
    from papermerge.core.features.document.db.orm import Document as _DocORM

    stmt = _sa_select(_DocORM).where(_DocORM.id == document_id)
    result = await db_session.execute(stmt)
    doc = result.scalar_one_or_none()
    if doc is None:
        raise exc.HTTP404NotFound()

    metadata = doc.document_metadata or {}
    raw_entities = metadata.get("entities", {})

    if not raw_entities:
        return EntitiesResponse(entities=[])

    # Normalise: the task stores a flat dict of known fields.
    # Map each non-null field to a typed EntityItem.
    _FIELD_TYPE_MAP: dict[str, str] = {
        "vendor": "ORG",
        "invoice_number": "OTHER",
        "invoice_date": "DATE",
        "due_date": "DATE",
        "total_amount": "MONEY",
        "currency": "OTHER",
        "document_type": "OTHER",
    }

    items: list[EntityItem] = []

    if isinstance(raw_entities, dict):
        for field_name, entity_type in _FIELD_TYPE_MAP.items():
            value = raw_entities.get(field_name)
            if value is None:
                continue
            # Combine total_amount + currency into a single MONEY entity
            if field_name == "total_amount":
                currency = raw_entities.get("currency", "")
                display = f"{value} {currency}".strip() if currency else str(value)
                items.append(EntityItem(entity_type="MONEY", value=display))
                continue
            if field_name == "currency":
                # Already folded into total_amount above — skip standalone
                continue
            items.append(EntityItem(entity_type=entity_type, value=str(value)))
    elif isinstance(raw_entities, list):
        # Future shape: list of {text, label, ...} dicts from SpaCy/ocrworker
        for ent in raw_entities:
            if not isinstance(ent, dict):
                continue
            label = ent.get("label") or ent.get("entity_type") or "OTHER"
            text_val = ent.get("text") or ent.get("value") or ""
            if not text_val:
                continue
            items.append(EntityItem(
                entity_type=label,
                value=text_val,
                confidence=ent.get("confidence") or ent.get("score"),
                page_number=ent.get("page_number"),
                bbox=ent.get("bbox"),
            ))

    return EntitiesResponse(entities=items)


@router.post(
    "/{document_id}/re-extract-entities",
    response_model=ReExtractResponse,
    responses={
        status.HTTP_403_FORBIDDEN: {
            "description": f"No `{scopes.NODE_UPDATE}` permission on the node",
            "content": OPEN_API_GENERIC_JSON_DETAIL,
        }
    },
)
async def re_extract_document_entities(
        document_id: uuid.UUID,
        user: require_scopes(scopes.NODE_UPDATE),
        db_session: AsyncSession = Depends(get_db),
) -> ReExtractResponse:
    """Queue entity re-extraction for the given document."""
    if not await dbapi_common.has_node_perm(
            db_session,
            node_id=document_id,
            codename=scopes.NODE_UPDATE,
            user_id=user.id,
    ):
        raise exc.HTTP403Forbidden()

    send_task(
        "darchiva.documents.extract_entities",
        kwargs={"document_id": str(document_id), "user_id": str(user.id)},
    )
    logger.info(f"Re-extract entities queued for document {document_id}")
    return ReExtractResponse(queued=True, message="Entity extraction queued")


@router.get(
    "/{document_id}/anomaly",
    response_model=AnomalyResult,
    responses={
        status.HTTP_403_FORBIDDEN: {
            "description": f"No `{scopes.NODE_VIEW}` permission on the node",
            "content": OPEN_API_GENERIC_JSON_DETAIL,
        }
    },
)
async def detect_document_anomalies(
        document_id: uuid.UUID,
        user: require_scopes(scopes.NODE_VIEW),
        db_session: AsyncSession = Depends(get_db),
) -> AnomalyResult:
    """Detect anomalies in document metadata"""
    if not await dbapi_common.has_node_perm(
            db_session,
            node_id=document_id,
            codename=scopes.NODE_VIEW,
            user_id=user.id,
    ):
        raise exc.HTTP403Forbidden()

    service = AnomalyDetectionService(db_session)
    # Get user's tenant_id if applicable
    tenant_id = getattr(user, 'tenant_id', None)
    
    result = await service.detect_anomalies(document_id, tenant_id=tenant_id)
    return result


@router.patch(
    "/{document_id}/type",
    responses={
        status.HTTP_403_FORBIDDEN: {
            "description": f"No `{scopes.NODE_UPDATE}` permission on the node",
            "content": OPEN_API_GENERIC_JSON_DETAIL,
        }
    },
)
async def update_document_type(
        document_id: uuid.UUID,
        document_type: DocumentTypeArg,
        user: require_scopes(scopes.NODE_VIEW),
        db_session: AsyncSession = Depends(get_db),
):
    """Updates document type"""
    try:
        if not await dbapi_common.has_node_perm(
                db_session,
                node_id=document_id,
                codename=scopes.NODE_UPDATE,
                user_id=user.id,
        ):
            raise exc.HTTP403Forbidden()

        async with AsyncAuditContext(
                db_session,
                user_id=user.id,
                username=user.username
        ):
            await dbapi.update_doc_type(
                db_session,
                document_id=document_id,
                document_type_id=document_type.document_type_id,
            )
    except NoResultFound:
        raise exc.HTTP404NotFound()

    send_task(
        const.PATH_TMPL_MOVE_DOCUMENT,
        kwargs={"document_id": str(document_id)},
        route_name="path_tmpl",
    )


@router.get(
    "/type/{document_type_id}/",
    response_model=schema.PaginatedResponse[schema.DocumentCFV]
)
async def get_documents_by_type(
        document_type_id: uuid.UUID,
        user: require_scopes(scopes.NODE_VIEW),
        params: schema.DocumentsByTypeParams = Depends(),
        db_session: AsyncSession = Depends(get_db),
) -> schema.PaginatedResponse[schema.DocumentCFV]:
    """
    Get all documents of specific type with all custom field values
    """
    try:
        result = await dbapi.get_documents_by_type_paginated(
            db_session,
            document_type_id=document_type_id,
            user_id=user.id,
            page_size=params.page_size,
            page_number=params.page_number,
            sort_by=params.sort_by,
            sort_direction=params.sort_direction,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid parameters: {str(e)}"
        )
    except Exception as e:
        logger.error(
            f"Error fetching documents by type for user {user.id}: {e}",
            exc_info=True
        )
        raise HTTPException(status_code=500, detail="Internal server error")

    return result


@router.get(
    "/thumbnail-img-status/",
    responses={
        status.HTTP_403_FORBIDDEN: {
            "description": f"No `{scopes.NODE_VIEW}` permission on one of the documents",
            "content": OPEN_API_GENERIC_JSON_DETAIL,
        }
    },
)
async def get_document_doc_thumbnail_status(
        user: require_scopes(scopes.NODE_VIEW),
        doc_ids: list[uuid.UUID] = Query(),
        db_session: AsyncSession = Depends(get_db),
) -> list[schema.DocumentPreviewImageStatus]:
    """
    Get documents thumbnail image preview status

    Receives as input a list of document IDs (i.e. node IDs).

    In case of CDN setup, for each document with NULL value in `preview_status`
    field - one `S3worker` task will be scheduled for generating respective
    document thumbnail.
    """

    for doc_id in doc_ids:
        if not await dbapi_common.has_node_perm(
                db_session,
                node_id=doc_id,
                codename=scopes.NODE_VIEW,
                user_id=user.id,
        ):
            raise exc.HTTP403Forbidden()

    response, doc_ids_not_yet_considered = await dbapi.get_docs_thumbnail_img_status(
        db_session, doc_ids=doc_ids
    )

    storage_backend = config.storage_backend
    if storage_backend in (types.StorageBackend.S3, types.StorageBackend.R2):
        if len(doc_ids_not_yet_considered) > 0:
            for doc_id in doc_ids_not_yet_considered:
                send_task(
                    const.S3_WORKER_GENERATE_DOC_THUMBNAIL,
                    kwargs={"doc_id": str(doc_id)},
                    route_name="s3preview",
                )

    return response


# ---------------------------------------------------------------------------
# Version diff response models
# ---------------------------------------------------------------------------

class DiffChunk(BaseModel):
    type: str  # "equal" | "insert" | "delete"
    words: list[str]


class VersionDiffResponse(BaseModel):
    version_a: int
    version_b: int
    additions: int
    deletions: int
    unchanged: int
    diff: list[DiffChunk]


def _extract_version_text(db_ver) -> str:
    """
    Return the full text for a DocumentVersion ORM object.

    Prefer DocumentVersion.text (already concatenated by OCR worker).
    Fall back to joining page-level text in page-number order.
    """
    if db_ver.text:
        return db_ver.text

    pages = sorted(db_ver.pages, key=lambda p: p.number)
    parts = [p.text for p in pages if p.text]
    return " ".join(parts)


def _word_diff(text_a: str, text_b: str) -> list[DiffChunk]:
    """Word-level diff using difflib.SequenceMatcher."""
    words_a = text_a.split()
    words_b = text_b.split()

    sm = difflib.SequenceMatcher(None, words_a, words_b, autojunk=False)
    chunks: list[DiffChunk] = []

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            chunks.append(DiffChunk(type="equal", words=words_a[i1:i2]))
        elif tag == "insert":
            chunks.append(DiffChunk(type="insert", words=words_b[j1:j2]))
        elif tag == "delete":
            chunks.append(DiffChunk(type="delete", words=words_a[i1:i2]))
        elif tag == "replace":
            # Treat as delete-then-insert so the frontend has clean segments
            chunks.append(DiffChunk(type="delete", words=words_a[i1:i2]))
            chunks.append(DiffChunk(type="insert", words=words_b[j1:j2]))

    return chunks


@router.get(
    "/{document_id}/versions/diff",
    response_model=VersionDiffResponse,
    responses={
        status.HTTP_403_FORBIDDEN: {
            "description": f"No `{scopes.NODE_VIEW}` permission on the node",
            "content": OPEN_API_GENERIC_JSON_DETAIL,
        },
        status.HTTP_404_NOT_FOUND: {
            "description": "Document or requested version not found",
            "content": OPEN_API_GENERIC_JSON_DETAIL,
        },
    },
)
async def get_document_version_diff(
        document_id: uuid.UUID,
        user: require_scopes(scopes.NODE_VIEW),
        version_a: int = Query(..., ge=1, description="Version number of the older snapshot"),
        version_b: int = Query(..., ge=1, description="Version number of the newer snapshot"),
        db_session: AsyncSession = Depends(get_db),
) -> VersionDiffResponse:
    """
    Compute a word-level text diff between two versions of a document.

    Returns classified word chunks (equal / insert / delete) suitable for
    rendering a split-pane or inline diff view in the frontend.
    """
    if not await dbapi_common.has_node_perm(
            db_session,
            node_id=document_id,
            codename=scopes.NODE_VIEW,
            user_id=user.id,
    ):
        raise exc.HTTP403Forbidden()

    from sqlalchemy import select as _select
    from papermerge.core import orm as _orm
    from sqlalchemy.orm import selectinload as _selectinload

    async def _load_ver(number: int):
        stmt = (
            _select(_orm.DocumentVersion)
            .options(_selectinload(_orm.DocumentVersion.pages))
            .where(
                _orm.DocumentVersion.document_id == document_id,
                _orm.DocumentVersion.number == number,
            )
        )
        result = await db_session.execute(stmt)
        return result.scalar_one_or_none()

    ver_a = await _load_ver(version_a)
    ver_b = await _load_ver(version_b)

    if ver_a is None or ver_b is None:
        missing = version_a if ver_a is None else version_b
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Version {missing} not found for document {document_id}",
        )

    text_a = _extract_version_text(ver_a)
    text_b = _extract_version_text(ver_b)

    chunks = _word_diff(text_a, text_b)

    additions = sum(len(c.words) for c in chunks if c.type == "insert")
    deletions = sum(len(c.words) for c in chunks if c.type == "delete")
    unchanged = sum(len(c.words) for c in chunks if c.type == "equal")

    return VersionDiffResponse(
        version_a=version_a,
        version_b=version_b,
        additions=additions,
        deletions=deletions,
        unchanged=unchanged,
        diff=chunks,
    )


# ---------------------------------------------------------------------------
# Merge request / response models
# ---------------------------------------------------------------------------

class MergeDocumentsRequest(BaseModel):
    source_document_ids: list[uuid.UUID]
    title: str
    destination_folder_id: uuid.UUID | None = None


class MergeDocumentsResponse(BaseModel):
    document_id: uuid.UUID
    title: str
    page_count: int
    version_id: uuid.UUID


# ---------------------------------------------------------------------------
# Split request / response models
# ---------------------------------------------------------------------------

class SplitDocumentRequest(BaseModel):
    at_page: int
    title_part1: str | None = None
    title_part2: str | None = None


class SplitPartInfo(BaseModel):
    document_id: uuid.UUID
    title: str
    page_count: int
    version_id: uuid.UUID


class SplitDocumentResponse(BaseModel):
    part1: SplitPartInfo
    part2: SplitPartInfo


# ---------------------------------------------------------------------------
# POST /documents/merge
# ---------------------------------------------------------------------------

@router.post(
    "/merge",
    status_code=201,
    response_model=MergeDocumentsResponse,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "description": "pypdf not installed or invalid source documents",
            "content": OPEN_API_GENERIC_JSON_DETAIL,
        },
        status.HTTP_403_FORBIDDEN: {
            "description": f"No `{scopes.NODE_CREATE}` or `{scopes.NODE_VIEW}` permission",
            "content": OPEN_API_GENERIC_JSON_DETAIL,
        },
    },
)
async def merge_documents(
    body: MergeDocumentsRequest,
    user: require_scopes(scopes.NODE_CREATE, scopes.NODE_VIEW),
    db_session: AsyncSession = Depends(get_db),
) -> MergeDocumentsResponse:
    """
    Merge multiple PDFs into a single new document.

    Source documents are merged in the order specified by source_document_ids.
    The merged document is placed in destination_folder_id (defaults to user inbox).
    """
    if not _PIKEPDF_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="PDF merge requires pikepdf which is not installed",
        )

    if len(body.source_document_ids) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least two source documents are required for merge",
        )

    parent_id = body.destination_folder_id or user.inbox_folder_id

    # Verify read permission on parent destination
    if not await dbapi_common.has_node_perm(
            db_session,
            node_id=parent_id,
            codename=scopes.NODE_VIEW,
            user_id=user.id,
    ):
        raise exc.HTTP403Forbidden()

    # Resolve latest version for each source document and verify read access
    from sqlalchemy import select as _sa_select
    from papermerge.core import orm as _orm
    from sqlalchemy.orm import selectinload as _sil

    source_versions: list[_orm.DocumentVersion] = []
    for doc_id in body.source_document_ids:
        if not await dbapi_common.has_node_perm(
                db_session,
                node_id=doc_id,
                codename=scopes.NODE_VIEW,
                user_id=user.id,
        ):
            raise exc.HTTP403Forbidden()

        stmt = (
            _sa_select(_orm.DocumentVersion)
            .options(_sil(_orm.DocumentVersion.pages))
            .where(_orm.DocumentVersion.document_id == doc_id)
            .order_by(_orm.DocumentVersion.number.desc())
            .limit(1)
        )
        result = await db_session.execute(stmt)
        doc_ver = result.scalar_one_or_none()
        if doc_ver is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Document {doc_id} not found or has no versions",
            )
        if not doc_ver.file_path.exists():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Document {doc_id} file not available locally (still processing?)",
            )
        source_versions.append(doc_ver)

    # Perform merge with pikepdf
    new_doc_id = uuid.uuid4()
    new_ver_id = uuid.uuid4()
    merged_file_name = f"{body.title.replace(' ', '_')}.pdf"

    from papermerge.core.pathlib import abs_docver_path as _abs_docver_path

    merged_path = _abs_docver_path(new_ver_id, merged_file_name)
    os.makedirs(merged_path.parent, exist_ok=True)

    total_pages = 0
    try:
        merged_pdf = _Pdf.new()
        for doc_ver in source_versions:
            src_pdf = _Pdf.open(doc_ver.file_path)
            for page in src_pdf.pages:
                merged_pdf.pages.append(page)
                total_pages += 1
            src_pdf.close()
        merged_pdf.save(merged_path)
        merged_pdf.close()
    except Exception as e:
        logger.error(f"PDF merge failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"PDF merge failed: {e}",
        )

    merged_size = os.path.getsize(merged_path)
    lang = user.preferences.document_default_lang or config.default_lang

    new_document = schema.NewDocument(
        id=new_doc_id,
        title=body.title,
        lang=lang,
        parent_id=parent_id,
        size=merged_size,
        page_count=total_pages,
        ocr=False,
        file_name=merged_file_name,
        ctype="document",
        created_by=user.id,
        updated_by=user.id,
    )

    async with AsyncAuditContext(db_session, user_id=user.id, username=user.username):
        result = await doc_dbapi.create_document(
            db_session,
            new_document,
            mime_type="application/pdf",
            document_version_id=new_ver_id,
        )
        if isinstance(result, tuple):
            doc, error = result
        else:
            doc, error = result, None

        if error:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))

    # Upload merged PDF to storage (for non-local backends)
    from papermerge.storage.base import get_storage_backend
    from papermerge.core.pathlib import docver_path as _docver_path
    storage = get_storage_backend()
    object_key = str(_docver_path(new_ver_id, file_name=merged_file_name))
    try:
        with open(merged_path, "rb") as _f:
            merged_bytes = _f.read()
        await storage.upload_bytes(
            data=merged_bytes,
            object_key=object_key,
            content_type="application/pdf",
        )
    except Exception as upload_err:
        logger.warning(f"Storage upload of merged PDF failed (non-fatal for local): {upload_err}")

    logger.info(f"Merged {len(source_versions)} documents into {doc.id} ({total_pages} pages)")

    return MergeDocumentsResponse(
        document_id=doc.id,
        title=doc.title,
        page_count=total_pages,
        version_id=new_ver_id,
    )


# ---------------------------------------------------------------------------
# POST /documents/{document_id}/split
# ---------------------------------------------------------------------------

@router.post(
    "/{document_id}/split",
    status_code=201,
    response_model=SplitDocumentResponse,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "description": "Invalid split point or missing pikepdf",
            "content": OPEN_API_GENERIC_JSON_DETAIL,
        },
        status.HTTP_403_FORBIDDEN: {
            "description": f"No `{scopes.NODE_CREATE}` or `{scopes.NODE_VIEW}` permission",
            "content": OPEN_API_GENERIC_JSON_DETAIL,
        },
    },
)
async def split_document(
    document_id: uuid.UUID,
    body: SplitDocumentRequest,
    user: require_scopes(scopes.NODE_CREATE, scopes.NODE_VIEW),
    db_session: AsyncSession = Depends(get_db),
) -> SplitDocumentResponse:
    """
    Split a PDF document into two parts at the given page boundary.

    Pages 1..at_page become part 1; pages at_page+1..end become part 2.
    Both new documents are placed in the same folder as the original.
    """
    if not _PIKEPDF_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="PDF split requires pikepdf which is not installed",
        )

    if not await dbapi_common.has_node_perm(
            db_session,
            node_id=document_id,
            codename=scopes.NODE_VIEW,
            user_id=user.id,
    ):
        raise exc.HTTP403Forbidden()

    from sqlalchemy import select as _sa_select
    from papermerge.core import orm as _orm
    from sqlalchemy.orm import selectinload as _sil

    # Load source document and its latest version
    stmt = (
        _sa_select(_orm.Document)
        .options(_sil(_orm.Document.versions))
        .where(_orm.Document.id == document_id)
    )
    result = await db_session.execute(stmt)
    src_doc = result.scalar_one_or_none()
    if src_doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    stmt2 = (
        _sa_select(_orm.DocumentVersion)
        .where(_orm.DocumentVersion.document_id == document_id)
        .order_by(_orm.DocumentVersion.number.desc())
        .limit(1)
    )
    r2 = await db_session.execute(stmt2)
    src_ver = r2.scalar_one_or_none()
    if src_ver is None or not src_ver.file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Source document file not available locally",
        )

    # Open source PDF and validate split point
    try:
        src_pdf = _Pdf.open(src_ver.file_path)
        total_pages = len(src_pdf.pages)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not open source PDF: {e}",
        )

    at_page = body.at_page
    if at_page < 1 or at_page >= total_pages:
        src_pdf.close()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"at_page must be between 1 and {total_pages - 1} (document has {total_pages} pages)",
        )

    parent_id = src_doc.parent_id
    lang = user.preferences.document_default_lang or config.default_lang

    base_title = src_ver.file_name or src_doc.title or "document"
    stem = base_title.rsplit(".", 1)[0] if "." in base_title else base_title

    title1 = body.title_part1 or f"{stem} (part 1)"
    title2 = body.title_part2 or f"{stem} (part 2)"
    file1 = f"{title1.replace(' ', '_')}.pdf"
    file2 = f"{title2.replace(' ', '_')}.pdf"

    from papermerge.core.pathlib import abs_docver_path as _adp, docver_path as _dp

    ver1_id = uuid.uuid4()
    ver2_id = uuid.uuid4()
    path1 = _adp(ver1_id, file1)
    path2 = _adp(ver2_id, file2)
    os.makedirs(path1.parent, exist_ok=True)
    os.makedirs(path2.parent, exist_ok=True)

    page_count1 = at_page
    page_count2 = total_pages - at_page

    try:
        pdf1 = _Pdf.new()
        for i in range(page_count1):
            pdf1.pages.append(src_pdf.pages[i])
        pdf1.save(path1)
        pdf1.close()

        pdf2 = _Pdf.new()
        for i in range(at_page, total_pages):
            pdf2.pages.append(src_pdf.pages[i])
        pdf2.save(path2)
        pdf2.close()
    except Exception as e:
        logger.error(f"PDF split failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"PDF split failed: {e}",
        )
    finally:
        src_pdf.close()

    size1 = os.path.getsize(path1)
    size2 = os.path.getsize(path2)

    doc1_id = uuid.uuid4()
    doc2_id = uuid.uuid4()

    async with AsyncAuditContext(db_session, user_id=user.id, username=user.username):
        nd1 = schema.NewDocument(
            id=doc1_id,
            title=title1,
            lang=lang,
            parent_id=parent_id,
            size=size1,
            page_count=page_count1,
            ocr=False,
            file_name=file1,
            ctype="document",
            created_by=user.id,
            updated_by=user.id,
        )
        r1 = await doc_dbapi.create_document(
            db_session, nd1, mime_type="application/pdf", document_version_id=ver1_id
        )
        doc1, err1 = r1 if isinstance(r1, tuple) else (r1, None)
        if err1:
            raise HTTPException(status_code=400, detail=str(err1))

        nd2 = schema.NewDocument(
            id=doc2_id,
            title=title2,
            lang=lang,
            parent_id=parent_id,
            size=size2,
            page_count=page_count2,
            ocr=False,
            file_name=file2,
            ctype="document",
            created_by=user.id,
            updated_by=user.id,
        )
        r2 = await doc_dbapi.create_document(
            db_session, nd2, mime_type="application/pdf", document_version_id=ver2_id
        )
        doc2, err2 = r2 if isinstance(r2, tuple) else (r2, None)
        if err2:
            raise HTTPException(status_code=400, detail=str(err2))

    # Upload both parts to storage
    from papermerge.storage.base import get_storage_backend
    storage = get_storage_backend()
    for _path, _ver_id, _fname in [
        (path1, ver1_id, file1),
        (path2, ver2_id, file2),
    ]:
        try:
            with open(_path, "rb") as _f:
                _bytes = _f.read()
            await storage.upload_bytes(
                data=_bytes,
                object_key=str(_dp(_ver_id, _fname)),
                content_type="application/pdf",
            )
        except Exception as _ue:
            logger.warning(f"Storage upload of split PDF failed (non-fatal for local): {_ue}")

    logger.info(
        f"Split document {document_id} at page {at_page}: "
        f"part1={doc1.id}({page_count1}pp) part2={doc2.id}({page_count2}pp)"
    )

    return SplitDocumentResponse(
        part1=SplitPartInfo(
            document_id=doc1.id,
            title=title1,
            page_count=page_count1,
            version_id=ver1_id,
        ),
        part2=SplitPartInfo(
            document_id=doc2.id,
            title=title2,
            page_count=page_count2,
            version_id=ver2_id,
        ),
    )

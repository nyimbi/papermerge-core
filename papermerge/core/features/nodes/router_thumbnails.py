import logging
import os
import uuid
from typing import Annotated

from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import APIRouter, HTTPException, Security, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel

from papermerge.core import utils
from papermerge.core.features.users import schema as usr_schema
from papermerge.core.features.auth import get_current_user
from papermerge.core.features.auth import scopes
from papermerge.core.features.document.db import api as dbapi
from papermerge.core.pathlib import rel2abs, thumbnail_path
from papermerge.core.utils import image
from papermerge.core.db.common import has_node_perm
from papermerge.core.exceptions import HTTP403Forbidden, HTTP404NotFound
from papermerge.core.routers.common import OPEN_API_GENERIC_JSON_DETAIL
from papermerge.core.db.engine import get_db

router = APIRouter(
    prefix="/thumbnails",
    tags=["thumbnails"],
)

logger = logging.getLogger(__name__)


class Message(BaseModel):
    detail: str


class JPEGFileResponse(FileResponse):
    media_type = "application/jpeg"


@router.get(
    "/{document_id}",
    response_class=JPEGFileResponse,
    responses={
        309: {
            "description": """Preview image cannot be generated at this moment
             yet. This may happen for example because the document is currently
            still being uploaded. A later response may succeed with 200 status
            code.""",
            "content": OPEN_API_GENERIC_JSON_DETAIL,
        },
        404: {
            "description": """Document with specified UUID was not found""",
            "content": OPEN_API_GENERIC_JSON_DETAIL,
        },
    },
)
@utils.docstring_parameter(scope=scopes.NODE_VIEW)
async def get_document_thumbnail(
    document_id: uuid.UUID,
    user: Annotated[
        usr_schema.User, Security(get_current_user, scopes=[scopes.NODE_VIEW])
    ],
    db_session: AsyncSession = Depends(get_db),
):
    """Retrieves thumbnail of the document last version's first page

    Required scope: `{scope}`
    """

    ok = await has_node_perm(
        db_session, user_id=user.id, codename=scopes.NODE_VIEW, node_id=document_id
    )
    if not ok:
        raise HTTP403Forbidden()

    try:
        doc_ver = await dbapi.get_last_doc_ver(db_session, doc_id=document_id)
    except NoResultFound:
        raise HTTP404NotFound
    try:
        page = await dbapi.get_first_page(db_session, doc_ver_id=doc_ver.id)
    except NoResultFound:
        raise HTTPException(
            status_code=309,
            detail="Not ready for preview yet",
        )

    jpg_abs_path = rel2abs(thumbnail_path(page.id))

    if not os.path.exists(jpg_abs_path):
        image.gen_doc_thumbnail(
            page_id=page.id,
            doc_ver_id=doc_ver.id,
            page_number=1,
            file_name=doc_ver.file_name,
        )

    return JPEGFileResponse(jpg_abs_path)


@router.get(
    "/{document_id}/page/{page_number}",
    response_class=JPEGFileResponse,
    responses={
        309: {"description": "Document not ready for preview yet", "content": OPEN_API_GENERIC_JSON_DETAIL},
        404: {"description": "Document not found", "content": OPEN_API_GENERIC_JSON_DETAIL},
    },
)
@utils.docstring_parameter(scope=scopes.NODE_VIEW)
async def get_document_page_thumbnail(
    document_id: uuid.UUID,
    page_number: int,
    user: Annotated[
        usr_schema.User, Security(get_current_user, scopes=[scopes.NODE_VIEW])
    ],
    db_session: AsyncSession = Depends(get_db),
):
    """Retrieves thumbnail for a specific page of the document's last version.

    Required scope: `{scope}`
    """
    ok = await has_node_perm(
        db_session, user_id=user.id, codename=scopes.NODE_VIEW, node_id=document_id
    )
    if not ok:
        raise HTTP403Forbidden()

    try:
        doc_ver = await dbapi.get_last_doc_ver(db_session, doc_id=document_id)
    except NoResultFound:
        raise HTTP404NotFound

    from sqlalchemy import select
    from papermerge.core.features.document.db.orm import Page
    stmt = (
        select(Page)
        .where(Page.document_version_id == doc_ver.id)
        .where(Page.number == page_number)
    )
    result = await db_session.execute(stmt)
    page = result.scalar_one_or_none()

    if page is None:
        # Fall back to first page when page_number is out of range
        try:
            page = await dbapi.get_first_page(db_session, doc_ver_id=doc_ver.id)
        except NoResultFound:
            raise HTTPException(status_code=309, detail="Not ready for preview yet")

    jpg_abs_path = rel2abs(thumbnail_path(page.id))

    if not os.path.exists(jpg_abs_path):
        image.gen_doc_thumbnail(
            page_id=page.id,
            doc_ver_id=doc_ver.id,
            page_number=page_number,
            file_name=doc_ver.file_name,
        )

    return JPEGFileResponse(jpg_abs_path)


@router.get(
    "/{document_id}/full",
    responses={
        200: {
            "description": "Full resolution document image",
            "content": {
                "application/pdf": {},
                "image/jpeg": {},
                "image/png": {},
                "image/tiff": {},
            }
        },
        309: {
            "description": "Document not ready for preview yet",
            "content": OPEN_API_GENERIC_JSON_DETAIL,
        },
        404: {
            "description": "Document not found",
            "content": OPEN_API_GENERIC_JSON_DETAIL,
        },
    },
)
@utils.docstring_parameter(scope=scopes.NODE_VIEW)
async def get_document_full(
    document_id: uuid.UUID,
    user: Annotated[
        usr_schema.User, Security(get_current_user, scopes=[scopes.NODE_VIEW])
    ],
    db_session: AsyncSession = Depends(get_db),
):
    """Retrieves full resolution document (last version)

    Required scope: `{scope}`
    """
    from papermerge.core.features.document.response import DocumentFileResponse

    ok = await has_node_perm(
        db_session, user_id=user.id, codename=scopes.NODE_VIEW, node_id=document_id
    )
    if not ok:
        raise HTTP403Forbidden()

    try:
        doc_ver = await dbapi.get_last_doc_ver(db_session, doc_id=document_id)
    except NoResultFound:
        raise HTTP404NotFound

    if not doc_ver.file_path.exists():
        raise HTTPException(
            status_code=309,
            detail="Document file not ready yet",
        )

    return DocumentFileResponse(
        doc_ver.file_path,
        filename=doc_ver.file_name,
        content_disposition_type="inline"  # Display in browser, don't download
    )

import io
import logging
import zipfile
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core import config
from papermerge.core.db.engine import get_db
from papermerge.core.features.auth import scopes
from papermerge.core.features.auth.dependencies import require_scopes
from papermerge.core.features.document.db.api import get_last_doc_ver
from papermerge.core.features.document.db.orm import Document
from papermerge.core.features.users import schema as usr_schema

router = APIRouter(prefix="/nodes", tags=["nodes"])

logger = logging.getLogger(__name__)
settings = config.get_settings()


class BulkDownloadRequest(BaseModel):
    node_ids: list[str]


@router.post("/bulk/download-zip")
async def bulk_download_zip(
    body: BulkDownloadRequest,
    user: Annotated[usr_schema.User, require_scopes(scopes.NODE_VIEW)],
    db_session: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Download multiple documents as a single ZIP archive.

    Queries documents owned by the current user matching the supplied node_ids,
    reads each file from local storage, and streams back a ZIP.

    Required scope: `node.view`
    """
    if not body.node_ids:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, mode="w"):
            pass
        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="application/zip",
            headers={"Content-Disposition": "attachment; filename=documents.zip"},
        )

    stmt = (
        select(Document)
        .where(Document.id.in_(body.node_ids))
        .where(Document.user_id == user.id)
    )
    result = await db_session.execute(stmt)
    docs = result.scalars().all()

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for doc in docs:
            try:
                doc_ver = await get_last_doc_ver(db_session, doc_id=doc.id)
            except Exception:
                logger.warning("No document version found for doc %s — skipping", doc.id)
                continue

            file_path = doc_ver.file_path
            if not file_path.exists():
                logger.warning("File not found at %s — skipping", file_path)
                continue

            arc_name = doc_ver.file_name or f"{doc.id}.bin"
            zf.write(file_path, arcname=arc_name)

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=documents.zip"},
    )

import uuid
import logging

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.features.auth.dependencies import require_scopes
from papermerge.core.features.auth import scopes
from papermerge.core import exceptions as exc
from papermerge.core.db import common as dbapi_common
from papermerge.core.db.engine import get_db
from papermerge.core.routers.common import OPEN_API_GENERIC_JSON_DETAIL
from papermerge.core.tasks import send_task

router = APIRouter(
    prefix="/documents",
    tags=["documents"],
)

logger = logging.getLogger(__name__)


class WatermarkRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=200, description="Watermark text, e.g. CONFIDENTIAL")
    position: str = Field("diagonal", description="One of: diagonal, header, footer, corner")
    opacity: float = Field(0.3, ge=0.05, le=1.0, description="Opacity 0.05–1.0")
    pages: str | list[int] = Field("all", description="'all' or list of 1-based page numbers")
    font_size: int = Field(36, ge=8, le=144, description="Font size in pt")
    color: str = Field("#808080", description="Hex color e.g. #808080")


class WatermarkResponse(BaseModel):
    task_id: str
    status: str = "queued"


@router.post(
    "/{document_id}/watermark",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=WatermarkResponse,
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
async def apply_watermark(
    document_id: uuid.UUID,
    body: WatermarkRequest,
    user: require_scopes(scopes.NODE_UPDATE),
    db_session: AsyncSession = Depends(get_db),
) -> WatermarkResponse:
    """
    Queue a watermark task for the given document.

    The task creates a new document (with '_watermarked' title suffix) containing
    the original PDF with the requested text watermark applied.

    Returns immediately with a task_id; the caller can poll task status via
    the standard Celery result backend or listen for a document.created webhook.
    """
    if not await dbapi_common.has_node_perm(
        db_session,
        node_id=document_id,
        codename=scopes.NODE_UPDATE,
        user_id=user.id,
    ):
        raise exc.HTTP403Forbidden()

    # Validate position value
    allowed_positions = {"diagonal", "header", "footer", "corner"}
    if body.position not in allowed_positions:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"position must be one of: {sorted(allowed_positions)}",
        )

    tenant_id = str(getattr(user, "tenant_id", None) or user.id)

    watermark_params = {
        "text": body.text,
        "position": body.position,
        "opacity": body.opacity,
        "pages": body.pages,
        "font_size": body.font_size,
        "color": body.color,
    }

    task_id = str(uuid.uuid4())

    send_task(
        "darchiva.documents.apply_watermark",
        kwargs={
            "document_id": str(document_id),
            "watermark_params": watermark_params,
            "created_by_id": str(user.id),
            "tenant_id": tenant_id,
        },
    )

    logger.info(
        f"Watermark task queued: doc={document_id} text='{body.text}' "
        f"position={body.position} user={str(user.id)[:8]}"
    )

    return WatermarkResponse(task_id=task_id, status="queued")

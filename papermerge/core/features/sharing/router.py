"""Expiring document share links.

Routes
------
POST   /documents/{document_id}/share-links          — create link (auth)
GET    /documents/{document_id}/share-links          — list links  (auth)
DELETE /documents/{document_id}/share-links/{link_id} — deactivate (auth)
GET    /share/{token}                                — public resolve
"""

import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Security, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core import schema
from papermerge.core.db.engine import get_db
from papermerge.core.features.auth import get_current_user, scopes
from papermerge.core.features.sharing.db.orm import DocumentShareLink

logger = logging.getLogger(__name__)

router = APIRouter(tags=["share-links"])

# ---------------------------------------------------------------------------
# Pydantic I/O schemas
# ---------------------------------------------------------------------------

_EXPIRY_PRESETS: dict[str, timedelta | None] = {
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "never": None,
}


class CreateShareLinkRequest(BaseModel):
    expiry: str = "7d"          # one of the keys in _EXPIRY_PRESETS
    password: str | None = None
    max_views: int | None = None


class ShareLinkOut(BaseModel):
    id: str
    document_id: str
    token: str
    url: str
    expires_at: str | None
    password_protected: bool
    max_views: int | None
    view_count: int
    is_active: bool
    is_valid: bool
    created_at: str


class PublicShareInfo(BaseModel):
    document_id: str
    token: str
    view_count: int
    expires_at: str | None
    password_protected: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hash_password(password: str) -> str:
    """PBKDF2-HMAC-SHA256, 260 000 iterations, hex-encoded."""
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
    return f"{salt}:{dk.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        salt, dk_hex = stored.split(":", 1)
    except ValueError:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
    return secrets.compare_digest(dk.hex(), dk_hex)


def _serialize(link: DocumentShareLink, base_url: str) -> ShareLinkOut:
    return ShareLinkOut(
        id=str(link.id),
        document_id=str(link.document_id),
        token=link.token,
        url=f"{base_url}/share/{link.token}",
        expires_at=link.expires_at.isoformat() if link.expires_at else None,
        password_protected=link.password_hash is not None,
        max_views=link.max_views,
        view_count=link.view_count,
        is_active=link.is_active,
        is_valid=link.is_valid,
        created_at=link.created_at.isoformat(),
    )


def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


# ---------------------------------------------------------------------------
# Authenticated endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/documents/{document_id}/share-links",
    status_code=status.HTTP_201_CREATED,
    response_model=ShareLinkOut,
)
async def create_share_link(
    document_id: uuid.UUID,
    body: CreateShareLinkRequest,
    request: Request,
    user: Annotated[
        schema.User,
        Security(get_current_user, scopes=[scopes.SHARED_NODE_CREATE]),
    ],
    db_session: AsyncSession = Depends(get_db),
) -> ShareLinkOut:
    """Create an expiring share link for a document."""

    if body.expiry not in _EXPIRY_PRESETS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"expiry must be one of {list(_EXPIRY_PRESETS)}",
        )

    delta = _EXPIRY_PRESETS[body.expiry]
    expires_at = datetime.utcnow() + delta if delta else None

    password_hash: str | None = None
    if body.password:
        password_hash = _hash_password(body.password)

    link = DocumentShareLink(
        id=uuid.uuid4(),
        document_id=document_id,
        created_by_id=user.id,
        token=secrets.token_urlsafe(32),
        expires_at=expires_at,
        password_hash=password_hash,
        max_views=body.max_views,
        view_count=0,
        is_active=True,
        created_at=datetime.utcnow(),
    )
    db_session.add(link)
    await db_session.commit()
    await db_session.refresh(link)

    logger.info(
        "share_link.created document_id=%s link_id=%s by user=%s",
        document_id, link.id, user.id,
    )
    return _serialize(link, _base_url(request))


@router.get(
    "/documents/{document_id}/share-links",
    response_model=list[ShareLinkOut],
)
async def list_share_links(
    document_id: uuid.UUID,
    request: Request,
    user: Annotated[
        schema.User,
        Security(get_current_user, scopes=[scopes.SHARED_NODE_VIEW]),
    ],
    db_session: AsyncSession = Depends(get_db),
) -> list[ShareLinkOut]:
    """List all share links for a document (active and inactive)."""

    rows = (
        await db_session.execute(
            select(DocumentShareLink)
            .where(DocumentShareLink.document_id == document_id)
            .order_by(DocumentShareLink.created_at.desc())
        )
    ).scalars().all()

    base = _base_url(request)
    return [_serialize(lnk, base) for lnk in rows]


@router.delete(
    "/documents/{document_id}/share-links/{link_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def deactivate_share_link(
    document_id: uuid.UUID,
    link_id: uuid.UUID,
    user: Annotated[
        schema.User,
        Security(get_current_user, scopes=[scopes.SHARED_NODE_DELETE]),
    ],
    db_session: AsyncSession = Depends(get_db),
) -> None:
    """Deactivate (soft-delete) a share link."""

    link = (
        await db_session.execute(
            select(DocumentShareLink).where(
                DocumentShareLink.id == link_id,
                DocumentShareLink.document_id == document_id,
            )
        )
    ).scalar_one_or_none()

    if not link:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Share link not found",
        )
    if link.created_by_id != user.id and not getattr(user, "is_superuser", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to deactivate this link",
        )

    link.is_active = False
    await db_session.commit()
    logger.info("share_link.deactivated link_id=%s by user=%s", link_id, user.id)


# ---------------------------------------------------------------------------
# Public endpoint — no auth
# ---------------------------------------------------------------------------

@router.get(
    "/share/{token}",
    response_model=PublicShareInfo,
)
async def resolve_share_link(
    token: str,
    password: str | None = None,
    db_session: AsyncSession = Depends(get_db),
) -> PublicShareInfo:
    """
    Public endpoint: validate a share token, optionally check password,
    increment view_count, return document info.

    Query param `password` is used for password-protected links.
    """

    link = (
        await db_session.execute(
            select(DocumentShareLink).where(DocumentShareLink.token == token)
        )
    ).scalar_one_or_none()

    if not link:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Share link not found",
        )
    if not link.is_active:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This share link has been deactivated",
        )
    if link.is_expired:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This share link has expired",
        )
    if link.is_exhausted:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This share link has reached its maximum view count",
        )
    if link.password_hash is not None:
        if not password:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Password required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if not _verify_password(password, link.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect password",
            )

    # Increment view count
    link.view_count += 1
    await db_session.commit()

    return PublicShareInfo(
        document_id=str(link.document_id),
        token=link.token,
        view_count=link.view_count,
        expires_at=link.expires_at.isoformat() if link.expires_at else None,
        password_protected=link.password_hash is not None,
    )

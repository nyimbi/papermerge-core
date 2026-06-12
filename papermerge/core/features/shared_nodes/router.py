import logging
import uuid
import secrets
from datetime import datetime
from typing import Annotated, Any, Union

from fastapi import APIRouter, Security, Depends, Response, status, \
    HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.engine import get_db
from papermerge.core import utils, schema, dbapi
from papermerge.core.features.auth import scopes, get_current_user
from papermerge.core.types import PaginatedResponse
from papermerge.core.features.shared_nodes.schema import SharedNodeParams
from papermerge.core.features.shared_nodes.db.orm import NodeShareLink
from papermerge.core.auth import require_scopes

router = APIRouter(
    prefix="/shared-nodes",
    tags=["shared-nodes"],
)


logger = logging.getLogger(__name__)


@router.get("", response_model=PaginatedResponse[Union[schema.DocumentEx, schema.FolderEx]],
)
async def get_shared_nodes(
    user: require_scopes(scopes.NODE_VIEW),
    params: SharedNodeParams = Depends(),
    db_session: AsyncSession = Depends(get_db),
) -> PaginatedResponse[Union[schema.DocumentEx, schema.FolderEx]]:
    """Returns a list of top level nodes shared with current user"""
    try:
        filters = params.to_filters()
        result = await dbapi.get_paginated_shared_nodes(
            db_session=db_session,
            user_id=user.id,
            page_size=params.page_size,
            page_number=params.page_number,
            sort_by=params.sort_by,
            sort_direction=params.sort_direction,
            filters=filters,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid parameters: {str(e)}")
    except Exception as e:
        logger.error(
            f"Error fetching shared nodes for user {user.id}: {e}",
            exc_info=True
        )
        raise HTTPException(status_code=500, detail="Internal server error")

    return result


@router.post("", status_code=204)
@utils.docstring_parameter(scope=scopes.SHARED_NODE_CREATE)
async def create_shared_nodes(
    shared_node: schema.CreateSharedNode,
    user: Annotated[
        schema.User, Security(get_current_user, scopes=[scopes.SHARED_NODE_CREATE])
    ],
    db_session: AsyncSession=Depends(get_db),
):
    """Creates shared node

    Required scope: `{scope}`
    """

    await dbapi.create_shared_nodes(
        db_session=db_session,
        node_ids=shared_node.node_ids,
        role_ids=shared_node.role_ids,
        user_ids=shared_node.user_ids,
        group_ids=shared_node.group_ids,
        owner_id=user.id,
    )

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/access/{node_id}")
@utils.docstring_parameter(scope=scopes.SHARED_NODE_VIEW)
async def get_shared_node_access_details(
    node_id: uuid.UUID,
    user: Annotated[
        schema.User, Security(get_current_user, scopes=[scopes.SHARED_NODE_VIEW])
    ],
    db_session: AsyncSession=Depends(get_db),
) -> schema.SharedNodeAccessDetails:
    """Get shared node access details

    Required scope: `{scope}`

    In other words: gets info about who can access this node
    and with what roles?
    """
    node_access = await dbapi.get_shared_node_access_details(db_session, node_id=node_id)

    return node_access


@router.patch("/access/{node_id}", status_code=status.HTTP_200_OK)
@utils.docstring_parameter(scope=scopes.SHARED_NODE_UPDATE)
async def update_shared_node_access(
    node_id: uuid.UUID,
    access_update: schema.SharedNodeAccessUpdate,
    user: Annotated[
        schema.User, Security(get_current_user, scopes=[scopes.SHARED_NODE_VIEW])
    ],
    db_session: AsyncSession=Depends(get_db),
):
    """Update shared nodes access

    Required scope: `{scope}`

    More appropriate name for this would be "sync" - because this is
    exactly what it does - it actually syncs content in `access_update` for
    specific node_id to match data in `shared_nodes` table.
    """
    await dbapi.update_shared_node_access(
        db_session, node_id=node_id, access_update=access_update, owner_id=user.id
    )


# ---------------------------------------------------------------------------
# Share Links (public/expiring links to a node)
# ---------------------------------------------------------------------------

def _serialize_link(link: NodeShareLink, request_base_url: str = "") -> dict[str, Any]:
	return {
		"id": str(link.id),
		"node_id": str(link.node_id),
		"token": link.token,
		"url": f"{request_base_url}/shared/{link.token}",
		"permissions": link.permissions or [],
		"password_protected": link.password_hash is not None,
		"expires_at": link.expires_at.isoformat() if link.expires_at else None,
		"max_access_count": link.max_access_count,
		"access_count": link.access_count,
		"created_at": link.created_at.isoformat(),
		"created_by_name": "",
	}


@router.get("/links/{node_id}")
async def list_share_links(
	node_id: uuid.UUID,
	user: Annotated[schema.User, Security(get_current_user, scopes=[scopes.SHARED_NODE_VIEW])],
	db_session: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
	"""List all share links for a node."""
	links = (await db_session.execute(
		select(NodeShareLink)
		.where(NodeShareLink.node_id == node_id)
		.order_by(NodeShareLink.created_at.desc())
	)).scalars().all()
	return [_serialize_link(link) for link in links]


@router.post("/links", status_code=status.HTTP_201_CREATED)
async def create_share_link(
	data: dict[str, Any],
	user: Annotated[schema.User, Security(get_current_user, scopes=[scopes.SHARED_NODE_CREATE])],
	db_session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
	"""Create a public share link for a node."""
	node_id_str = data.get("node_id")
	if not node_id_str:
		raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="node_id required")

	expires_at = None
	if data.get("expires_at"):
		try:
			expires_at = datetime.fromisoformat(str(data["expires_at"]).rstrip("Z"))
		except ValueError:
			raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid expires_at format")

	link = NodeShareLink(
		node_id=uuid.UUID(str(node_id_str)),
		created_by_id=user.id,
		token=secrets.token_urlsafe(24),
		permissions=data.get("permissions", []),
		expires_at=expires_at,
		max_access_count=data.get("max_access_count"),
		access_count=0,
		created_at=datetime.utcnow(),
	)
	db_session.add(link)
	await db_session.commit()
	await db_session.refresh(link)
	return _serialize_link(link)


@router.delete("/links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_share_link(
	link_id: uuid.UUID,
	user: Annotated[schema.User, Security(get_current_user, scopes=[scopes.SHARED_NODE_DELETE])],
	db_session: AsyncSession = Depends(get_db),
) -> None:
	"""Delete a share link."""
	link = (await db_session.execute(
		select(NodeShareLink).where(NodeShareLink.id == link_id)
	)).scalar_one_or_none()
	if not link:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Share link not found")
	if link.created_by_id != user.id and not user.is_superuser:
		raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")
	await db_session.delete(link)
	await db_session.commit()

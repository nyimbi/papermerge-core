import logging
import uuid
from typing import Iterable, Literal, Union
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select, update, delete
from sqlalchemy.exc import NoResultFound, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.exceptions import HTTP404NotFound, EntityNotFound
from papermerge.core import schema, config, orm
from papermerge.core.features.auth import scopes
from papermerge.core.features.nodes.db import api as nodes_dbapi
from papermerge.core.features.auth.dependencies import require_scopes
from papermerge.core.routers.common import OPEN_API_GENERIC_JSON_DETAIL
from papermerge.core.types import PaginatedResponse
from papermerge.core.db import common as dbapi_common
from papermerge.core import exceptions as exc
from papermerge.core.db.engine import get_db
from papermerge.core.features.audit.db.audit_context import AsyncAuditContext
from .schema import NodeParams

router = APIRouter(prefix="/nodes", tags=["nodes"])

logger = logging.getLogger(__name__)
settings = config.get_settings()


@router.get("/tree")
async def get_folder_tree(
    user: require_scopes(scopes.NODE_VIEW),
    db_session: AsyncSession = Depends(get_db),
) -> dict:
    """Returns a tree of folders for navigation.

    Required scope: `node.view`
    """
    home_folder_id = user.home_folder_id
    if home_folder_id is None:
        return {"nodes": []}

    try:
        tree = await nodes_dbapi.get_folder_tree(db_session, home_folder_id)
        return {"nodes": tree}
    except Exception as e:
        logger.error(f"Error fetching folder tree for user {user.id}: {e}", exc_info=True)
        return {"nodes": []}


@router.get("/")
async def get_root_nodes(
    user: require_scopes(scopes.NODE_VIEW),
    params: NodeParams = Depends(),
    db_session: AsyncSession = Depends(get_db),
) -> PaginatedResponse[Union[schema.DocumentEx, schema.FolderEx]]:
    """Returns nodes from user's home folder (root view).

    Required scope: `node.view`
    """
    # Get user's home folder
    home_folder_id = user.home_folder_id
    if home_folder_id is None:
        logger.warning(f"User {user.username} has no home folder")
        return PaginatedResponse(
            page_size=params.page_size,
            page_number=params.page_number,
            num_pages=0,
            items=[],
        )

    try:
        filters = params.to_filters()
        result = await nodes_dbapi.get_paginated_nodes(
            db_session=db_session,
            parent_id=home_folder_id,
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
            f"Error fetching root nodes for user {user.id}: {e}",
            exc_info=True
        )
        raise HTTPException(status_code=500, detail="Internal server error")

    return result


@router.get(
    "/{parent_id}",
    response_model=PaginatedResponse[Union[schema.DocumentEx, schema.FolderEx]],
    responses={
        status.HTTP_403_FORBIDDEN: {
            "description": f"No `{scopes.NODE_VIEW}` permission on the node",
            "content": OPEN_API_GENERIC_JSON_DETAIL,
        }
    },
)
async def get_node(
    parent_id: UUID,
    user: require_scopes(scopes.NODE_VIEW),
    params: NodeParams = Depends(),
    db_session: AsyncSession = Depends(get_db),
) -> PaginatedResponse[Union[schema.DocumentEx, schema.FolderEx]]:
    """Returns list of *paginated* direct descendants of `parent_id` node

    Required scope: `node.view`
    """
    if not await dbapi_common.has_node_perm(
        db_session,
        node_id=parent_id,
        codename=scopes.NODE_VIEW,
        user_id=user.id,
    ):
        raise exc.HTTP403Forbidden()

    try:
        filters = params.to_filters()
        result = await nodes_dbapi.get_paginated_nodes(
            db_session=db_session,
            parent_id=parent_id,
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
            f"Error fetching nodes for parent {parent_id} by user {user.id}: {e}",
            exc_info=True
        )
        raise HTTPException(status_code=500, detail="Internal server error")

    return result


@router.post(
    "/",
    status_code=201,
    responses={
        status.HTTP_403_FORBIDDEN: {
            "description": f"No `{scopes.NODE_CREATE}` permission on the parent node",
            "content": OPEN_API_GENERIC_JSON_DETAIL,
        }
    },
)
async def create_folder(
    pynode: schema.NewFolder,
    user: require_scopes(scopes.NODE_CREATE),
    db_session: AsyncSession = Depends(get_db),
) -> schema.FolderShort:
    """Creates a folder

    Node's `ctype` must be `folder`.
    Optionally you may pass ID attribute. If ID is present and has
    non-emtpy UUID value, then newly create node will be assigned this
    custom ID.
    If node has `parent_id` empty, defaults to user's home folder.
    """

    error = None
    # Default to user's home folder if no parent specified
    parent_id = pynode.parent_id
    logger.info(f"create_folder: pynode.parent_id={pynode.parent_id}, user.home_folder_id={user.home_folder_id}")
    if parent_id is None:
        parent_id = user.home_folder_id
        logger.info(f"create_folder: Using home folder as parent: {parent_id}")

    logger.info(f"create_folder: Checking permission for parent_id={parent_id}, user.id={user.id}")
    if not await dbapi_common.has_node_perm(
            db_session,
            node_id=parent_id,
            codename=scopes.NODE_CREATE,
            user_id=user.id,
    ):
        raise exc.HTTP403Forbidden()

    attrs = dict(
        title=pynode.title,
        ctype="folder",
        parent_id=parent_id,
    )
    if pynode.id:
        attrs["id"] = pynode.id
    new_folder = schema.NewFolder(**attrs)

    async with AsyncAuditContext(
        db_session,
        user_id=user.id,
        username=user.username
    ):
        created_node, error = await nodes_dbapi.create_folder(
            db_session,
            new_folder,
            created_by=user.id
        )

    if error:
        raise HTTPException(status_code=400, detail=error.model_dump())

    return created_node


@router.patch(
    "/{node_id}",
    responses={
        status.HTTP_403_FORBIDDEN: {
            "description": f"No `{scopes.NODE_UPDATE}` permission on the node",
            "content": OPEN_API_GENERIC_JSON_DETAIL,
        }
    },
)
async def update_node(
    node_id: UUID,
    node: schema.UpdateNode,
    user: require_scopes(scopes.NODE_UPDATE),
    db_session: AsyncSession = Depends(get_db),
) -> schema.NodeShort:
    """Updates node

    parent_id is optional field. However, when present, parent_id
    should be not empty string (UUID).
    """

    if not await dbapi_common.has_node_perm(
        db_session,
        node_id=node_id,
        codename=scopes.NODE_UPDATE,
        user_id=user.id,
    ):
        raise exc.HTTP403Forbidden()

    async with AsyncAuditContext(
        db_session,
        user_id=user.id,
        username=user.username
    ):
        updated_node = await nodes_dbapi.update_node(
            db_session, node_id=node_id, attrs=node
        )

    return updated_node


@router.delete(
    "/",
    responses={
        status.HTTP_403_FORBIDDEN: {
            "description": f"No `{scopes.NODE_DELETE}` permission on some of the nodes"
            "at least one of the specified nodes",
            "content": OPEN_API_GENERIC_JSON_DETAIL,
        }
    },
)
async def delete_nodes(
    list_of_uuids: list[UUID],
    user: require_scopes(scopes.NODE_DELETE),
    db_session: AsyncSession = Depends(get_db),
):
    """Deletes nodes with specified UUIDs

    Returns a list of UUIDs of actually deleted nodes.
    In case nothing was deleted (e.g. no nodes with specified UUIDs
    were found) - will return an empty list.
    """
    for node_id in list_of_uuids:
        if not await dbapi_common.has_node_perm(
            db_session,
            node_id=node_id,
            codename=scopes.NODE_DELETE,
            user_id=user.id,
        ):
            raise exc.HTTP403Forbidden()

    async with AsyncAuditContext(
        db_session,
        user_id=user.id,
        username=user.username
    ):
        error = await nodes_dbapi.delete_nodes(
            db_session, node_ids=list_of_uuids, user_id=user.id
        )

    if error:
        raise HTTPException(status_code=400, detail=error.model_dump())


@router.post(
    "/move",
    responses={
        status.HTTP_403_FORBIDDEN: {
            "description": f"Check user has `{scopes.NODE_MOVE}` on all source nodes "
            f" and `{scopes.NODE_UPDATE}` on the target node.",
            "content": OPEN_API_GENERIC_JSON_DETAIL,
        },
        432: {
            "description": """Move of mentioned node is not possible due
            to duplicate title on the target""",
            "content": OPEN_API_GENERIC_JSON_DETAIL,
        },
        400: {
            "description": """No target node with specified UUID found""",
            "content": OPEN_API_GENERIC_JSON_DETAIL,
        },
        419: {
            "description": """No nodes were updated""",
            "content": OPEN_API_GENERIC_JSON_DETAIL,
        },
        420: {
            "description": """Not all nodes were updated""",
            "content": OPEN_API_GENERIC_JSON_DETAIL,
        },
    },
)
async def move_nodes(
    params: schema.MoveNode,
    user: require_scopes(scopes.NODE_MOVE),
    db_session: AsyncSession = Depends(get_db),
) -> list[UUID]:
    """Move source nodes into the target node.

    User should have

        * `node.update` permission for the target node
        * `node.move` permission for each source node

    In other words, after successful completion of this action
    all source nodes will have target node as their parent.
    Think of set of folders and/or documents being moved from one
    folder into another folder.

    Returns UUIDs of successfully moved nodes.
    """
    try:
        for source_id in params.source_ids:
            if not await dbapi_common.has_node_perm(
                db_session,
                node_id=source_id,
                codename=scopes.NODE_MOVE,
                user_id=user.id,
            ):
                raise exc.HTTP403Forbidden()

        if not await dbapi_common.has_node_perm(
            db_session,
            node_id=params.target_id,
            codename=scopes.NODE_UPDATE,
            user_id=user.id,
        ):
            raise exc.HTTP403Forbidden()

        async with AsyncAuditContext(
                db_session,
                user_id=user.id,
                username=user.username
        ):
            affected_row_count = await nodes_dbapi.move_nodes(
                db_session,
                source_ids=params.source_ids,
                target_id=params.target_id,
            )
    except NoResultFound as e:
        logger.error(e, exc_info=True)
        error = schema.Error(
            messages=["No results found. Please check that all source nodes exists"]
        )
        raise HTTPException(status_code=404, detail=error.model_dump())
    except (IntegrityError, EntityNotFound) as e:
        logger.debug(exc, exc_info=True)
        error = schema.Error(
            messages=["Integrity error. Please check that target exists"]
        )
        raise HTTPException(status_code=400, detail=error.model_dump())

    if affected_row_count == 0:
        error = schema.Error(
            messages=["No nodes were updated. Please check that source nodes exists"]
        )
        raise HTTPException(status_code=419, detail=error.model_dump())

    if affected_row_count != len(params.source_ids):
        error = schema.Error(
            messages=[
                "Not all nodes were updated"
                f"(only {affected_row_count} out of {len(params.source_ids)})."
                " Please check that all source nodes exists"
            ]
        )
        raise HTTPException(status_code=420, detail=error.model_dump())

    return params.source_ids


class _MoveTarget(BaseModel):
    target_id: UUID


@router.patch("/{node_id}/move")
async def move_single_node(
    node_id: UUID,
    body: _MoveTarget,
    user: require_scopes(scopes.NODE_MOVE),
    db_session: AsyncSession = Depends(get_db),
) -> list[UUID]:
    """Move a single node into the target folder (frontend single-item move)."""
    try:
        if not await dbapi_common.has_node_perm(
            db_session,
            node_id=node_id,
            codename=scopes.NODE_MOVE,
            user_id=user.id,
        ):
            raise exc.HTTP403Forbidden()

        if not await dbapi_common.has_node_perm(
            db_session,
            node_id=body.target_id,
            codename=scopes.NODE_UPDATE,
            user_id=user.id,
        ):
            raise exc.HTTP403Forbidden()

        async with AsyncAuditContext(db_session, user_id=user.id, username=user.username):
            affected_row_count = await nodes_dbapi.move_nodes(
                db_session,
                source_ids=[node_id],
                target_id=body.target_id,
            )
    except exc.HTTP403Forbidden:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    except NoResultFound as e:
        logger.error(e, exc_info=True)
        raise HTTPException(
            status_code=404,
            detail=schema.Error(messages=["Node not found"]).model_dump(),
        )
    except (IntegrityError, EntityNotFound) as e:
        logger.debug(e, exc_info=True)
        raise HTTPException(
            status_code=400,
            detail=schema.Error(messages=["Move failed — check target exists and name is unique"]).model_dump(),
        )

    if affected_row_count == 0:
        raise HTTPException(
            status_code=419,
            detail=schema.Error(messages=["Node not found or already at target"]).model_dump(),
        )

    return [node_id]


@router.post(
    "/{node_id}/tags",
    responses={
        status.HTTP_403_FORBIDDEN: {
            "description": f"User does not have `{scopes.NODE_UPDATE}` permission on the node",
            "content": OPEN_API_GENERIC_JSON_DETAIL,
        },
    },
)
async def assign_node_tags(
    node_id: UUID,
    tags: list[str],
    user: require_scopes(scopes.NODE_UPDATE),
    db_session: AsyncSession = Depends(get_db),
) -> schema.DocumentShort | schema.FolderShort:
    """
    Assigns given list of tag names to the node.

    All tags not present in given list of tags names
    will be disassociated from the node; in other words upon
    successful completion of the request node will have ONLY
    tags from the list.
    Yet another way of thinking about http POST is as it **replaces
    existing node tags** with the one from input list.
    """
    try:
        if not await dbapi_common.has_node_perm(
            db_session,
            node_id=node_id,
            codename=scopes.NODE_UPDATE,
            user_id=user.id,
        ):
            raise exc.HTTP403Forbidden()

        async with AsyncAuditContext(
            db_session,
            user_id=user.id,
            username=user.username
        ):
            node = await nodes_dbapi.assign_node_tags(
                db_session, node_id=node_id, tags=tags, created_by=user.id
            )
    except EntityNotFound:
        await db_session.rollback()
        raise HTTP404NotFound
    except Exception:
        await db_session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to assign tags"
        )

    if node.ctype == "folder":
        return schema.FolderShort.model_validate(node)

    return schema.DocumentShort.model_validate(node)


@router.get(
    "/",
    responses={
        status.HTTP_403_FORBIDDEN: {
            "description": f"User does not have `{scopes.NODE_VIEW}` permission on "
            "some of the nodes",
            "content": OPEN_API_GENERIC_JSON_DETAIL,
        }
    },
)
async def get_nodes_details(
    user: require_scopes(scopes.NODE_VIEW),
    node_ids: list[uuid.UUID] | None = Query(default=None),
    db_session: AsyncSession = Depends(get_db),
) -> list[schema.Folder | schema.Document]:
    """Returns detailed information about queried nodes
    (breadcrumb, tags)

    Dev note: this API endpoint is used by UI to fetch tags and breadcrumbs
    for the *search results*, as search index does not store these attributes.
    """
    if node_ids is None:
        return []

    if len(node_ids) == 0:
        return []

    for node_id in node_ids:
        if not await dbapi_common.has_node_perm(
            db_session,
            node_id=node_id,
            codename=scopes.NODE_VIEW,
            user_id=user.id,
        ):
            raise exc.HTTP403Forbidden()

    nodes = await nodes_dbapi.get_nodes(db_session, node_ids=node_ids, user_id=user.id)

    return nodes


@router.patch(
    "/{node_id}/tags",
    responses={
        status.HTTP_403_FORBIDDEN: {
            "description": f"User does not have `{scopes.NODE_UPDATE}` permission on the node",
            "content": OPEN_API_GENERIC_JSON_DETAIL,
        },
    },
)
async def update_node_tags(
    node_id: UUID,
    tags: list[str],
    user: require_scopes(scopes.NODE_UPDATE),
    db_session: AsyncSession = Depends(get_db),
) -> schema.DocumentShort | schema.FolderShort:
    """
    Appends given list of tag names to the node.

    Retains all previously associated node tags.
    Yet another way of thinking about http PATCH method is as it
    **appends** input tags to the currently associated tags.

    Example:

        Node N1 has 'invoice', 'important' tags.

        After following request:

            POST /api/nodes/<N1>/tags/

            tags: ['paid']

        Node N1 will have 'invoice', 'important', 'paid' tags.
        Notice that previously associated 'invoice' and 'important' tags
        are still assigned to N1.
    """
    try:
        if not await dbapi_common.has_node_perm(
            db_session,
            node_id=node_id,
            codename=scopes.NODE_UPDATE,
            user_id=user.id,
        ):
            raise exc.HTTP403Forbidden()

        async with AsyncAuditContext(
            db_session,
            user_id=user.id,
            username=user.username
        ):
            node = await nodes_dbapi.update_node_tags(
                db_session, node_id=node_id, tags=tags
            )
    except EntityNotFound:
        await db_session.rollback()
        raise HTTP404NotFound
    except Exception:
        await db_session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to assign tags"
        )

    if node.ctype == "folder":
        return schema.FolderShort.model_validate(node)

    return schema.DocumentShort.model_validate(node)


@router.get(
    "/{node_id}/tags",
    responses={
        status.HTTP_403_FORBIDDEN: {
            "description": f"User does not have `{scopes.NODE_VIEW}` permission on the node",
            "content": OPEN_API_GENERIC_JSON_DETAIL,
        },
    },
)
async def get_node_tags(
    node_id: UUID,
    user: require_scopes(scopes.NODE_VIEW),
    db_session=Depends(get_db),
) -> Iterable[schema.Tag]:
    """Retrieves nodes tags"""
    try:
        if not await dbapi_common.has_node_perm(
            db_session,
            node_id=node_id,
            codename=scopes.NODE_VIEW,
            user_id=user.id,
        ):
            raise exc.HTTP403Forbidden()

        tags, error = await nodes_dbapi.get_node_tags(
            db_session, node_id=node_id, user_id=user.id
        )
    except EntityNotFound:
        raise HTTP404NotFound

    if error:
        raise HTTPException(status_code=400, detail=error.model_dump())

    return tags


@router.delete(
    "/{node_id}/tags",
    responses={
        status.HTTP_403_FORBIDDEN: {
            "description": f"User does not have `{scopes.NODE_UPDATE}` permission on the node",
            "content": OPEN_API_GENERIC_JSON_DETAIL,
        },
    },
)
async def remove_node_tags(
    node_id: UUID,
    tags: list[str],
    user: require_scopes(scopes.NODE_VIEW),
    db_session: AsyncSession = Depends(get_db),
) -> schema.DocumentShort | schema.FolderShort:
    """
    Dissociate given tags the node.

    Tags models are not deleted - just dissociated from the node.
    """
    try:
        if not await dbapi_common.has_node_perm(
            db_session,
            node_id=node_id,
            codename=scopes.NODE_UPDATE,
            user_id=user.id,
        ):
            raise exc.HTTP403Forbidden()

        async with AsyncAuditContext(
            db_session,
            user_id=user.id,
            username=user.username
        ):
            node = await nodes_dbapi.remove_node_tags(
                db_session, node_id=node_id, tags=tags, user_id=user.id
            )
    except EntityNotFound:
        await db_session.rollback()
        raise HTTP404NotFound
    except Exception:
        await db_session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to assign tags"
            )

    if node.ctype == "folder":
        return schema.FolderShort.model_validate(node)

    return schema.DocumentShort.model_validate(node)


# ---------------------------------------------------------------------------
# Bulk operation request/response models
# ---------------------------------------------------------------------------

class BulkMoveRequest(BaseModel):
    node_ids: list[UUID]
    target_folder_id: UUID


class BulkMoveResponse(BaseModel):
    moved: int
    failed: int
    errors: list[str] = []


class BulkDeleteRequest(BaseModel):
    node_ids: list[UUID]


class BulkDeleteResponse(BaseModel):
    deleted: int
    failed: int


class BulkTagRequest(BaseModel):
    node_ids: list[UUID]
    tag_ids: list[UUID]
    action: Literal["add", "remove", "replace"]


class BulkTagResponse(BaseModel):
    updated: int


class BulkAssignTypeRequest(BaseModel):
    node_ids: list[UUID]
    document_type_id: UUID


class BulkAssignTypeResponse(BaseModel):
    updated: int


# ---------------------------------------------------------------------------
# POST /nodes/bulk/move
# ---------------------------------------------------------------------------

@router.post("/bulk/move", status_code=200)
async def bulk_move_nodes(
    body: BulkMoveRequest,
    user: require_scopes(scopes.NODE_MOVE),
    db_session: AsyncSession = Depends(get_db),
) -> BulkMoveResponse:
    """Move multiple nodes to a target folder.

    Validates NODE_MOVE on each source and NODE_UPDATE on the target.
    Each node is processed independently — failures are collected rather
    than aborting the entire batch.
    """
    if not body.node_ids:
        return BulkMoveResponse(moved=0, failed=0)

    # Validate target once
    if not await dbapi_common.has_node_perm(
        db_session,
        node_id=body.target_folder_id,
        codename=scopes.NODE_UPDATE,
        user_id=user.id,
    ):
        raise exc.HTTP403Forbidden()

    moved = 0
    failed = 0
    errors: list[str] = []

    async with AsyncAuditContext(db_session, user_id=user.id, username=user.username):
        for node_id in body.node_ids:
            # Use a SAVEPOINT so a single failure doesn't kill the session
            async with db_session.begin_nested():
                try:
                    if not await dbapi_common.has_node_perm(
                        db_session,
                        node_id=node_id,
                        codename=scopes.NODE_MOVE,
                        user_id=user.id,
                    ):
                        failed += 1
                        errors.append(f"{node_id}: permission denied")
                        continue

                    count = await nodes_dbapi.move_nodes(
                        db_session,
                        source_ids=[node_id],
                        target_id=body.target_folder_id,
                    )
                    if count > 0:
                        moved += 1
                    else:
                        failed += 1
                        errors.append(f"{node_id}: not found or already at target")
                except (EntityNotFound, NoResultFound):
                    failed += 1
                    errors.append(f"{node_id}: not found")
                except IntegrityError as e:
                    failed += 1
                    errors.append(f"{node_id}: integrity error — {e.orig}")
                except Exception as e:
                    failed += 1
                    errors.append(f"{node_id}: {e}")

    await db_session.commit()
    return BulkMoveResponse(moved=moved, failed=failed, errors=errors)


# ---------------------------------------------------------------------------
# POST /nodes/bulk/delete
# ---------------------------------------------------------------------------

@router.post("/bulk/delete", status_code=200)
async def bulk_delete_nodes(
    body: BulkDeleteRequest,
    user: require_scopes(scopes.NODE_DELETE),
    db_session: AsyncSession = Depends(get_db),
) -> BulkDeleteResponse:
    """Soft-delete (hard-delete) multiple nodes.

    Validates NODE_DELETE on each node individually.  Each node is processed
    under its own savepoint so a single failure does not abort others.
    """
    if not body.node_ids:
        return BulkDeleteResponse(deleted=0, failed=0)

    deleted = 0
    failed = 0

    async with AsyncAuditContext(db_session, user_id=user.id, username=user.username):
        for node_id in body.node_ids:
            async with db_session.begin_nested():
                try:
                    if not await dbapi_common.has_node_perm(
                        db_session,
                        node_id=node_id,
                        codename=scopes.NODE_DELETE,
                        user_id=user.id,
                    ):
                        failed += 1
                        continue

                    error = await nodes_dbapi.delete_nodes(
                        db_session, node_ids=[node_id], user_id=user.id
                    )
                    if error:
                        failed += 1
                    else:
                        deleted += 1
                except Exception:
                    failed += 1

    await db_session.commit()
    return BulkDeleteResponse(deleted=deleted, failed=failed)


# ---------------------------------------------------------------------------
# POST /nodes/bulk/tag
# ---------------------------------------------------------------------------

@router.post("/bulk/tag", status_code=200)
async def bulk_tag_nodes(
    body: BulkTagRequest,
    user: require_scopes(scopes.NODE_UPDATE),
    db_session: AsyncSession = Depends(get_db),
) -> BulkTagResponse:
    """Add, remove, or replace tags on multiple nodes.

    `action` is one of:
    - `add`     — append supplied tag_ids (no-op for already-present tags)
    - `remove`  — dissociate supplied tag_ids
    - `replace` — replace all existing tags with supplied tag_ids
    """
    if not body.node_ids or not body.tag_ids:
        return BulkTagResponse(updated=0)

    # Resolve tag ORM objects once
    tag_stmt = select(orm.Tag).where(orm.Tag.id.in_(body.tag_ids))
    tags: list[orm.Tag] = list((await db_session.scalars(tag_stmt)).all())

    if not tags and body.action in ("add", "replace"):
        raise HTTPException(status_code=404, detail="None of the supplied tag_ids found")

    updated = 0

    async with AsyncAuditContext(db_session, user_id=user.id, username=user.username):
        for node_id in body.node_ids:
            async with db_session.begin_nested():
                try:
                    if not await dbapi_common.has_node_perm(
                        db_session,
                        node_id=node_id,
                        codename=scopes.NODE_UPDATE,
                        user_id=user.id,
                    ):
                        continue

                    node_stmt = select(orm.Node).where(orm.Node.id == node_id)
                    node = (await db_session.scalars(node_stmt)).one_or_none()
                    if node is None:
                        continue

                    # Ensure tags relationship is loaded
                    await db_session.refresh(node, ["tags"])

                    if body.action == "replace":
                        node.tags = tags
                    elif body.action == "add":
                        existing_ids = {t.id for t in node.tags}
                        node.tags = list(node.tags) + [t for t in tags if t.id not in existing_ids]
                    else:  # remove
                        remove_ids = {t.id for t in tags}
                        node.tags = [t for t in node.tags if t.id not in remove_ids]

                    await db_session.flush()
                    updated += 1
                except Exception as e:
                    logger.warning(f"bulk_tag_nodes: node {node_id} failed: {e}")

    await db_session.commit()
    return BulkTagResponse(updated=updated)


# ---------------------------------------------------------------------------
# POST /nodes/bulk/assign-document-type
# ---------------------------------------------------------------------------

@router.post("/bulk/assign-document-type", status_code=200)
async def bulk_assign_document_type(
    body: BulkAssignTypeRequest,
    user: require_scopes(scopes.NODE_UPDATE),
    db_session: AsyncSession = Depends(get_db),
) -> BulkAssignTypeResponse:
    """Set document_type_id on multiple document nodes.

    Silently skips folder nodes.  Validates NODE_UPDATE on each node.
    """
    if not body.node_ids:
        return BulkAssignTypeResponse(updated=0)

    updated = 0

    async with AsyncAuditContext(db_session, user_id=user.id, username=user.username):
        for node_id in body.node_ids:
            async with db_session.begin_nested():
                try:
                    if not await dbapi_common.has_node_perm(
                        db_session,
                        node_id=node_id,
                        codename=scopes.NODE_UPDATE,
                        user_id=user.id,
                    ):
                        continue

                    # Only update document nodes (Document table has document_type_id)
                    result = await db_session.execute(
                        update(orm.Document)
                        .where(orm.Document.id == node_id)
                        .values(document_type_id=body.document_type_id)
                    )
                    if result.rowcount > 0:
                        updated += 1
                except Exception as e:
                    logger.warning(f"bulk_assign_document_type: node {node_id} failed: {e}")

    await db_session.commit()
    return BulkAssignTypeResponse(updated=updated)


# ---------------------------------------------------------------------------
# POST /nodes/bulk-export  &  GET /nodes/bulk-export/{job_id}
# ---------------------------------------------------------------------------

class BulkExportRequest(BaseModel):
    document_ids: list[UUID]
    include_metadata: bool = True
    include_original: bool = True


class BulkExportResponse(BaseModel):
    job_id: str
    status_url: str


class BulkExportStatusResponse(BaseModel):
    status: str  # queued | processing | complete | failed
    progress: float  # 0.0 – 1.0
    download_url: str | None = None
    error: str | None = None


@router.post("/bulk-export", status_code=202, response_model=BulkExportResponse)
async def start_bulk_export(
    body: BulkExportRequest,
    user: require_scopes(scopes.NODE_VIEW),
    db_session: AsyncSession = Depends(get_db),
) -> BulkExportResponse:
    """Enqueue a background ZIP export for the given document IDs.

    Returns immediately with a job_id; poll GET /nodes/bulk-export/{job_id}
    for status and the eventual download URL.

    Required scope: `node.view`
    """
    if not body.document_ids:
        raise HTTPException(status_code=400, detail="document_ids must not be empty")

    # Verify the caller has VIEW permission on every requested document
    for doc_id in body.document_ids:
        if not await dbapi_common.has_node_perm(
            db_session,
            node_id=doc_id,
            codename=scopes.NODE_VIEW,
            user_id=user.id,
        ):
            raise exc.HTTP403Forbidden()

    import uuid as _uuid
    job_id = str(_uuid.uuid4())

    from papermerge.core.tasks import send_task
    send_task(
        "darchiva.export.bulk_export",
        kwargs={
            "job_id": job_id,
            "document_ids": [str(d) for d in body.document_ids],
            "include_metadata": body.include_metadata,
            "include_original": body.include_original,
        },
    )

    return BulkExportResponse(
        job_id=job_id,
        status_url=f"/api/v1/nodes/bulk-export/{job_id}",
    )


@router.get("/bulk-export/{job_id}", response_model=BulkExportStatusResponse)
async def get_bulk_export_status(
    job_id: str,
    user: require_scopes(scopes.NODE_VIEW),
) -> BulkExportStatusResponse:
    """Poll the status of a bulk-export job.

    Returns status, progress (0.0–1.0), and download_url once complete.
    """
    try:
        from papermerge.core.config import get_settings as _get_settings
        import redis as _redis

        cfg = _get_settings()
        redis_url = getattr(cfg, "redis_url", None) or getattr(cfg, "pm_redis_url", None)
        if not redis_url:
            # Redis unavailable — return a polite unknown
            return BulkExportStatusResponse(status="queued", progress=0.0)

        r = _redis.from_url(redis_url, decode_responses=True)
        data = r.hgetall(f"bulk_export:{job_id}")
    except Exception as e:
        logger.warning(f"bulk_export status: Redis error for job {job_id}: {e}")
        return BulkExportStatusResponse(status="queued", progress=0.0)

    if not data:
        # Job not yet picked up by worker, or job_id unknown
        return BulkExportStatusResponse(status="queued", progress=0.0)

    return BulkExportStatusResponse(
        status=data.get("status", "queued"),
        progress=float(data.get("progress", 0.0)),
        download_url=data.get("download_url") or None,
        error=data.get("error") or None,
    )

# WIRING NEEDED: add "darchiva.documents.batch_operation" to celery_app.py task routes
import asyncio
import logging
import uuid

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="darchiva.documents.batch_operation", bind=True)
def batch_operation_task(
    self,
    operation: str,
    document_ids: list,
    params: dict,
    user_id: str,
):
    """
    Handle large batch document operations asynchronously.

    Called when document_ids >= 50. Dispatches to the same underlying
    dbapi functions as the sync path in POST /documents/batch.

    operation: "tag" | "move" | "classify" | "delete" | "export"
    params:
      tag:      {tag_ids: [str], action: "add"|"remove"|"set"}
      move:     {destination_folder_id: str}
      classify: {document_type_id: str}
      delete:   {}
      export:   {job_id: str}
    """
    logger.info(
        f"batch_operation_task: op={operation} "
        f"docs={len(document_ids)} user={user_id[:8]}"
    )

    async def _run():
        from papermerge.core.db.engine import get_async_session_maker
        from papermerge.core import orm
        from papermerge.core.features.nodes.db import api as nodes_dbapi
        from sqlalchemy import update as _update, select as _select

        async_session = get_async_session_maker()
        async with async_session() as session:
            uid = uuid.UUID(user_id)
            doc_uuids = [uuid.UUID(d) for d in document_ids]

            if operation == "delete":
                error = await nodes_dbapi.delete_nodes(
                    session, node_ids=doc_uuids, user_id=uid
                )
                await session.commit()
                if error:
                    logger.error(f"batch delete error: {error}")

            elif operation == "move":
                dest = uuid.UUID(params["destination_folder_id"])
                await nodes_dbapi.move_nodes(
                    session, source_ids=doc_uuids, target_id=dest
                )
                await session.commit()

            elif operation == "tag":
                tag_ids = [uuid.UUID(t) for t in params.get("tag_ids", [])]
                action = params.get("action", "add")
                tag_stmt = _select(orm.Tag).where(orm.Tag.id.in_(tag_ids))
                tags = list((await session.scalars(tag_stmt)).all())
                for node_id in doc_uuids:
                    async with session.begin_nested():
                        try:
                            node_stmt = _select(orm.Node).where(orm.Node.id == node_id)
                            node = (await session.scalars(node_stmt)).one_or_none()
                            if node is None:
                                continue
                            await session.refresh(node, ["tags"])
                            if action == "set":
                                node.tags = tags
                            elif action == "add":
                                existing_ids = {t.id for t in node.tags}
                                node.tags = list(node.tags) + [
                                    t for t in tags if t.id not in existing_ids
                                ]
                            else:  # remove
                                remove_ids = {t.id for t in tags}
                                node.tags = [t for t in node.tags if t.id not in remove_ids]
                            await session.flush()
                        except Exception as e:
                            logger.warning(f"batch tag: node {node_id} failed: {e}")
                await session.commit()

            elif operation == "classify":
                dt_id = uuid.UUID(params["document_type_id"])
                await session.execute(
                    _update(orm.Document)
                    .where(orm.Document.id.in_(doc_uuids))
                    .values(document_type_id=dt_id)
                )
                await session.commit()

            elif operation == "export":
                job_id = params.get("job_id", str(uuid.uuid4()))
                from papermerge.core.tasks import send_task
                send_task(
                    "darchiva.export.bulk_export",
                    kwargs={
                        "job_id": job_id,
                        "document_ids": [str(d) for d in document_ids],
                        "include_metadata": params.get("include_metadata", True),
                        "include_original": params.get("include_original", True),
                    },
                )
            else:
                logger.error(f"batch_operation_task: unknown operation '{operation}'")

    asyncio.run(_run())
    logger.info(f"batch_operation_task: completed op={operation}")

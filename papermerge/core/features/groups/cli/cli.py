import uuid

import typer
from rich.console import Console
from sqlalchemy import select

from papermerge.core.db.engine import AsyncSessionLocal
from papermerge.core.features.groups.db import orm
from papermerge.core.features.groups.db import api as dbapi
from papermerge.core.features.groups import schema


app = typer.Typer(help="Groups basic management")

_SYSTEM_UUID = uuid.UUID("00000000-0000-0000-0000-000000000000")


async def _get_superuser_id(session) -> uuid.UUID:
    """Return first superuser ID, falling back to nil UUID."""
    from papermerge.core.features.users.db.orm import User
    result = await session.execute(
        select(User.id).where(User.is_superuser == True).limit(1)
    )
    row = result.scalar_one_or_none()
    return row if row is not None else _SYSTEM_UUID


@app.command()
async def create_admin(exists_ok: bool = True):
    """Creates group named 'admin'"""
    async with AsyncSessionLocal() as db_session:
        created_by = await _get_superuser_id(db_session)
        await dbapi.create_group(db_session, name="admin", created_by=created_by, exists_ok=exists_ok)


@app.command("ls")
async def list_groups():
    """List existing groups and their scopes"""
    async with AsyncSessionLocal() as session:
        stmt = select(orm.Group)
        db_items = (await session.scalars(stmt)).unique()
        result = []
        for item in db_items:
            group = dict(name=item.name, id=item.id)
            result.append(schema.GroupDetails.model_validate(group))

    console = Console()
    for g in result:
        console.print(f"Name={g.name}")

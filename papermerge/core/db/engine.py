import logging
import ssl

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from papermerge.core.config import get_settings

logger = logging.getLogger(__name__)

# Register all ORM models so SQLAlchemy can resolve string-based relationship()
# references before configure_mappers() is called.
import papermerge.core.db.all_models  # noqa: F401, E402

settings = get_settings()

connect_args = {}
if settings.db_ssl:
    # asyncpg requires an SSL context, not sslmode. Use a default context
    # which verifies the server certificate and hostname.
    connect_args["ssl"] = ssl.create_default_context()

# Schema-per-tenant mode sets `search_path` per connection; a pooled connection
# could leak its search_path across requests/tenants. Use NullPool for strict
# isolation in multi-tenant deployments, otherwise pool connections normally.
pool_kwargs = {}
if settings.deployment_mode == "multi_tenant":
    pool_kwargs["poolclass"] = NullPool
else:
    pool_kwargs["pool_pre_ping"] = True

engine = create_async_engine(
    settings.async_db_url,
    connect_args=connect_args,
    **pool_kwargs,
)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


def _make_sync_url(async_url: str) -> str:
    return async_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)


_sync_connect_args = {}
if settings.db_ssl:
    _sync_connect_args["sslmode"] = "require"

_sync_engine = create_engine(
    _make_sync_url(settings.async_db_url),
    connect_args=_sync_connect_args,
    **pool_kwargs,
)
Session = sessionmaker(_sync_engine, expire_on_commit=False)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


# Alias for consistency with scanner router and other features
get_session = get_db


def get_engine():
    return engine


def get_async_session_maker():
    return AsyncSessionLocal


# Expose sync engine for tasks that need it
sync_engine = _sync_engine

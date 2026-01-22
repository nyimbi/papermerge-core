import logging
import ssl

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from papermerge.core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

connect_args = {}
if settings.db_ssl:
    # asyncpg requires an SSL context, not sslmode
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    connect_args["ssl"] = ssl_context

engine = create_async_engine(
    settings.async_db_url,
    poolclass=NullPool,
    connect_args=connect_args
)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


# Alias for consistency with scanner router and other features
get_session = get_db


def get_engine():
    return engine

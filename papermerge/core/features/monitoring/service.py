import logging
import asyncio
from sqlalchemy import text
from redis import Redis
from papermerge.core.db.engine import AsyncSessionLocal
from papermerge.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

async def _check_db_async() -> bool:
	async with AsyncSessionLocal() as session:
		await session.execute(text("SELECT 1"))
	return True

def check_db_status() -> bool:
    try:
        loop = asyncio.new_event_loop()
        return loop.run_until_complete(_check_db_async())
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return False

def check_redis_status() -> bool:
    try:
        r = Redis.from_url(settings.redis_url)
        return r.ping()
    except Exception as e:
        logger.error(f"Redis health check failed: {e}")
        return False

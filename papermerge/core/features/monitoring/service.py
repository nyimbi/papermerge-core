import logging
from sqlalchemy import text
from redis import Redis
from papermerge.core.db.engine import SessionLocal
from papermerge.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

def check_db_status() -> bool:
    try:
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
        return True
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

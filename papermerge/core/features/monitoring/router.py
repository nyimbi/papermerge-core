from fastapi import APIRouter, Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from papermerge.core.features.monitoring.service import check_db_status, check_redis_status

router = APIRouter(
    prefix="/monitoring",
    tags=["monitoring"]
)

@router.get("/health")
def health_check():
    db_status = check_db_status()
    redis_status = check_redis_status()
    
    status = "ok" if db_status and redis_status else "error"
    
    return {
        "status": status,
        "details": {
            "database": "up" if db_status else "down",
            "redis": "up" if redis_status else "down"
        }
    }

@router.get("/metrics")
def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

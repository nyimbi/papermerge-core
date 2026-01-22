# (c) Copyright Datacraft, 2026
"""Dashboard API endpoints."""
from fastapi import APIRouter

from papermerge.core.features.auth.dependencies import require_scopes
from papermerge.core.features.auth import scopes

router = APIRouter(
	prefix="/dashboard",
	tags=["dashboard"],
)


@router.get("/stats")
async def get_dashboard_stats(
	user: require_scopes(scopes.NODE_VIEW),
) -> dict:
	"""Get dashboard statistics for current user."""
	return {
		"totalDocuments": 0,
		"documentsThisMonth": 0,
		"pendingTasks": 0,
		"storageUsedBytes": 0,
		"storageQuotaBytes": 10737418240,  # 10 GB
		"activeWorkflows": 0,
		"ocrProcessed": 0,
	}


@router.get("/activity")
async def get_recent_activity(
	user: require_scopes(scopes.NODE_VIEW),
	limit: int = 10,
) -> dict:
	"""Get recent activity for current user."""
	return {
		"items": [],
		"total": 0,
	}

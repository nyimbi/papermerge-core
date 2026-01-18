# (c) Copyright Datacraft, 2026
"""Feature flags API router."""
import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.engine import get_db
from papermerge.core.config.features import (
	FeatureResponse,
	FeatureSet,
	get_feature_config,
)

router = APIRouter(
	prefix="/features",
	tags=["features"],
)

logger = logging.getLogger(__name__)


@router.get("/")
async def get_features(
	request: Request,
	db_session: AsyncSession = Depends(get_db),
) -> FeatureResponse:
	"""
	Get available features for the current tenant.

	Returns the combined feature flags from system configuration
	and tenant-specific settings.
	"""
	# Get system features
	feature_set = FeatureSet.from_config()
	features = feature_set.to_dict()

	# Get tenant context if available
	tenant_context = getattr(request.state, "tenant_context", None)

	tier = "free"
	limits: dict[str, Any] = {}

	if tenant_context:
		# Merge tenant-specific features
		if tenant_context.features:
			features.update(tenant_context.features)

		tier = tenant_context.plan or "free"

		# Get tenant limits from database
		from papermerge.core.features.tenants.db.orm import Tenant
		tenant = await db_session.get(Tenant, tenant_context.tenant_id)
		if tenant:
			limits = {
				"max_users": tenant.max_users,
				"max_storage_gb": tenant.max_storage_gb,
			}

	return FeatureResponse(
		features=features,
		tier=tier,
		limits=limits,
	)


@router.get("/check/{feature_name}")
async def check_feature(
	feature_name: str,
	request: Request,
) -> dict[str, bool]:
	"""
	Check if a specific feature is enabled.

	Uses both system configuration and tenant context.
	"""
	from papermerge.core.tenancy import get_feature_flags

	# Get tenant context
	tenant_context = getattr(request.state, "tenant_context", None)

	if tenant_context:
		flags = get_feature_flags(
			tenant_id=tenant_context.tenant_id,
			tenant_slug=tenant_context.tenant_slug,
			tenant_features=tenant_context.features,
			plan=tenant_context.plan,
		)
		enabled = flags.is_enabled(feature_name)
	else:
		# Fall back to system config
		from papermerge.core.config.features import is_feature_enabled
		enabled = is_feature_enabled(feature_name)

	return {"feature": feature_name, "enabled": enabled}

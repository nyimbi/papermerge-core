# (c) Copyright Datacraft, 2026
"""Tenant management API endpoints."""
import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.engine import get_db
from papermerge.core.features.auth.dependencies import require_scopes
from papermerge.core.features.auth import scopes
from . import schema
from .db.orm import (
	Tenant, TenantBranding, TenantSettings,
	TenantStorageConfig, TenantAIConfig, TenantSubscription
)

router = APIRouter(
	prefix="/tenants",
	tags=["tenants"],
)

logger = logging.getLogger(__name__)


@router.get("/current")
async def get_current_tenant(
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
) -> schema.TenantDetail:
	"""Get current user's tenant details."""
	tenant = await db_session.get(Tenant, user.tenant_id)
	if not tenant:
		raise HTTPException(status_code=404, detail="Tenant not found")

	result = schema.TenantDetail(
		id=tenant.id,
		name=tenant.name,
		slug=tenant.slug,
		status=tenant.status,
		contact_email=tenant.contact_email,
		contact_phone=tenant.contact_phone,
		billing_email=tenant.billing_email,
		stripe_customer_id=tenant.stripe_customer_id,
		max_users=tenant.max_users,
		max_storage_gb=tenant.max_storage_gb,
		trial_ends_at=tenant.trial_ends_at,
		created_at=tenant.created_at,
		updated_at=tenant.updated_at,
	)

	if tenant.branding:
		result.branding = schema.TenantBrandingInfo.model_validate(tenant.branding)
	if tenant.settings:
		result.settings = schema.TenantSettingsInfo.model_validate(tenant.settings)

	return result


@router.patch("/current")
async def update_current_tenant(
	updates: schema.TenantUpdate,
	user: require_scopes(scopes.TENANT_ADMIN),
	db_session: AsyncSession = Depends(get_db),
) -> schema.TenantDetail:
	"""Update current tenant."""
	tenant = await db_session.get(Tenant, user.tenant_id)
	if not tenant:
		raise HTTPException(status_code=404, detail="Tenant not found")

	update_data = updates.model_dump(exclude_unset=True)
	for field, value in update_data.items():
		setattr(tenant, field, value)

	await db_session.commit()
	await db_session.refresh(tenant)

	return schema.TenantDetail(
		id=tenant.id,
		name=tenant.name,
		slug=tenant.slug,
		status=tenant.status,
		contact_email=tenant.contact_email,
		contact_phone=tenant.contact_phone,
		billing_email=tenant.billing_email,
		stripe_customer_id=tenant.stripe_customer_id,
		max_users=tenant.max_users,
		max_storage_gb=tenant.max_storage_gb,
		trial_ends_at=tenant.trial_ends_at,
		created_at=tenant.created_at,
		updated_at=tenant.updated_at,
	)


@router.get("/current/branding")
async def get_tenant_branding(
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
) -> schema.TenantBrandingInfo:
	"""Get tenant branding settings."""
	stmt = select(TenantBranding).where(TenantBranding.tenant_id == user.tenant_id)
	result = await db_session.execute(stmt)
	branding = result.scalar()

	if branding:
		return schema.TenantBrandingInfo.model_validate(branding)

	return schema.TenantBrandingInfo()


@router.patch("/current/branding")
async def update_tenant_branding(
	updates: schema.BrandingUpdate,
	user: require_scopes(scopes.TENANT_ADMIN),
	db_session: AsyncSession = Depends(get_db),
) -> schema.TenantBrandingInfo:
	"""Update tenant branding."""
	stmt = select(TenantBranding).where(TenantBranding.tenant_id == user.tenant_id)
	result = await db_session.execute(stmt)
	branding = result.scalar()

	if not branding:
		branding = TenantBranding(tenant_id=user.tenant_id)
		db_session.add(branding)

	update_data = updates.model_dump(exclude_unset=True)
	for field, value in update_data.items():
		setattr(branding, field, value)

	await db_session.commit()
	await db_session.refresh(branding)

	return schema.TenantBrandingInfo.model_validate(branding)


@router.get("/current/settings")
async def get_tenant_settings(
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
) -> schema.TenantSettingsInfo:
	"""Get tenant settings."""
	stmt = select(TenantSettings).where(TenantSettings.tenant_id == user.tenant_id)
	result = await db_session.execute(stmt)
	settings = result.scalar()

	if settings:
		return schema.TenantSettingsInfo.model_validate(settings)

	return schema.TenantSettingsInfo()


@router.patch("/current/settings")
async def update_tenant_settings(
	updates: schema.SettingsUpdate,
	user: require_scopes(scopes.TENANT_ADMIN),
	db_session: AsyncSession = Depends(get_db),
) -> schema.TenantSettingsInfo:
	"""Update tenant settings."""
	stmt = select(TenantSettings).where(TenantSettings.tenant_id == user.tenant_id)
	result = await db_session.execute(stmt)
	settings = result.scalar()

	if not settings:
		settings = TenantSettings(tenant_id=user.tenant_id)
		db_session.add(settings)

	update_data = updates.model_dump(exclude_unset=True)
	for field, value in update_data.items():
		setattr(settings, field, value)

	await db_session.commit()
	await db_session.refresh(settings)

	return schema.TenantSettingsInfo.model_validate(settings)


@router.get("/current/usage")
async def get_tenant_usage(
	user: require_scopes(scopes.TENANT_ADMIN),
	db_session: AsyncSession = Depends(get_db),
) -> schema.TenantUsageInfo:
	"""Get tenant usage statistics."""
	from papermerge.core.features.users.db.orm import User
	from papermerge.core.features.document.db.orm import Document

	# Count users
	user_count_stmt = select(func.count()).select_from(User).where(
		User.tenant_id == user.tenant_id
	)
	total_users = await db_session.scalar(user_count_stmt) or 0

	# Count documents
	doc_count_stmt = select(func.count()).select_from(Document).where(
		Document.tenant_id == user.tenant_id
	)
	total_documents = await db_session.scalar(doc_count_stmt) or 0

	# Get storage used (sum of document sizes)
	storage_stmt = select(func.coalesce(func.sum(Document.file_size), 0)).where(
		Document.tenant_id == user.tenant_id
	)
	storage_used = await db_session.scalar(storage_stmt) or 0

	# Get tenant settings for quota
	tenant = await db_session.get(Tenant, user.tenant_id)
	storage_quota_bytes = None
	storage_percentage = None

	if tenant and tenant.max_storage_gb:
		storage_quota_bytes = tenant.max_storage_gb * 1024 * 1024 * 1024
		storage_percentage = (storage_used / storage_quota_bytes * 100) if storage_quota_bytes > 0 else 0

	return schema.TenantUsageInfo(
		tenant_id=user.tenant_id,
		total_users=total_users,
		total_documents=total_documents,
		storage_used_bytes=storage_used,
		storage_quota_bytes=storage_quota_bytes,
		storage_percentage=storage_percentage,
	)


# System admin endpoints for managing all tenants
@router.get("/")
async def list_tenants(
	user: require_scopes(scopes.SYSTEM_ADMIN),
	db_session: AsyncSession = Depends(get_db),
	status_filter: str | None = None,
	page: int = 1,
	page_size: int = 50,
) -> schema.TenantListResponse:
	"""List all tenants (system admin only)."""
	offset = (page - 1) * page_size

	conditions = []
	if status_filter:
		conditions.append(Tenant.status == status_filter)

	count_stmt = select(func.count()).select_from(Tenant)
	if conditions:
		count_stmt = count_stmt.where(*conditions)
	total = await db_session.scalar(count_stmt)

	stmt = select(Tenant)
	if conditions:
		stmt = stmt.where(*conditions)
	stmt = stmt.order_by(Tenant.name).offset(offset).limit(page_size)

	result = await db_session.execute(stmt)
	tenants = result.scalars().all()

	return schema.TenantListResponse(
		items=[schema.TenantInfo.model_validate(t) for t in tenants],
		total=total,
		page=page,
		page_size=page_size,
	)


@router.post("/")
async def create_tenant(
	tenant_data: schema.TenantCreate,
	user: require_scopes(scopes.SYSTEM_ADMIN),
	db_session: AsyncSession = Depends(get_db),
) -> schema.TenantDetail:
	"""Create a new tenant (system admin only)."""
	from papermerge.core.config import get_settings

	# Check if slug already exists
	stmt = select(Tenant).where(Tenant.slug == tenant_data.slug)
	result = await db_session.execute(stmt)
	if result.scalar():
		raise HTTPException(status_code=400, detail="Slug already exists")

	# Check if custom domain already exists
	if tenant_data.custom_domain:
		stmt = select(Tenant).where(Tenant.custom_domain == tenant_data.custom_domain)
		result = await db_session.execute(stmt)
		if result.scalar():
			raise HTTPException(status_code=400, detail="Custom domain already exists")

	tenant = Tenant(
		name=tenant_data.name,
		slug=tenant_data.slug,
		plan=tenant_data.plan,
		custom_domain=tenant_data.custom_domain,
		subdomain=tenant_data.subdomain,
		contact_email=tenant_data.contact_email,
		contact_phone=tenant_data.contact_phone,
		billing_email=tenant_data.billing_email,
		max_users=tenant_data.max_users,
		max_storage_gb=tenant_data.max_storage_gb,
		features=tenant_data.features,
	)
	db_session.add(tenant)
	await db_session.flush()

	# Create default branding
	branding = TenantBranding(tenant_id=tenant.id)
	db_session.add(branding)

	# Create default settings
	settings = TenantSettings(tenant_id=tenant.id)
	db_session.add(settings)

	await db_session.commit()
	await db_session.refresh(tenant)

	# Create tenant schema for multi-tenant deployments
	config = get_settings()
	if config.deployment_mode == 'multi_tenant':
		from papermerge.core.tenancy import TenantSchemaManager
		from papermerge.core.db.engine import engine

		schema_manager = TenantSchemaManager(engine)
		await schema_manager.create_tenant_schema(
			db_session=db_session,
			tenant_id=tenant.id,
			tenant_slug=tenant.slug,
		)

	return schema.TenantDetail(
		id=tenant.id,
		name=tenant.name,
		slug=tenant.slug,
		status=tenant.status,
		plan=tenant.plan,
		custom_domain=tenant.custom_domain,
		subdomain=tenant.subdomain,
		contact_email=tenant.contact_email,
		contact_phone=tenant.contact_phone,
		billing_email=tenant.billing_email,
		max_users=tenant.max_users,
		max_storage_gb=tenant.max_storage_gb,
		features=tenant.features,
		created_at=tenant.created_at,
		updated_at=tenant.updated_at,
	)


@router.get("/{tenant_id}")
async def get_tenant(
	tenant_id: UUID,
	user: require_scopes(scopes.SYSTEM_ADMIN),
	db_session: AsyncSession = Depends(get_db),
) -> schema.TenantDetail:
	"""Get tenant details (system admin only)."""
	tenant = await db_session.get(Tenant, tenant_id)
	if not tenant:
		raise HTTPException(status_code=404, detail="Tenant not found")

	result = schema.TenantDetail(
		id=tenant.id,
		name=tenant.name,
		slug=tenant.slug,
		status=tenant.status,
		contact_email=tenant.contact_email,
		contact_phone=tenant.contact_phone,
		billing_email=tenant.billing_email,
		stripe_customer_id=tenant.stripe_customer_id,
		max_users=tenant.max_users,
		max_storage_gb=tenant.max_storage_gb,
		trial_ends_at=tenant.trial_ends_at,
		created_at=tenant.created_at,
		updated_at=tenant.updated_at,
	)

	if tenant.branding:
		result.branding = schema.TenantBrandingInfo.model_validate(tenant.branding)
	if tenant.settings:
		result.settings = schema.TenantSettingsInfo.model_validate(tenant.settings)

	return result


@router.patch("/{tenant_id}")
async def update_tenant(
	tenant_id: UUID,
	updates: schema.TenantUpdate,
	user: require_scopes(scopes.SYSTEM_ADMIN),
	db_session: AsyncSession = Depends(get_db),
) -> schema.TenantDetail:
	"""Update a tenant (system admin only)."""
	tenant = await db_session.get(Tenant, tenant_id)
	if not tenant:
		raise HTTPException(status_code=404, detail="Tenant not found")

	update_data = updates.model_dump(exclude_unset=True)
	for field, value in update_data.items():
		setattr(tenant, field, value)

	await db_session.commit()
	await db_session.refresh(tenant)

	return schema.TenantDetail(
		id=tenant.id,
		name=tenant.name,
		slug=tenant.slug,
		status=tenant.status,
		contact_email=tenant.contact_email,
		contact_phone=tenant.contact_phone,
		billing_email=tenant.billing_email,
		stripe_customer_id=tenant.stripe_customer_id,
		max_users=tenant.max_users,
		max_storage_gb=tenant.max_storage_gb,
		trial_ends_at=tenant.trial_ends_at,
		created_at=tenant.created_at,
		updated_at=tenant.updated_at,
	)


# ==================== Storage Configuration ====================

@router.get("/{tenant_id}/storage")
async def get_tenant_storage_config(
	tenant_id: UUID,
	user: require_scopes(scopes.SYSTEM_ADMIN),
	db_session: AsyncSession = Depends(get_db),
) -> schema.StorageConfigInfo:
	"""Get tenant storage configuration (system admin only)."""
	stmt = select(TenantStorageConfig).where(TenantStorageConfig.tenant_id == tenant_id)
	result = await db_session.execute(stmt)
	config = result.scalar()

	if config:
		return schema.StorageConfigInfo.model_validate(config)
	return schema.StorageConfigInfo()


@router.put("/{tenant_id}/storage")
async def update_tenant_storage_config(
	tenant_id: UUID,
	config_data: schema.StorageConfigUpdate,
	user: require_scopes(scopes.SYSTEM_ADMIN),
	db_session: AsyncSession = Depends(get_db),
) -> schema.StorageConfigInfo:
	"""Update tenant storage configuration (system admin only)."""
	tenant = await db_session.get(Tenant, tenant_id)
	if not tenant:
		raise HTTPException(status_code=404, detail="Tenant not found")

	stmt = select(TenantStorageConfig).where(TenantStorageConfig.tenant_id == tenant_id)
	result = await db_session.execute(stmt)
	config = result.scalar()

	if not config:
		config = TenantStorageConfig(tenant_id=tenant_id)
		db_session.add(config)

	update_data = config_data.model_dump(exclude_unset=True)
	for field, value in update_data.items():
		setattr(config, field, value)

	config.is_verified = False  # Mark as unverified after changes
	await db_session.commit()
	await db_session.refresh(config)

	return schema.StorageConfigInfo.model_validate(config)


@router.post("/{tenant_id}/storage/verify")
async def verify_tenant_storage(
	tenant_id: UUID,
	user: require_scopes(scopes.SYSTEM_ADMIN),
	db_session: AsyncSession = Depends(get_db),
) -> dict:
	"""Verify tenant storage configuration (system admin only)."""
	from papermerge.core.utils.tz import utc_now

	stmt = select(TenantStorageConfig).where(TenantStorageConfig.tenant_id == tenant_id)
	result = await db_session.execute(stmt)
	config = result.scalar()

	if not config:
		raise HTTPException(status_code=404, detail="Storage not configured")

	# Verify based on provider
	try:
		if config.provider == "s3" or config.provider == "linode":
			import boto3
			s3_client = boto3.client(
				's3',
				endpoint_url=config.endpoint_url,
				region_name=config.region,
				aws_access_key_id=config.access_key_id,
				aws_secret_access_key=config.secret_access_key,
			)
			s3_client.head_bucket(Bucket=config.bucket_name)

		config.is_verified = True
		config.last_verified_at = utc_now()
		await db_session.commit()

		return {"success": True, "message": "Storage verified successfully"}
	except Exception as e:
		return {"success": False, "message": str(e)}


# ==================== AI Configuration ====================

@router.get("/{tenant_id}/ai")
async def get_tenant_ai_config(
	tenant_id: UUID,
	user: require_scopes(scopes.SYSTEM_ADMIN),
	db_session: AsyncSession = Depends(get_db),
) -> schema.AIConfigInfo:
	"""Get tenant AI configuration (system admin only)."""
	stmt = select(TenantAIConfig).where(TenantAIConfig.tenant_id == tenant_id)
	result = await db_session.execute(stmt)
	config = result.scalar()

	if config:
		return schema.AIConfigInfo.model_validate(config)
	return schema.AIConfigInfo()


@router.put("/{tenant_id}/ai")
async def update_tenant_ai_config(
	tenant_id: UUID,
	config_data: schema.AIConfigUpdate,
	user: require_scopes(scopes.SYSTEM_ADMIN),
	db_session: AsyncSession = Depends(get_db),
) -> schema.AIConfigInfo:
	"""Update tenant AI configuration (system admin only)."""
	tenant = await db_session.get(Tenant, tenant_id)
	if not tenant:
		raise HTTPException(status_code=404, detail="Tenant not found")

	stmt = select(TenantAIConfig).where(TenantAIConfig.tenant_id == tenant_id)
	result = await db_session.execute(stmt)
	config = result.scalar()

	if not config:
		config = TenantAIConfig(tenant_id=tenant_id)
		db_session.add(config)

	update_data = config_data.model_dump(exclude_unset=True)
	for field, value in update_data.items():
		setattr(config, field, value)

	await db_session.commit()
	await db_session.refresh(config)

	return schema.AIConfigInfo.model_validate(config)


@router.post("/{tenant_id}/ai/reset-tokens")
async def reset_tenant_ai_tokens(
	tenant_id: UUID,
	user: require_scopes(scopes.SYSTEM_ADMIN),
	db_session: AsyncSession = Depends(get_db),
) -> dict:
	"""Reset tenant AI token usage (system admin only)."""
	stmt = select(TenantAIConfig).where(TenantAIConfig.tenant_id == tenant_id)
	result = await db_session.execute(stmt)
	config = result.scalar()

	if not config:
		raise HTTPException(status_code=404, detail="AI not configured")

	config.tokens_used_this_month = 0
	await db_session.commit()

	return {"success": True, "message": "Token usage reset"}


# ==================== Subscription ====================

@router.get("/{tenant_id}/subscription")
async def get_tenant_subscription(
	tenant_id: UUID,
	user: require_scopes(scopes.SYSTEM_ADMIN),
	db_session: AsyncSession = Depends(get_db),
) -> schema.SubscriptionInfo:
	"""Get tenant subscription (system admin only)."""
	stmt = select(TenantSubscription).where(TenantSubscription.tenant_id == tenant_id)
	result = await db_session.execute(stmt)
	subscription = result.scalar()

	if subscription:
		return schema.SubscriptionInfo.model_validate(subscription)
	return schema.SubscriptionInfo()


@router.put("/{tenant_id}/subscription")
async def update_tenant_subscription(
	tenant_id: UUID,
	sub_data: schema.SubscriptionUpdate,
	user: require_scopes(scopes.SYSTEM_ADMIN),
	db_session: AsyncSession = Depends(get_db),
) -> schema.SubscriptionInfo:
	"""Update tenant subscription (system admin only)."""
	tenant = await db_session.get(Tenant, tenant_id)
	if not tenant:
		raise HTTPException(status_code=404, detail="Tenant not found")

	stmt = select(TenantSubscription).where(TenantSubscription.tenant_id == tenant_id)
	result = await db_session.execute(stmt)
	subscription = result.scalar()

	if not subscription:
		subscription = TenantSubscription(tenant_id=tenant_id)
		db_session.add(subscription)

	update_data = sub_data.model_dump(exclude_unset=True)
	for field, value in update_data.items():
		setattr(subscription, field, value)

	# Sync limits to tenant
	if sub_data.max_users is not None:
		tenant.max_users = sub_data.max_users
	if sub_data.max_storage_gb is not None:
		tenant.max_storage_gb = sub_data.max_storage_gb

	await db_session.commit()
	await db_session.refresh(subscription)

	return schema.SubscriptionInfo.model_validate(subscription)


# ==================== Full Tenant Provisioning ====================

@router.post("/provision")
async def provision_tenant(
	provision_data: schema.TenantProvisionRequest,
	user: require_scopes(scopes.SYSTEM_ADMIN),
	db_session: AsyncSession = Depends(get_db),
) -> schema.TenantProvisionResponse:
	"""Provision a complete new tenant with storage, AI, and admin user (system admin only)."""
	import secrets
	from papermerge.core.features.users.db.orm import User
	from papermerge.core.utils.security import hash_password

	# Check slug uniqueness
	stmt = select(Tenant).where(Tenant.slug == provision_data.slug)
	if await db_session.scalar(stmt):
		raise HTTPException(status_code=400, detail="Slug already exists")

	# Create tenant
	tenant = Tenant(
		name=provision_data.name,
		slug=provision_data.slug,
		contact_email=provision_data.contact_email,
		billing_email=provision_data.billing_email or provision_data.contact_email,
		plan=provision_data.plan,
		max_users=provision_data.max_users,
		max_storage_gb=provision_data.max_storage_gb,
	)
	db_session.add(tenant)
	await db_session.flush()

	# Create branding
	branding = TenantBranding(tenant_id=tenant.id)
	db_session.add(branding)

	# Create settings
	settings = TenantSettings(
		tenant_id=tenant.id,
		storage_quota_gb=provision_data.max_storage_gb,
		ai_features_enabled=provision_data.ai_monthly_tokens is not None,
	)
	db_session.add(settings)

	# Create storage config
	storage_configured = False
	if provision_data.storage_provider != "local":
		storage = TenantStorageConfig(
			tenant_id=tenant.id,
			provider=provision_data.storage_provider,
			bucket_name=provision_data.storage_bucket or f"darchiva-{tenant.slug}",
			region=provision_data.storage_region,
			endpoint_url=provision_data.storage_endpoint,
		)
		db_session.add(storage)
		storage_configured = True

	# Create AI config
	ai_configured = False
	if provision_data.ai_monthly_tokens:
		ai_config = TenantAIConfig(
			tenant_id=tenant.id,
			provider=provision_data.ai_provider,
			monthly_token_limit=provision_data.ai_monthly_tokens,
		)
		db_session.add(ai_config)
		ai_configured = True

	# Create subscription
	subscription = TenantSubscription(
		tenant_id=tenant.id,
		plan=provision_data.plan,
		billing_cycle=provision_data.billing_cycle,
		max_users=provision_data.max_users,
		max_storage_gb=provision_data.max_storage_gb,
		ai_tokens_per_month=provision_data.ai_monthly_tokens,
	)
	db_session.add(subscription)

	# Create admin user
	admin_user = None
	setup_link = None
	password = provision_data.admin_password or secrets.token_urlsafe(16)

	admin_user = User(
		tenant_id=tenant.id,
		email=provision_data.admin_email,
		username=provision_data.admin_email.split("@")[0],
		password_hash=hash_password(password),
		is_active=True,
		is_superuser=False,  # Tenant admin, not system admin
	)
	db_session.add(admin_user)
	await db_session.flush()

	if not provision_data.admin_password:
		# Generate setup link (would be emailed in production)
		setup_token = secrets.token_urlsafe(32)
		setup_link = f"/setup?token={setup_token}&tenant={tenant.slug}"

	await db_session.commit()

	return schema.TenantProvisionResponse(
		tenant=schema.TenantInfo.model_validate(tenant),
		storage_configured=storage_configured,
		ai_configured=ai_configured,
		admin_user_id=admin_user.id if admin_user else None,
		setup_link=setup_link,
	)

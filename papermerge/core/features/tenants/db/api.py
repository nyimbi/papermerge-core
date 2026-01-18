# (c) Copyright Datacraft, 2026
"""Tenant database API."""
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import Session

from .orm import Tenant, TenantBranding, TenantSettings


async def get_tenant(db: Session, tenant_id: UUID) -> Tenant | None:
	"""Get tenant by ID."""
	return db.get(Tenant, tenant_id)


async def get_tenant_by_slug(db: Session, slug: str) -> Tenant | None:
	"""Get tenant by slug."""
	stmt = select(Tenant).where(Tenant.slug == slug)
	return db.scalar(stmt)


async def create_tenant(
	db: Session,
	name: str,
	slug: str,
	contact_email: str | None = None,
) -> Tenant:
	"""Create a new tenant with default branding and settings."""
	tenant = Tenant(
		name=name,
		slug=slug,
		contact_email=contact_email,
	)
	db.add(tenant)
	db.flush()

	# Create default branding
	branding = TenantBranding(tenant_id=tenant.id)
	db.add(branding)

	# Create default settings
	settings = TenantSettings(tenant_id=tenant.id)
	db.add(settings)

	db.commit()
	db.refresh(tenant)
	return tenant


async def update_tenant(
	db: Session,
	tenant_id: UUID,
	**kwargs
) -> Tenant | None:
	"""Update tenant."""
	tenant = db.get(Tenant, tenant_id)
	if not tenant:
		return None

	for key, value in kwargs.items():
		if hasattr(tenant, key):
			setattr(tenant, key, value)

	db.commit()
	db.refresh(tenant)
	return tenant


async def get_branding(db: Session, tenant_id: UUID) -> TenantBranding | None:
	"""Get tenant branding."""
	stmt = select(TenantBranding).where(TenantBranding.tenant_id == tenant_id)
	return db.scalar(stmt)


async def update_branding(
	db: Session,
	tenant_id: UUID,
	**kwargs
) -> TenantBranding | None:
	"""Update tenant branding."""
	branding = await get_branding(db, tenant_id)
	if not branding:
		return None

	for key, value in kwargs.items():
		if hasattr(branding, key):
			setattr(branding, key, value)

	db.commit()
	db.refresh(branding)
	return branding


async def get_settings(db: Session, tenant_id: UUID) -> TenantSettings | None:
	"""Get tenant settings."""
	stmt = select(TenantSettings).where(TenantSettings.tenant_id == tenant_id)
	return db.scalar(stmt)


async def update_settings(
	db: Session,
	tenant_id: UUID,
	**kwargs
) -> TenantSettings | None:
	"""Update tenant settings."""
	settings = await get_settings(db, tenant_id)
	if not settings:
		return None

	for key, value in kwargs.items():
		if hasattr(settings, key):
			setattr(settings, key, value)

	db.commit()
	db.refresh(settings)
	return settings

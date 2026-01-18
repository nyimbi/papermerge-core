# (c) Copyright Datacraft, 2026
"""
Tenant middleware for FastAPI.

Resolves tenant from request and sets the tenant context for the request lifecycle.
"""
import logging
from typing import Callable, Awaitable
from uuid import UUID

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .context import TenantContext, set_tenant_context, create_tenant_context

logger = logging.getLogger(__name__)


class TenantResolutionStrategy:
	"""Base class for tenant resolution strategies."""

	async def resolve(
		self, request: Request, db_session: AsyncSession
	) -> TenantContext | None:
		"""Resolve tenant from request. Returns None if no tenant found."""
		raise NotImplementedError


class HostHeaderStrategy(TenantResolutionStrategy):
	"""Resolve tenant from Host header (subdomain or custom domain)."""

	def __init__(self, base_domain: str = "localhost"):
		self.base_domain = base_domain

	async def resolve(
		self, request: Request, db_session: AsyncSession
	) -> TenantContext | None:
		from papermerge.core.features.tenants.db.orm import Tenant

		host = request.headers.get("host", "")
		# Remove port if present
		host = host.split(":")[0]

		# Check for subdomain: <tenant>.base_domain
		if host.endswith(f".{self.base_domain}"):
			slug = host.replace(f".{self.base_domain}", "")
			stmt = select(Tenant).where(Tenant.slug == slug)
			result = await db_session.execute(stmt)
			tenant = result.scalar()

			if tenant:
				return create_tenant_context(
					tenant_id=tenant.id,
					tenant_slug=tenant.slug,
					domain=host,
					plan=tenant.status,
				)

		# Check for custom domain
		stmt = select(Tenant).where(Tenant.custom_domain == host)
		result = await db_session.execute(stmt)
		tenant = result.scalar()

		if tenant:
			return create_tenant_context(
				tenant_id=tenant.id,
				tenant_slug=tenant.slug,
				domain=host,
				plan=tenant.status,
			)

		return None


class HeaderStrategy(TenantResolutionStrategy):
	"""Resolve tenant from X-Tenant-ID or X-Tenant-Slug header."""

	def __init__(
		self,
		id_header: str = "X-Tenant-ID",
		slug_header: str = "X-Tenant-Slug",
	):
		self.id_header = id_header
		self.slug_header = slug_header

	async def resolve(
		self, request: Request, db_session: AsyncSession
	) -> TenantContext | None:
		from papermerge.core.features.tenants.db.orm import Tenant

		# Try tenant ID first
		tenant_id = request.headers.get(self.id_header)
		if tenant_id:
			try:
				uuid = UUID(tenant_id)
				tenant = await db_session.get(Tenant, uuid)
				if tenant:
					return create_tenant_context(
						tenant_id=tenant.id,
						tenant_slug=tenant.slug,
						plan=tenant.status,
					)
			except ValueError:
				logger.warning(f"Invalid tenant ID in header: {tenant_id}")

		# Try tenant slug
		slug = request.headers.get(self.slug_header)
		if slug:
			stmt = select(Tenant).where(Tenant.slug == slug)
			result = await db_session.execute(stmt)
			tenant = result.scalar()

			if tenant:
				return create_tenant_context(
					tenant_id=tenant.id,
					tenant_slug=tenant.slug,
					plan=tenant.status,
				)

		return None


class PathPrefixStrategy(TenantResolutionStrategy):
	"""Resolve tenant from URL path prefix: /tenant/<slug>/..."""

	def __init__(self, prefix: str = "/tenant"):
		self.prefix = prefix

	async def resolve(
		self, request: Request, db_session: AsyncSession
	) -> TenantContext | None:
		from papermerge.core.features.tenants.db.orm import Tenant

		path = request.url.path
		if not path.startswith(f"{self.prefix}/"):
			return None

		# Extract slug from path
		parts = path[len(self.prefix) + 1:].split("/")
		if not parts:
			return None

		slug = parts[0]
		stmt = select(Tenant).where(Tenant.slug == slug)
		result = await db_session.execute(stmt)
		tenant = result.scalar()

		if tenant:
			return create_tenant_context(
				tenant_id=tenant.id,
				tenant_slug=tenant.slug,
				plan=tenant.status,
			)

		return None


class TokenClaimStrategy(TenantResolutionStrategy):
	"""Resolve tenant from JWT token claims."""

	def __init__(self, claim_name: str = "tenant_id"):
		self.claim_name = claim_name

	async def resolve(
		self, request: Request, db_session: AsyncSession
	) -> TenantContext | None:
		from papermerge.core.features.tenants.db.orm import Tenant

		# Get user from request state (set by auth middleware)
		user = getattr(request.state, "user", None)
		if not user:
			return None

		tenant_id = getattr(user, "tenant_id", None)
		if not tenant_id:
			return None

		tenant = await db_session.get(Tenant, tenant_id)
		if tenant:
			return create_tenant_context(
				tenant_id=tenant.id,
				tenant_slug=tenant.slug,
				plan=tenant.status,
			)

		return None


class ChainedStrategy(TenantResolutionStrategy):
	"""Try multiple strategies in order until one succeeds."""

	def __init__(self, strategies: list[TenantResolutionStrategy]):
		self.strategies = strategies

	async def resolve(
		self, request: Request, db_session: AsyncSession
	) -> TenantContext | None:
		for strategy in self.strategies:
			context = await strategy.resolve(request, db_session)
			if context:
				return context
		return None


class TenantMiddleware(BaseHTTPMiddleware):
	"""
	FastAPI middleware for tenant resolution and context management.

	Resolves the tenant from the request using configurable strategies
	and sets the tenant context for the request lifecycle.
	"""

	def __init__(
		self,
		app: ASGIApp,
		strategy: TenantResolutionStrategy | None = None,
		require_tenant: bool = False,
		excluded_paths: list[str] | None = None,
		default_tenant_slug: str | None = None,
	):
		super().__init__(app)
		self.strategy = strategy or ChainedStrategy([
			TokenClaimStrategy(),
			HeaderStrategy(),
			HostHeaderStrategy(),
		])
		self.require_tenant = require_tenant
		self.excluded_paths = excluded_paths or [
			"/health",
			"/ready",
			"/version",
			"/openapi.json",
			"/docs",
			"/redoc",
		]
		self.default_tenant_slug = default_tenant_slug

	async def dispatch(
		self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
	) -> Response:
		# Skip tenant resolution for excluded paths
		if self._is_excluded_path(request.url.path):
			return await call_next(request)

		# Get database session
		from papermerge.core.db.engine import async_session_factory

		async with async_session_factory() as db_session:
			# Resolve tenant
			context = await self.strategy.resolve(request, db_session)

			# Fall back to default tenant if configured
			if context is None and self.default_tenant_slug:
				from papermerge.core.features.tenants.db.orm import Tenant
				stmt = select(Tenant).where(Tenant.slug == self.default_tenant_slug)
				result = await db_session.execute(stmt)
				tenant = result.scalar()
				if tenant:
					context = create_tenant_context(
						tenant_id=tenant.id,
						tenant_slug=tenant.slug,
						plan=tenant.status,
					)

			# Check if tenant is required
			if context is None and self.require_tenant:
				from fastapi.responses import JSONResponse
				return JSONResponse(
					status_code=400,
					content={"detail": "Tenant not found or not specified"},
				)

			# Set tenant context
			token = set_tenant_context(context)
			try:
				# Store context in request state for easy access
				request.state.tenant_context = context
				response = await call_next(request)
				return response
			finally:
				# Reset context after request
				from .context import _tenant_context
				_tenant_context.reset(token)

	def _is_excluded_path(self, path: str) -> bool:
		"""Check if path should be excluded from tenant resolution."""
		for excluded in self.excluded_paths:
			if path.startswith(excluded):
				return True
		return False


def get_tenant_from_request(request: Request) -> TenantContext | None:
	"""Get tenant context from request state."""
	return getattr(request.state, "tenant_context", None)


def require_tenant_from_request(request: Request) -> TenantContext:
	"""Get tenant context from request, raising if not present."""
	context = get_tenant_from_request(request)
	if context is None:
		from fastapi import HTTPException
		raise HTTPException(status_code=400, detail="Tenant context required")
	return context

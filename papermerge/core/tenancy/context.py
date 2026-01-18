# (c) Copyright Datacraft, 2026
"""Tenant context management using contextvars for async safety."""
import contextvars
from dataclasses import dataclass
from uuid import UUID
from typing import Any

# Context variable for current tenant
_tenant_context: contextvars.ContextVar["TenantContext | None"] = contextvars.ContextVar(
	"tenant_context", default=None
)


@dataclass(frozen=True, slots=True)
class TenantContext:
	"""
	Immutable tenant context for the current request.

	Provides tenant identification, schema name, and feature flags
	that are automatically propagated through async call chains.
	"""
	tenant_id: UUID
	tenant_slug: str
	schema_name: str
	domain: str | None = None
	features: dict[str, bool] | None = None
	plan: str | None = None

	@property
	def is_default_tenant(self) -> bool:
		"""Check if this is the default/public tenant."""
		return self.schema_name == "public"

	def has_feature(self, feature_name: str) -> bool:
		"""Check if tenant has a specific feature enabled."""
		if self.features is None:
			return False
		return self.features.get(feature_name, False)

	def get_schema_prefix(self) -> str:
		"""Get the schema prefix for database tables."""
		if self.is_default_tenant:
			return ""
		return f"{self.schema_name}."


def get_tenant_context() -> TenantContext | None:
	"""
	Get the current tenant context.

	Returns None if no tenant context is set (e.g., during startup,
	or for system-level operations).
	"""
	return _tenant_context.get()


def set_tenant_context(context: TenantContext | None) -> contextvars.Token:
	"""
	Set the tenant context for the current async chain.

	Returns a token that can be used to reset the context.
	"""
	return _tenant_context.set(context)


def require_tenant_context() -> TenantContext:
	"""
	Get the current tenant context, raising if none is set.

	Use this in code paths that must have a tenant context.
	"""
	ctx = get_tenant_context()
	if ctx is None:
		raise RuntimeError("No tenant context available - this operation requires a tenant")
	return ctx


class TenantContextManager:
	"""
	Context manager for temporarily setting tenant context.

	Useful for background tasks or system operations that need
	to run in the context of a specific tenant.

	Example:
		async with TenantContextManager(tenant_context):
			await process_documents()
	"""

	def __init__(self, context: TenantContext | None):
		self.context = context
		self.token: contextvars.Token | None = None

	def __enter__(self) -> "TenantContextManager":
		self.token = set_tenant_context(self.context)
		return self

	def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
		if self.token is not None:
			_tenant_context.reset(self.token)

	async def __aenter__(self) -> "TenantContextManager":
		return self.__enter__()

	async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
		self.__exit__(exc_type, exc_val, exc_tb)


def create_tenant_context(
	tenant_id: UUID,
	tenant_slug: str,
	domain: str | None = None,
	features: dict[str, bool] | None = None,
	plan: str | None = None,
) -> TenantContext:
	"""
	Create a new tenant context with the appropriate schema name.

	Schema naming convention: tenant_<slug>
	"""
	# Sanitize slug for schema name (only alphanumeric and underscore)
	safe_slug = "".join(c if c.isalnum() or c == "_" else "_" for c in tenant_slug.lower())
	schema_name = f"tenant_{safe_slug}"

	return TenantContext(
		tenant_id=tenant_id,
		tenant_slug=tenant_slug,
		schema_name=schema_name,
		domain=domain,
		features=features,
		plan=plan,
	)

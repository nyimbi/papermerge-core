# (c) Copyright Datacraft, 2026
"""
Schema-per-tenant database management.

Provides utilities for creating, migrating, and managing
per-tenant PostgreSQL schemas for data isolation.
"""
import logging
from typing import Sequence
from uuid import UUID

from sqlalchemy import text, inspect
from sqlalchemy.ext.asyncio import AsyncSession, AsyncEngine
from sqlalchemy.orm import DeclarativeBase

from .context import TenantContext, create_tenant_context

logger = logging.getLogger(__name__)

# Tables that should remain in public schema (shared across tenants)
PUBLIC_SCHEMA_TABLES = frozenset({
	"tenants",
	"tenant_branding",
	"tenant_settings",
	"alembic_version",
})

# Tables that should be created per-tenant
TENANT_SCHEMA_TABLES = frozenset({
	"users",
	"groups",
	"roles",
	"permissions",
	"user_groups",
	"user_roles",
	"nodes",
	"documents",
	"folders",
	"document_versions",
	"pages",
	"tags",
	"node_tags",
	"custom_fields",
	"custom_field_values",
	"document_types",
	"workflows",
	"workflow_instances",
	"workflow_steps",
	"cases",
	"portfolios",
	"audit_logs",
})


class TenantSchemaManager:
	"""
	Manages per-tenant PostgreSQL schemas.

	Each tenant gets its own schema (namespace) in PostgreSQL,
	providing strong data isolation while sharing the same database.
	"""

	def __init__(self, engine: AsyncEngine):
		self.engine = engine

	def get_schema_name(self, tenant_slug: str) -> str:
		"""Generate schema name from tenant slug."""
		safe_slug = "".join(
			c if c.isalnum() or c == "_" else "_"
			for c in tenant_slug.lower()
		)
		return f"tenant_{safe_slug}"

	async def schema_exists(self, schema_name: str) -> bool:
		"""Check if a schema exists."""
		async with self.engine.connect() as conn:
			result = await conn.execute(
				text(
					"SELECT EXISTS(SELECT 1 FROM information_schema.schemata "
					"WHERE schema_name = :schema)"
				),
				{"schema": schema_name},
			)
			return bool(result.scalar())

	async def create_schema(self, schema_name: str) -> None:
		"""Create a new schema if it doesn't exist."""
		# Validate schema name to prevent SQL injection
		if not schema_name.replace("_", "").isalnum():
			raise ValueError(f"Invalid schema name: {schema_name}")

		async with self.engine.begin() as conn:
			await conn.execute(
				text(f"CREATE SCHEMA IF NOT EXISTS {schema_name}")
			)
			logger.info(f"Created schema: {schema_name}")

	async def drop_schema(self, schema_name: str, cascade: bool = False) -> None:
		"""
		Drop a schema.

		Use with caution - this will delete all data in the schema.
		"""
		if schema_name == "public":
			raise ValueError("Cannot drop public schema")

		if not schema_name.replace("_", "").isalnum():
			raise ValueError(f"Invalid schema name: {schema_name}")

		async with self.engine.begin() as conn:
			cascade_sql = "CASCADE" if cascade else "RESTRICT"
			await conn.execute(
				text(f"DROP SCHEMA IF EXISTS {schema_name} {cascade_sql}")
			)
			logger.info(f"Dropped schema: {schema_name}")

	async def list_schemas(self) -> list[str]:
		"""List all tenant schemas."""
		async with self.engine.connect() as conn:
			result = await conn.execute(
				text(
					"SELECT schema_name FROM information_schema.schemata "
					"WHERE schema_name LIKE 'tenant_%' "
					"ORDER BY schema_name"
				)
			)
			return [row[0] for row in result.fetchall()]

	async def create_tenant_schema(
		self,
		db_session: AsyncSession,
		tenant_id: UUID,
		tenant_slug: str,
	) -> str:
		"""
		Create a complete schema for a new tenant.

		This creates the schema and all required tables with proper
		structure matching the public schema.
		"""
		schema_name = self.get_schema_name(tenant_slug)

		# Create the schema
		await self.create_schema(schema_name)

		# Get the public schema table definitions
		async with self.engine.begin() as conn:
			# Clone table structures from public schema
			for table_name in TENANT_SCHEMA_TABLES:
				await self._clone_table_to_schema(conn, table_name, schema_name)

			# Grant usage on schema
			await conn.execute(
				text(f"GRANT USAGE ON SCHEMA {schema_name} TO PUBLIC")
			)

		logger.info(f"Created tenant schema with tables: {schema_name}")
		return schema_name

	async def _clone_table_to_schema(
		self,
		conn,
		table_name: str,
		target_schema: str,
	) -> None:
		"""Clone a table structure from public schema to target schema."""
		# Check if table exists in public
		result = await conn.execute(
			text(
				"SELECT EXISTS(SELECT 1 FROM information_schema.tables "
				"WHERE table_schema = 'public' AND table_name = :table)"
			),
			{"table": table_name},
		)
		if not result.scalar():
			logger.debug(f"Table {table_name} not found in public schema, skipping")
			return

		# Clone structure (without data)
		await conn.execute(
			text(
				f"CREATE TABLE IF NOT EXISTS {target_schema}.{table_name} "
				f"(LIKE public.{table_name} INCLUDING ALL)"
			)
		)
		logger.debug(f"Cloned table: public.{table_name} -> {target_schema}.{table_name}")

	async def migrate_tenant_schema(
		self,
		schema_name: str,
		revision: str | None = None,
	) -> None:
		"""
		Run migrations for a tenant schema.

		Uses the same migration scripts as the public schema but
		targets the tenant schema.
		"""
		# This would integrate with Alembic
		# For now, we rely on table cloning from public schema
		logger.info(f"Migrating tenant schema: {schema_name}")

	async def set_search_path(
		self,
		conn,
		schema_name: str,
	) -> None:
		"""
		Set the search path for a connection to use the tenant schema.

		This makes queries automatically resolve to the tenant's tables.
		"""
		await conn.execute(
			text(f"SET search_path TO {schema_name}, public")
		)

	async def reset_search_path(self, conn) -> None:
		"""Reset search path to default (public only)."""
		await conn.execute(text("SET search_path TO public"))

	async def get_schema_size(self, schema_name: str) -> int:
		"""Get the total size of a schema in bytes."""
		async with self.engine.connect() as conn:
			result = await conn.execute(
				text(
					"SELECT COALESCE(SUM(pg_total_relation_size("
					"quote_ident(schemaname) || '.' || quote_ident(tablename)"
					")), 0) as size "
					"FROM pg_tables WHERE schemaname = :schema"
				),
				{"schema": schema_name},
			)
			return int(result.scalar() or 0)

	async def get_schema_table_counts(
		self, schema_name: str
	) -> dict[str, int]:
		"""Get row counts for all tables in a schema."""
		counts = {}
		async with self.engine.connect() as conn:
			# Get table names
			result = await conn.execute(
				text(
					"SELECT tablename FROM pg_tables WHERE schemaname = :schema"
				),
				{"schema": schema_name},
			)
			tables = [row[0] for row in result.fetchall()]

			# Get counts for each table
			for table in tables:
				count_result = await conn.execute(
					text(f"SELECT COUNT(*) FROM {schema_name}.{table}")
				)
				counts[table] = int(count_result.scalar() or 0)

		return counts


class TenantAwareSession:
	"""
	Context manager for tenant-aware database sessions.

	Automatically sets the search path to include the tenant's schema,
	making queries resolve to tenant-specific tables.
	"""

	def __init__(
		self,
		session: AsyncSession,
		tenant_context: TenantContext,
	):
		self.session = session
		self.tenant_context = tenant_context

	async def __aenter__(self) -> AsyncSession:
		if not self.tenant_context.is_default_tenant:
			await self.session.execute(
				text(
					f"SET search_path TO {self.tenant_context.schema_name}, public"
				)
			)
		return self.session

	async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
		# Reset search path
		await self.session.execute(text("SET search_path TO public"))


async def get_tenant_session(
	session: AsyncSession,
	tenant_context: TenantContext | None = None,
) -> AsyncSession:
	"""
	Get a session configured for the current tenant.

	If tenant_context is None, uses the context from context vars.
	"""
	if tenant_context is None:
		from .context import get_tenant_context
		tenant_context = get_tenant_context()

	if tenant_context and not tenant_context.is_default_tenant:
		await session.execute(
			text(
				f"SET search_path TO {tenant_context.schema_name}, public"
			)
		)

	return session


class SchemaRouter:
	"""
	Routes database queries to the appropriate schema based on tenant.

	Used with SQLAlchemy's event system for automatic schema routing.
	"""

	def __init__(self, public_tables: set[str] | None = None):
		self.public_tables = public_tables or PUBLIC_SCHEMA_TABLES

	def get_schema_for_table(
		self,
		table_name: str,
		tenant_context: TenantContext | None,
	) -> str:
		"""Determine which schema to use for a given table."""
		# Public tables always go to public schema
		if table_name in self.public_tables:
			return "public"

		# If no tenant context, use public
		if tenant_context is None:
			return "public"

		# Use tenant schema
		return tenant_context.schema_name

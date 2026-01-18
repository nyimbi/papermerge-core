import logging
import time
from typing import Any, Sequence
from uuid import UUID

from sqlalchemy import select, func, and_, or_, text
from sqlalchemy.ext.asyncio import AsyncSession

from .base import SearchBackend, SearchBackendType, SearchQuery, SearchResult, SearchHit

logger = logging.getLogger(__name__)


# Language config mapping for PostgreSQL
LANG_CONFIG_MAP = {
	'deu': 'german',
	'eng': 'english',
	'fra': 'french',
	'spa': 'spanish',
	'ita': 'italian',
	'por': 'portuguese',
	'rus': 'russian',
	'nld': 'dutch',
	'swe': 'swedish',
	'nor': 'norwegian',
	'dan': 'danish',
	'fin': 'finnish',
	'hun': 'hungarian',
	'rom': 'romanian',
	'tur': 'turkish',
}


class PostgresSearchBackend(SearchBackend):
	"""PostgreSQL full-text search backend using tsvector."""

	backend_type = SearchBackendType.POSTGRES

	def __init__(self, session_factory):
		"""
		Initialize PostgreSQL search backend.

		Args:
			session_factory: Async session factory for database connections
		"""
		self.session_factory = session_factory

	async def search(self, query: SearchQuery) -> SearchResult:
		"""Execute full-text search using PostgreSQL."""
		start_time = time.time()

		async with self.session_factory() as session:
			lang_config = LANG_CONFIG_MAP.get(query.lang, 'simple')

			# Build the search query
			if query.query.strip():
				# Parse query terms
				terms = query.query.strip().split()
				ts_query_str = ' & '.join(terms)

				if '|' in ts_query_str or '(' in ts_query_str:
					ts_query = func.to_tsquery(lang_config, ts_query_str)
				else:
					ts_query = func.plainto_tsquery(lang_config, ts_query_str)
			else:
				ts_query = None

			# Build main query
			sql = """
				SELECT
					dsi.document_id,
					dsi.title,
					dsi.document_type_name,
					dsi.tags,
					dsi.owner_type,
					dsi.owner_id,
					n.created_at,
					n.updated_at,
					{rank_expr} as score
				FROM document_search_index dsi
				JOIN nodes n ON n.id = dsi.document_id
				JOIN ownerships o ON o.resource_id = n.id AND o.resource_type = 'node'
				WHERE 1=1
				{access_filter}
				{fts_filter}
				{type_filter}
				{tag_filter}
				{owner_filter}
				{date_filters}
				ORDER BY {order_by}
				LIMIT :limit OFFSET :offset
			"""

			# Build rank expression
			if ts_query:
				rank_expr = f"ts_rank(dsi.search_vector, plainto_tsquery('{lang_config}', :query))"
			else:
				rank_expr = "1.0"

			# Build access filter
			access_filter = """
				AND (
					(dsi.owner_type = 'user' AND dsi.owner_id = :user_id)
					OR (dsi.owner_type = 'group' AND dsi.owner_id IN (
						SELECT group_id FROM users_groups WHERE user_id = :user_id
					))
				)
			"""

			# Build FTS filter
			fts_filter = ""
			if ts_query:
				fts_filter = f"AND dsi.search_vector @@ plainto_tsquery('{lang_config}', :query)"

			# Build type filter
			type_filter = ""
			if query.document_type_ids:
				type_filter = "AND dsi.document_type_id = ANY(:type_ids)"

			# Build tag filter
			tag_filter = ""
			if query.tag_names:
				tag_filter = "AND dsi.tags && :tag_names"

			# Build owner filter
			owner_filter = ""
			if query.owner_id:
				owner_filter = "AND dsi.owner_id = :owner_id"

			# Build date filters
			date_filters = ""
			if query.created_after:
				date_filters += " AND n.created_at >= :created_after"
			if query.created_before:
				date_filters += " AND n.created_at <= :created_before"
			if query.updated_after:
				date_filters += " AND n.updated_at >= :updated_after"
			if query.updated_before:
				date_filters += " AND n.updated_at <= :updated_before"

			# Build order by
			if query.sort_by == 'relevance' and ts_query:
				order_by = f"score {query.sort_order.upper()}"
			elif query.sort_by == 'created_at':
				order_by = f"n.created_at {query.sort_order.upper()}"
			elif query.sort_by == 'updated_at':
				order_by = f"n.updated_at {query.sort_order.upper()}"
			elif query.sort_by == 'title':
				order_by = f"dsi.title {query.sort_order.upper()}"
			else:
				order_by = "n.created_at DESC"

			# Format SQL
			sql = sql.format(
				rank_expr=rank_expr,
				access_filter=access_filter,
				fts_filter=fts_filter,
				type_filter=type_filter,
				tag_filter=tag_filter,
				owner_filter=owner_filter,
				date_filters=date_filters,
				order_by=order_by
			)

			# Build parameters
			params = {
				'user_id': query.user_id,
				'limit': query.page_size,
				'offset': (query.page - 1) * query.page_size
			}

			if query.query.strip():
				params['query'] = query.query

			if query.document_type_ids:
				params['type_ids'] = [str(t) for t in query.document_type_ids]

			if query.tag_names:
				params['tag_names'] = query.tag_names

			if query.owner_id:
				params['owner_id'] = query.owner_id

			if query.created_after:
				params['created_after'] = query.created_after
			if query.created_before:
				params['created_before'] = query.created_before
			if query.updated_after:
				params['updated_after'] = query.updated_after
			if query.updated_before:
				params['updated_before'] = query.updated_before

			# Execute search query
			result = await session.execute(text(sql), params)
			rows = result.fetchall()

			# Build hits
			hits = []
			for row in rows:
				hits.append(SearchHit(
					document_id=row[0],
					title=row[1],
					score=float(row[8]) if row[8] else 1.0,
					document_type=row[2],
					tags=row[3] or [],
					owner_type=row[4],
					owner_id=row[5],
					created_at=row[6],
					updated_at=row[7]
				))

			# Get total count
			count_sql = """
				SELECT COUNT(DISTINCT dsi.document_id)
				FROM document_search_index dsi
				JOIN nodes n ON n.id = dsi.document_id
				JOIN ownerships o ON o.resource_id = n.id AND o.resource_type = 'node'
				WHERE 1=1
				{access_filter}
				{fts_filter}
				{type_filter}
				{tag_filter}
				{owner_filter}
				{date_filters}
			""".format(
				access_filter=access_filter,
				fts_filter=fts_filter,
				type_filter=type_filter,
				tag_filter=tag_filter,
				owner_filter=owner_filter,
				date_filters=date_filters
			)

			count_result = await session.execute(text(count_sql), params)
			total = count_result.scalar() or 0

			query_time = (time.time() - start_time) * 1000

			return SearchResult(
				hits=hits,
				total=total,
				page=query.page,
				page_size=query.page_size,
				query_time_ms=query_time,
				backend='postgres'
			)

	async def index_document(
		self,
		document_id: UUID,
		title: str,
		content: str,
		metadata: dict[str, Any]
	) -> bool:
		"""Index document using PostgreSQL function."""
		async with self.session_factory() as session:
			try:
				await session.execute(
					text("SELECT upsert_document_search_index(:doc_id)"),
					{"doc_id": document_id}
				)
				await session.commit()
				return True
			except Exception as e:
				logger.error(f"Failed to index document {document_id}: {e}")
				return False

	async def update_document(
		self,
		document_id: UUID,
		title: str | None = None,
		content: str | None = None,
		metadata: dict[str, Any] | None = None
	) -> bool:
		"""Update document in index (re-index)."""
		return await self.index_document(
			document_id,
			title or '',
			content or '',
			metadata or {}
		)

	async def delete_document(self, document_id: UUID) -> bool:
		"""Remove document from search index."""
		async with self.session_factory() as session:
			try:
				await session.execute(
					text("DELETE FROM document_search_index WHERE document_id = :doc_id"),
					{"doc_id": document_id}
				)
				await session.commit()
				return True
			except Exception as e:
				logger.error(f"Failed to delete document {document_id} from index: {e}")
				return False

	async def bulk_index(
		self,
		documents: Sequence[dict[str, Any]]
	) -> tuple[int, int]:
		"""Bulk index documents."""
		success = 0
		failure = 0

		async with self.session_factory() as session:
			for doc in documents:
				try:
					await session.execute(
						text("SELECT upsert_document_search_index(:doc_id)"),
						{"doc_id": doc['id']}
					)
					success += 1

					if success % 100 == 0:
						await session.commit()
				except Exception as e:
					logger.error(f"Failed to index document {doc.get('id')}: {e}")
					failure += 1

			await session.commit()

		return success, failure

	async def get_stats(self) -> dict[str, Any]:
		"""Get index statistics."""
		async with self.session_factory() as session:
			# Get count
			count_result = await session.execute(
				text("SELECT COUNT(*) FROM document_search_index")
			)
			count = count_result.scalar() or 0

			# Get size
			try:
				size_result = await session.execute(
					text("SELECT pg_size_pretty(pg_total_relation_size('document_search_index'))")
				)
				size = size_result.scalar()
			except Exception:
				size = 'unknown'

			return {
				'backend': 'postgres',
				'document_count': count,
				'index_size': size
			}

	async def health_check(self) -> bool:
		"""Check database connectivity."""
		try:
			async with self.session_factory() as session:
				await session.execute(text("SELECT 1"))
				return True
		except Exception:
			return False

	async def suggest(
		self,
		prefix: str,
		user_id: UUID,
		limit: int = 10
	) -> list[str]:
		"""Get title suggestions based on prefix."""
		async with self.session_factory() as session:
			sql = """
				SELECT DISTINCT title
				FROM document_search_index dsi
				WHERE title ILIKE :prefix
				AND (
					(owner_type = 'user' AND owner_id = :user_id)
					OR (owner_type = 'group' AND owner_id IN (
						SELECT group_id FROM users_groups WHERE user_id = :user_id
					))
				)
				ORDER BY title
				LIMIT :limit
			"""

			result = await session.execute(
				text(sql),
				{'prefix': f'{prefix}%', 'user_id': user_id, 'limit': limit}
			)

			return [row[0] for row in result.fetchall()]

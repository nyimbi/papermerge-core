import logging
import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .backends.base import SearchHit, SearchResult, SearchQuery
from .embeddings.service import EmbeddingService
from papermerge.core.features.search.db.orm import DocumentEmbeddingModel

logger = logging.getLogger(__name__)


@dataclass
class SemanticSearchResult:
	"""Result from semantic search."""
	hits: list[SearchHit]
	total: int
	query_embedding_time_ms: float
	search_time_ms: float
	total_time_ms: float


class SemanticSearch:
	"""
	Semantic search using vector embeddings.

	Uses pgvector for similarity search with optional hybrid scoring.
	"""

	def __init__(
		self,
		embedding_service: EmbeddingService,
		session_factory
	):
		"""
		Initialize semantic search.

		Args:
			embedding_service: Service for generating embeddings
			session_factory: Async session factory for database
		"""
		self.embedding_service = embedding_service
		self.session_factory = session_factory

	async def search(
		self,
		query: str,
		user_id: UUID,
		limit: int = 20,
		threshold: float = 0.5,
		document_type_ids: list[UUID] | None = None
	) -> SemanticSearchResult:
		"""
		Perform semantic search using embeddings.

		Args:
			query: Search query
			user_id: User ID for access control
			limit: Maximum results
			threshold: Minimum similarity threshold (0-1)
			document_type_ids: Optional document type filter

		Returns:
			SemanticSearchResult with hits and timing
		"""
		start_time = time.time()

		# Generate query embedding
		embed_start = time.time()
		query_embedding = await self.embedding_service.embed_query(query)
		embed_time = (time.time() - embed_start) * 1000

		# Search for similar documents
		search_start = time.time()

		async with self.session_factory() as session:
			# Build similarity search query using pgvector
			sql = """
				WITH user_access AS (
					SELECT group_id FROM users_groups WHERE user_id = :user_id
				)
				SELECT
					de.document_id,
					de.chunk_index,
					de.chunk_text,
					dsi.title,
					dsi.document_type_name,
					dsi.tags,
					dsi.owner_type,
					dsi.owner_id,
					1 - (de.embedding <=> :query_embedding::float[]) as similarity
				FROM document_embeddings de
				JOIN document_search_index dsi ON dsi.document_id = de.document_id
				WHERE (
					(dsi.owner_type = 'user' AND dsi.owner_id = :user_id)
					OR (dsi.owner_type = 'group' AND dsi.owner_id IN (SELECT group_id FROM user_access))
				)
				{type_filter}
				AND 1 - (de.embedding <=> :query_embedding::float[]) >= :threshold
				ORDER BY similarity DESC
				LIMIT :limit
			"""

			type_filter = ""
			if document_type_ids:
				type_filter = "AND dsi.document_type_id = ANY(:type_ids)"

			sql = sql.format(type_filter=type_filter)

			params = {
				'user_id': user_id,
				'query_embedding': query_embedding.embedding,
				'threshold': threshold,
				'limit': limit
			}

			if document_type_ids:
				params['type_ids'] = [str(t) for t in document_type_ids]

			result = await session.execute(text(sql), params)
			rows = result.fetchall()

			# Group by document and take best chunk
			doc_hits: dict[UUID, SearchHit] = {}
			for row in rows:
				doc_id = row[0]
				similarity = float(row[8])

				if doc_id not in doc_hits or similarity > doc_hits[doc_id].score:
					doc_hits[doc_id] = SearchHit(
						document_id=doc_id,
						title=row[3],
						score=similarity,
						highlights={'content': [row[2][:200] if row[2] else '']},
						document_type=row[4],
						tags=row[5] or [],
						owner_type=row[6],
						owner_id=row[7]
					)

			hits = list(doc_hits.values())
			hits.sort(key=lambda h: h.score, reverse=True)

		search_time = (time.time() - search_start) * 1000
		total_time = (time.time() - start_time) * 1000

		return SemanticSearchResult(
			hits=hits,
			total=len(hits),
			query_embedding_time_ms=embed_time,
			search_time_ms=search_time,
			total_time_ms=total_time
		)

	async def hybrid_search(
		self,
		query: SearchQuery,
		semantic_weight: float = 0.5
	) -> SearchResult:
		"""
		Perform hybrid search combining FTS and semantic search.

		Args:
			query: Search query parameters
			semantic_weight: Weight for semantic scores (0-1)
				0 = pure FTS, 1 = pure semantic

		Returns:
			SearchResult with combined scores
		"""
		start_time = time.time()
		fts_weight = 1 - semantic_weight

		# Get FTS results
		from .factory import get_search_backend
		fts_backend = get_search_backend('postgres')
		fts_query = SearchQuery(
			query=query.query,
			user_id=query.user_id,
			page=1,
			page_size=query.page_size * 2,  # Get more for merging
			lang=query.lang,
			document_type_ids=query.document_type_ids,
			tag_names=query.tag_names
		)
		fts_result = await fts_backend.search(fts_query)

		# Get semantic results
		semantic_result = await self.search(
			query=query.query,
			user_id=query.user_id,
			limit=query.page_size * 2,
			threshold=0.3,
			document_type_ids=query.document_type_ids
		)

		# Normalize and combine scores
		combined_scores: dict[UUID, dict] = {}

		# Add FTS results
		if fts_result.hits:
			max_fts = max(h.score for h in fts_result.hits)
			for hit in fts_result.hits:
				normalized_fts = hit.score / max_fts if max_fts > 0 else 0
				combined_scores[hit.document_id] = {
					'hit': hit,
					'fts_score': normalized_fts,
					'semantic_score': 0
				}

		# Add semantic results
		if semantic_result.hits:
			for hit in semantic_result.hits:
				if hit.document_id in combined_scores:
					combined_scores[hit.document_id]['semantic_score'] = hit.score
				else:
					combined_scores[hit.document_id] = {
						'hit': hit,
						'fts_score': 0,
						'semantic_score': hit.score
					}

		# Calculate combined scores and sort
		final_hits = []
		for doc_id, data in combined_scores.items():
			combined = (
				data['fts_score'] * fts_weight +
				data['semantic_score'] * semantic_weight
			)
			hit = data['hit']
			hit.score = combined
			hit.metadata['fts_score'] = data['fts_score']
			hit.metadata['semantic_score'] = data['semantic_score']
			final_hits.append(hit)

		final_hits.sort(key=lambda h: h.score, reverse=True)

		# Apply pagination
		offset = (query.page - 1) * query.page_size
		paginated_hits = final_hits[offset:offset + query.page_size]

		query_time = (time.time() - start_time) * 1000

		return SearchResult(
			hits=paginated_hits,
			total=len(final_hits),
			page=query.page,
			page_size=query.page_size,
			query_time_ms=query_time,
			backend='hybrid'
		)

	async def index_document(
		self,
		document_id: UUID,
		document_version_id: UUID,
		text: str,
		page_id: UUID | None = None
	) -> int:
		"""
		Generate and store embeddings for a document.

		Args:
			document_id: Document UUID
			document_version_id: Version UUID
			text: Full text content
			page_id: Optional page UUID for page-level indexing

		Returns:
			Number of chunks indexed
		"""
		# Split into chunks
		chunks = self.embedding_service.chunk_text(text)

		if not chunks:
			return 0

		# Generate embeddings
		embeddings = await self.embedding_service.embed_texts(chunks)

		# Store in database
		async with self.session_factory() as session:
			from uuid_extensions import uuid7
			
			for i, (chunk, embedding_result) in enumerate(zip(chunks, embeddings)):
				embedding_obj = DocumentEmbeddingModel(
					id=uuid7(),
					document_id=document_id,
					document_version_id=document_version_id,
					page_id=page_id,
					chunk_index=i,
					chunk_text=chunk,
					embedding=embedding_result.embedding,
					model_name=embedding_result.model,
					model_version=None,
					embedding_dimension=embedding_result.dimension
				)
				await session.merge(embedding_obj)

			await session.commit()

		return len(chunks)

	async def delete_document_embeddings(self, document_id: UUID) -> int:
		"""
		Delete all embeddings for a document.

		Args:
			document_id: Document UUID

		Returns:
			Number of embeddings deleted
		"""
		async with self.session_factory() as session:
			result = await session.execute(
				text("DELETE FROM document_embeddings WHERE document_id = :doc_id"),
				{'doc_id': document_id}
			)
			await session.commit()
			return result.rowcount

	async def find_similar(
		self,
		document_id: UUID,
		user_id: UUID,
		limit: int = 10
	) -> list[SearchHit]:
		"""
		Find documents similar to a given document.

		Args:
			document_id: Reference document UUID
			user_id: User ID for access control
			limit: Maximum results

		Returns:
			List of similar document hits
		"""
		async with self.session_factory() as session:
			# Get embeddings for reference document
			result = await session.execute(
				text("""
					SELECT embedding
					FROM document_embeddings
					WHERE document_id = :doc_id
					ORDER BY chunk_index
					LIMIT 1
				"""),
				{'doc_id': document_id}
			)
			row = result.fetchone()

			if not row:
				return []

			ref_embedding = row[0]

			# Find similar documents
			result = await session.execute(
				text("""
					WITH user_access AS (
						SELECT group_id FROM users_groups WHERE user_id = :user_id
					)
					SELECT DISTINCT ON (de.document_id)
						de.document_id,
						dsi.title,
						dsi.document_type_name,
						dsi.tags,
						1 - (de.embedding <=> :ref_embedding::float[]) as similarity
					FROM document_embeddings de
					JOIN document_search_index dsi ON dsi.document_id = de.document_id
					WHERE de.document_id != :doc_id
					AND (
						(dsi.owner_type = 'user' AND dsi.owner_id = :user_id)
						OR (dsi.owner_type = 'group' AND dsi.owner_id IN (SELECT group_id FROM user_access))
					)
					ORDER BY de.document_id, similarity DESC
					LIMIT :limit
				"""),
				{
					'doc_id': document_id,
					'user_id': user_id,
					'ref_embedding': ref_embedding,
					'limit': limit
				}
			)

			hits = []
			for row in result.fetchall():
				hits.append(SearchHit(
					document_id=row[0],
					title=row[1],
					score=float(row[4]),
					document_type=row[2],
					tags=row[3] or []
				))

			return sorted(hits, key=lambda h: h.score, reverse=True)

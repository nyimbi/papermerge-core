import logging
import time
from typing import Any, Sequence
from uuid import UUID

from .base import SearchBackend, SearchBackendType, SearchQuery, SearchResult, SearchHit

logger = logging.getLogger(__name__)


class MeilisearchBackend(SearchBackend):
	"""Meilisearch search backend."""

	backend_type = SearchBackendType.MEILISEARCH

	def __init__(
		self,
		host: str = 'http://localhost:7700',
		api_key: str | None = None,
		index_name: str = 'documents'
	):
		"""
		Initialize Meilisearch backend.

		Args:
			host: Meilisearch host URL
			api_key: API key for authentication
			index_name: Name of the search index
		"""
		self.host = host
		self.api_key = api_key
		self.index_name = index_name
		self._client = None

	@property
	def client(self):
		"""Lazy-loaded Meilisearch client."""
		if self._client is None:
			try:
				import meilisearch

				self._client = meilisearch.AsyncClient(
					self.host,
					self.api_key
				)
			except ImportError:
				raise ImportError("meilisearch package not installed. Install with: pip install meilisearch")

		return self._client

	async def _ensure_index(self):
		"""Ensure index exists with proper settings."""
		try:
			index = self.client.index(self.index_name)

			# Update settings
			await index.update_settings({
				'searchableAttributes': ['title', 'content', 'tags'],
				'filterableAttributes': [
					'document_type',
					'document_type_id',
					'tags',
					'owner_id',
					'owner_type',
					'tenant_id',
					'created_at',
					'updated_at'
				],
				'sortableAttributes': ['title', 'created_at', 'updated_at'],
				'rankingRules': [
					'words',
					'typo',
					'proximity',
					'attribute',
					'sort',
					'exactness'
				]
			})
		except Exception as e:
			# Index might not exist yet, will be created on first document
			logger.debug(f"Index setup: {e}")

	async def search(self, query: SearchQuery) -> SearchResult:
		"""Execute search using Meilisearch."""
		start_time = time.time()

		await self._ensure_index()

		index = self.client.index(self.index_name)

		# Build filters
		filters = []

		# Access control (simplified - would need group membership)
		filters.append(f'owner_id = "{query.user_id}"')

		# Document type filter
		if query.document_type_ids:
			type_filters = [f'document_type_id = "{t}"' for t in query.document_type_ids]
			filters.append(f'({" OR ".join(type_filters)})')

		# Tag filter
		if query.tag_names:
			tag_filters = [f'tags = "{t}"' for t in query.tag_names]
			filters.append(f'({" OR ".join(tag_filters)})')

		# Owner filter
		if query.owner_id:
			filters.append(f'owner_id = "{query.owner_id}"')

		# Date filters
		if query.created_after:
			filters.append(f'created_at >= {int(query.created_after.timestamp())}')
		if query.created_before:
			filters.append(f'created_at <= {int(query.created_before.timestamp())}')
		if query.updated_after:
			filters.append(f'updated_at >= {int(query.updated_after.timestamp())}')
		if query.updated_before:
			filters.append(f'updated_at <= {int(query.updated_before.timestamp())}')

		filter_str = ' AND '.join(filters) if filters else None

		# Build sort
		sort = None
		if query.sort_by == 'created_at':
			sort = [f'created_at:{query.sort_order}']
		elif query.sort_by == 'updated_at':
			sort = [f'updated_at:{query.sort_order}']
		elif query.sort_by == 'title':
			sort = [f'title:{query.sort_order}']

		# Execute search
		search_params = {
			'q': query.query,
			'limit': query.page_size,
			'offset': (query.page - 1) * query.page_size,
			'attributesToHighlight': ['title', 'content'],
			'highlightPreTag': '<mark>',
			'highlightPostTag': '</mark>'
		}

		if filter_str:
			search_params['filter'] = filter_str
		if sort:
			search_params['sort'] = sort

		response = await index.search(**search_params)

		# Parse response
		hits = []
		for hit in response['hits']:
			highlights = {}
			if '_formatted' in hit:
				if hit['_formatted'].get('title'):
					highlights['title'] = [hit['_formatted']['title']]
				if hit['_formatted'].get('content'):
					highlights['content'] = [hit['_formatted']['content'][:200]]

			hits.append(SearchHit(
				document_id=UUID(hit['document_id']),
				title=hit['title'],
				score=1.0,  # Meilisearch doesn't return scores by default
				highlights=highlights,
				document_type=hit.get('document_type'),
				tags=hit.get('tags', []),
				owner_id=UUID(hit['owner_id']) if hit.get('owner_id') else None,
				owner_type=hit.get('owner_type'),
				created_at=hit.get('created_at'),
				updated_at=hit.get('updated_at'),
				metadata=hit.get('custom_fields', {})
			))

		total = response.get('estimatedTotalHits', len(hits))
		query_time = (time.time() - start_time) * 1000

		return SearchResult(
			hits=hits,
			total=total,
			page=query.page,
			page_size=query.page_size,
			query_time_ms=query_time,
			backend='meilisearch'
		)

	async def index_document(
		self,
		document_id: UUID,
		title: str,
		content: str,
		metadata: dict[str, Any]
	) -> bool:
		"""Index a document."""
		await self._ensure_index()

		index = self.client.index(self.index_name)

		try:
			await index.add_documents([{
				'id': str(document_id),
				'document_id': str(document_id),
				'title': title,
				'content': content,
				**metadata
			}])
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
		"""Update a document."""
		index = self.client.index(self.index_name)

		try:
			update_doc = {'id': str(document_id)}
			if title is not None:
				update_doc['title'] = title
			if content is not None:
				update_doc['content'] = content
			if metadata is not None:
				update_doc.update(metadata)

			await index.update_documents([update_doc])
			return True
		except Exception as e:
			logger.error(f"Failed to update document {document_id}: {e}")
			return False

	async def delete_document(self, document_id: UUID) -> bool:
		"""Delete a document from index."""
		index = self.client.index(self.index_name)

		try:
			await index.delete_document(str(document_id))
			return True
		except Exception as e:
			logger.error(f"Failed to delete document {document_id}: {e}")
			return False

	async def bulk_index(
		self,
		documents: Sequence[dict[str, Any]]
	) -> tuple[int, int]:
		"""Bulk index documents."""
		await self._ensure_index()

		index = self.client.index(self.index_name)

		docs = []
		for doc in documents:
			docs.append({
				'id': str(doc['id']),
				'document_id': str(doc['id']),
				'title': doc.get('title', ''),
				'content': doc.get('content', ''),
				**doc.get('metadata', {})
			})

		try:
			await index.add_documents(docs)
			return len(docs), 0
		except Exception as e:
			logger.error(f"Bulk indexing failed: {e}")
			return 0, len(docs)

	async def get_stats(self) -> dict[str, Any]:
		"""Get index statistics."""
		try:
			index = self.client.index(self.index_name)
			stats = await index.get_stats()
			return {
				'backend': 'meilisearch',
				'document_count': stats['numberOfDocuments'],
				'is_indexing': stats['isIndexing']
			}
		except Exception as e:
			logger.error(f"Failed to get stats: {e}")
			return {'backend': 'meilisearch', 'error': str(e)}

	async def health_check(self) -> bool:
		"""Check Meilisearch health."""
		try:
			health = await self.client.health()
			return health['status'] == 'available'
		except Exception:
			return False

	async def suggest(
		self,
		prefix: str,
		user_id: UUID,
		limit: int = 10
	) -> list[str]:
		"""Get search suggestions."""
		index = self.client.index(self.index_name)

		try:
			response = await index.search(
				prefix,
				{
					'limit': limit,
					'attributesToRetrieve': ['title'],
					'filter': f'owner_id = "{user_id}"'
				}
			)
			return [hit['title'] for hit in response['hits']]
		except Exception as e:
			logger.error(f"Suggest failed: {e}")
			return []

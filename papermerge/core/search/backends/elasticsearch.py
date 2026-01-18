import logging
import time
from typing import Any, Sequence
from uuid import UUID

from .base import SearchBackend, SearchBackendType, SearchQuery, SearchResult, SearchHit

logger = logging.getLogger(__name__)


class ElasticsearchBackend(SearchBackend):
	"""Elasticsearch search backend."""

	backend_type = SearchBackendType.ELASTICSEARCH

	def __init__(
		self,
		hosts: list[str] | None = None,
		index_name: str = 'documents',
		api_key: str | None = None,
		cloud_id: str | None = None
	):
		"""
		Initialize Elasticsearch backend.

		Args:
			hosts: List of Elasticsearch hosts
			index_name: Name of the search index
			api_key: API key for authentication
			cloud_id: Elastic Cloud ID
		"""
		self.hosts = hosts or ['http://localhost:9200']
		self.index_name = index_name
		self.api_key = api_key
		self.cloud_id = cloud_id
		self._client = None

	@property
	def client(self):
		"""Lazy-loaded Elasticsearch client."""
		if self._client is None:
			try:
				from elasticsearch import AsyncElasticsearch

				if self.cloud_id:
					self._client = AsyncElasticsearch(
						cloud_id=self.cloud_id,
						api_key=self.api_key
					)
				else:
					self._client = AsyncElasticsearch(
						hosts=self.hosts,
						api_key=self.api_key
					)
			except ImportError:
				raise ImportError("elasticsearch package not installed. Install with: pip install elasticsearch[async]")

		return self._client

	async def _ensure_index(self):
		"""Ensure index exists with proper mappings."""
		exists = await self.client.indices.exists(index=self.index_name)
		if not exists:
			await self.client.indices.create(
				index=self.index_name,
				body={
					'settings': {
						'number_of_shards': 1,
						'number_of_replicas': 0,
						'analysis': {
							'analyzer': {
								'document_analyzer': {
									'type': 'custom',
									'tokenizer': 'standard',
									'filter': ['lowercase', 'asciifolding', 'snowball']
								}
							}
						}
					},
					'mappings': {
						'properties': {
							'document_id': {'type': 'keyword'},
							'title': {
								'type': 'text',
								'analyzer': 'document_analyzer',
								'fields': {
									'keyword': {'type': 'keyword'}
								}
							},
							'content': {
								'type': 'text',
								'analyzer': 'document_analyzer'
							},
							'document_type': {'type': 'keyword'},
							'document_type_id': {'type': 'keyword'},
							'tags': {'type': 'keyword'},
							'owner_id': {'type': 'keyword'},
							'owner_type': {'type': 'keyword'},
							'tenant_id': {'type': 'keyword'},
							'created_at': {'type': 'date'},
							'updated_at': {'type': 'date'},
							'custom_fields': {'type': 'object', 'dynamic': True},
							'embedding': {
								'type': 'dense_vector',
								'dims': 1024,
								'index': True,
								'similarity': 'cosine'
							}
						}
					}
				}
			)

	async def search(self, query: SearchQuery) -> SearchResult:
		"""Execute search using Elasticsearch."""
		start_time = time.time()

		await self._ensure_index()

		# Build query
		must_clauses = []
		filter_clauses = []

		# Full-text search
		if query.query.strip():
			must_clauses.append({
				'multi_match': {
					'query': query.query,
					'fields': ['title^3', 'content'],
					'type': 'best_fields',
					'fuzziness': 'AUTO'
				}
			})

		# Access control filter
		filter_clauses.append({
			'bool': {
				'should': [
					{'bool': {
						'must': [
							{'term': {'owner_type': 'user'}},
							{'term': {'owner_id': str(query.user_id)}}
						]
					}},
					# Note: Group membership would need separate query
				]
			}
		})

		# Document type filter
		if query.document_type_ids:
			filter_clauses.append({
				'terms': {'document_type_id': [str(t) for t in query.document_type_ids]}
			})

		# Tag filter
		if query.tag_names:
			filter_clauses.append({
				'terms': {'tags': query.tag_names}
			})

		# Owner filter
		if query.owner_id:
			filter_clauses.append({
				'term': {'owner_id': str(query.owner_id)}
			})

		# Date range filters
		date_filters = {}
		if query.created_after:
			date_filters.setdefault('created_at', {})['gte'] = query.created_after.isoformat()
		if query.created_before:
			date_filters.setdefault('created_at', {})['lte'] = query.created_before.isoformat()
		if query.updated_after:
			date_filters.setdefault('updated_at', {})['gte'] = query.updated_after.isoformat()
		if query.updated_before:
			date_filters.setdefault('updated_at', {})['lte'] = query.updated_before.isoformat()

		for field, range_query in date_filters.items():
			filter_clauses.append({'range': {field: range_query}})

		# Build final query
		es_query = {
			'bool': {
				'must': must_clauses if must_clauses else [{'match_all': {}}],
				'filter': filter_clauses
			}
		}

		# Build sort
		sort = []
		if query.sort_by == 'relevance':
			sort.append('_score')
		elif query.sort_by == 'created_at':
			sort.append({'created_at': {'order': query.sort_order}})
		elif query.sort_by == 'updated_at':
			sort.append({'updated_at': {'order': query.sort_order}})
		elif query.sort_by == 'title':
			sort.append({'title.keyword': {'order': query.sort_order}})

		# Execute search
		response = await self.client.search(
			index=self.index_name,
			body={
				'query': es_query,
				'sort': sort,
				'from': (query.page - 1) * query.page_size,
				'size': query.page_size,
				'highlight': {
					'fields': {
						'title': {},
						'content': {'fragment_size': 150, 'number_of_fragments': 3}
					}
				}
			}
		)

		# Parse response
		hits = []
		for hit in response['hits']['hits']:
			source = hit['_source']
			highlights = {}
			if 'highlight' in hit:
				highlights = hit['highlight']

			hits.append(SearchHit(
				document_id=UUID(source['document_id']),
				title=source['title'],
				score=hit['_score'] or 0,
				highlights=highlights,
				document_type=source.get('document_type'),
				tags=source.get('tags', []),
				owner_id=UUID(source['owner_id']) if source.get('owner_id') else None,
				owner_type=source.get('owner_type'),
				created_at=source.get('created_at'),
				updated_at=source.get('updated_at'),
				metadata=source.get('custom_fields', {})
			))

		total = response['hits']['total']['value']
		query_time = (time.time() - start_time) * 1000

		return SearchResult(
			hits=hits,
			total=total,
			page=query.page,
			page_size=query.page_size,
			query_time_ms=query_time,
			backend='elasticsearch'
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

		try:
			await self.client.index(
				index=self.index_name,
				id=str(document_id),
				body={
					'document_id': str(document_id),
					'title': title,
					'content': content,
					**metadata
				}
			)
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
		try:
			update_body = {}
			if title is not None:
				update_body['title'] = title
			if content is not None:
				update_body['content'] = content
			if metadata is not None:
				update_body.update(metadata)

			await self.client.update(
				index=self.index_name,
				id=str(document_id),
				body={'doc': update_body}
			)
			return True
		except Exception as e:
			logger.error(f"Failed to update document {document_id}: {e}")
			return False

	async def delete_document(self, document_id: UUID) -> bool:
		"""Delete a document from index."""
		try:
			await self.client.delete(
				index=self.index_name,
				id=str(document_id)
			)
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

		from elasticsearch.helpers import async_bulk

		actions = []
		for doc in documents:
			actions.append({
				'_index': self.index_name,
				'_id': str(doc['id']),
				'_source': {
					'document_id': str(doc['id']),
					'title': doc.get('title', ''),
					'content': doc.get('content', ''),
					**doc.get('metadata', {})
				}
			})

		try:
			success, errors = await async_bulk(self.client, actions)
			return success, len(errors)
		except Exception as e:
			logger.error(f"Bulk indexing failed: {e}")
			return 0, len(documents)

	async def get_stats(self) -> dict[str, Any]:
		"""Get index statistics."""
		try:
			stats = await self.client.indices.stats(index=self.index_name)
			return {
				'backend': 'elasticsearch',
				'document_count': stats['_all']['total']['docs']['count'],
				'index_size': stats['_all']['total']['store']['size_in_bytes']
			}
		except Exception as e:
			logger.error(f"Failed to get stats: {e}")
			return {'backend': 'elasticsearch', 'error': str(e)}

	async def health_check(self) -> bool:
		"""Check Elasticsearch health."""
		try:
			health = await self.client.cluster.health()
			return health['status'] in ('green', 'yellow')
		except Exception:
			return False

	async def similar_documents(
		self,
		document_id: UUID,
		user_id: UUID,
		limit: int = 10
	) -> list[SearchHit]:
		"""Find similar documents using more_like_this."""
		try:
			response = await self.client.search(
				index=self.index_name,
				body={
					'query': {
						'more_like_this': {
							'fields': ['title', 'content'],
							'like': [{'_index': self.index_name, '_id': str(document_id)}],
							'min_term_freq': 1,
							'max_query_terms': 25
						}
					},
					'size': limit
				}
			)

			hits = []
			for hit in response['hits']['hits']:
				source = hit['_source']
				hits.append(SearchHit(
					document_id=UUID(source['document_id']),
					title=source['title'],
					score=hit['_score'] or 0,
					document_type=source.get('document_type'),
					tags=source.get('tags', [])
				))

			return hits
		except Exception as e:
			logger.error(f"Similar documents search failed: {e}")
			return []

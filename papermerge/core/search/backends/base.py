from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Sequence
from uuid import UUID


class SearchBackendType(str, Enum):
	"""Supported search backend types."""
	POSTGRES = 'postgres'
	ELASTICSEARCH = 'elasticsearch'
	MEILISEARCH = 'meilisearch'


@dataclass
class SearchQuery:
	"""Search query parameters."""
	query: str
	user_id: UUID
	page: int = 1
	page_size: int = 20
	lang: str = 'eng'

	# Filters
	document_type_ids: list[UUID] | None = None
	tag_names: list[str] | None = None
	owner_id: UUID | None = None
	created_after: datetime | None = None
	created_before: datetime | None = None
	updated_after: datetime | None = None
	updated_before: datetime | None = None

	# Custom field filters
	custom_fields: dict[str, Any] | None = None

	# Sorting
	sort_by: str = 'relevance'
	sort_order: str = 'desc'

	# Semantic search
	use_semantic: bool = False
	semantic_weight: float = 0.5


@dataclass
class SearchHit:
	"""Single search result hit."""
	document_id: UUID
	title: str
	score: float
	highlights: dict[str, list[str]] = field(default_factory=dict)
	document_type: str | None = None
	tags: list[str] = field(default_factory=list)
	owner_id: UUID | None = None
	owner_type: str | None = None
	created_at: datetime | None = None
	updated_at: datetime | None = None
	metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchResult:
	"""Search result with pagination."""
	hits: list[SearchHit]
	total: int
	page: int
	page_size: int
	query_time_ms: float
	backend: str

	@property
	def num_pages(self) -> int:
		if self.total == 0:
			return 0
		return (self.total + self.page_size - 1) // self.page_size

	@property
	def has_next(self) -> bool:
		return self.page < self.num_pages

	@property
	def has_prev(self) -> bool:
		return self.page > 1


class SearchBackend(ABC):
	"""Abstract base class for search backends."""

	backend_type: SearchBackendType

	@abstractmethod
	async def search(self, query: SearchQuery) -> SearchResult:
		"""
		Execute a search query.

		Args:
			query: Search query parameters

		Returns:
			SearchResult with hits and pagination
		"""
		pass

	@abstractmethod
	async def index_document(
		self,
		document_id: UUID,
		title: str,
		content: str,
		metadata: dict[str, Any]
	) -> bool:
		"""
		Index a document for search.

		Args:
			document_id: Document UUID
			title: Document title
			content: Full text content
			metadata: Additional metadata (tags, document_type, etc.)

		Returns:
			True if indexed successfully
		"""
		pass

	@abstractmethod
	async def update_document(
		self,
		document_id: UUID,
		title: str | None = None,
		content: str | None = None,
		metadata: dict[str, Any] | None = None
	) -> bool:
		"""
		Update an indexed document.

		Args:
			document_id: Document UUID
			title: Updated title (optional)
			content: Updated content (optional)
			metadata: Updated metadata (optional)

		Returns:
			True if updated successfully
		"""
		pass

	@abstractmethod
	async def delete_document(self, document_id: UUID) -> bool:
		"""
		Remove a document from the search index.

		Args:
			document_id: Document UUID

		Returns:
			True if deleted successfully
		"""
		pass

	@abstractmethod
	async def bulk_index(
		self,
		documents: Sequence[dict[str, Any]]
	) -> tuple[int, int]:
		"""
		Bulk index multiple documents.

		Args:
			documents: List of document dicts with id, title, content, metadata

		Returns:
			Tuple of (success_count, failure_count)
		"""
		pass

	@abstractmethod
	async def get_stats(self) -> dict[str, Any]:
		"""
		Get search index statistics.

		Returns:
			Dictionary with index stats (count, size, etc.)
		"""
		pass

	@abstractmethod
	async def health_check(self) -> bool:
		"""
		Check if search backend is healthy.

		Returns:
			True if backend is available and healthy
		"""
		pass

	async def suggest(
		self,
		prefix: str,
		user_id: UUID,
		limit: int = 10
	) -> list[str]:
		"""
		Get search suggestions based on prefix.

		Args:
			prefix: Search prefix
			user_id: User ID for access filtering
			limit: Maximum suggestions

		Returns:
			List of suggested search terms
		"""
		return []

	async def similar_documents(
		self,
		document_id: UUID,
		user_id: UUID,
		limit: int = 10
	) -> list[SearchHit]:
		"""
		Find documents similar to the given document.

		Args:
			document_id: Reference document UUID
			user_id: User ID for access filtering
			limit: Maximum results

		Returns:
			List of similar document hits
		"""
		return []

import logging
from functools import lru_cache

from .backends.base import SearchBackend, SearchBackendType

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_search_backend(
	backend_type: SearchBackendType | str | None = None,
	**kwargs
) -> SearchBackend:
	"""
	Factory function to get a search backend instance.

	Args:
		backend_type: Type of search backend (defaults to config)
		**kwargs: Backend-specific configuration options

	Returns:
		SearchBackend instance
	"""
	from papermerge.core.config import get_settings

	settings = get_settings()

	if backend_type is None:
		backend_type = getattr(settings, 'search_backend', 'postgres')

	if isinstance(backend_type, str):
		try:
			backend_type = SearchBackendType(backend_type.lower())
		except ValueError:
			logger.warning(f"Unknown search backend: {backend_type}, falling back to postgres")
			backend_type = SearchBackendType.POSTGRES

	if backend_type == SearchBackendType.POSTGRES:
		from papermerge.core.db.engine import async_session_factory
		from .backends.postgres import PostgresSearchBackend
		return PostgresSearchBackend(session_factory=async_session_factory)

	elif backend_type == SearchBackendType.ELASTICSEARCH:
		from .backends.elasticsearch import ElasticsearchBackend

		hosts = kwargs.get('hosts') or getattr(settings, 'elasticsearch_hosts', None)
		api_key = kwargs.get('api_key') or getattr(settings, 'elasticsearch_api_key', None)
		index_name = kwargs.get('index_name') or getattr(settings, 'elasticsearch_index', 'documents')

		if hosts and isinstance(hosts, str):
			hosts = [h.strip() for h in hosts.split(',')]

		return ElasticsearchBackend(
			hosts=hosts,
			api_key=api_key,
			index_name=index_name
		)

	elif backend_type == SearchBackendType.MEILISEARCH:
		from .backends.meilisearch import MeilisearchBackend

		host = kwargs.get('host') or getattr(settings, 'meilisearch_host', 'http://localhost:7700')
		api_key = kwargs.get('api_key') or getattr(settings, 'meilisearch_api_key', None)
		index_name = kwargs.get('index_name') or getattr(settings, 'meilisearch_index', 'documents')

		return MeilisearchBackend(
			host=host,
			api_key=api_key,
			index_name=index_name
		)

	else:
		raise ValueError(f"Unsupported search backend: {backend_type}")


def get_available_backends() -> dict[str, dict]:
	"""Get information about all available search backends."""
	backends = {}

	for backend_type in SearchBackendType:
		try:
			backend = get_search_backend(backend_type)
			backends[backend_type.value] = {
				'type': backend_type.value,
				'available': True,
				'description': backend.__class__.__doc__ or ''
			}
		except Exception as e:
			backends[backend_type.value] = {
				'type': backend_type.value,
				'available': False,
				'error': str(e)
			}

	return backends

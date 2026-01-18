import logging
import time
from typing import Any

import httpx

from .service import EmbeddingService, EmbeddingResult

logger = logging.getLogger(__name__)


class OllamaEmbeddings(EmbeddingService):
	"""Ollama embedding service using local models."""

	DEFAULT_MODEL = 'nomic-embed-text'
	DIMENSION_MAP = {
		'nomic-embed-text': 768,
		'all-minilm': 384,
		'mxbai-embed-large': 1024,
		'snowflake-arctic-embed': 1024,
		'bge-m3': 1024,
	}

	def __init__(
		self,
		base_url: str = 'http://localhost:11434',
		model: str = DEFAULT_MODEL,
		timeout: float = 60.0
	):
		"""
		Initialize Ollama embeddings.

		Args:
			base_url: Ollama API URL
			model: Embedding model name
			timeout: Request timeout in seconds
		"""
		self.base_url = base_url.rstrip('/')
		self.model = model
		self.timeout = timeout
		self._client = httpx.AsyncClient(timeout=timeout)

	async def close(self):
		"""Close HTTP client."""
		await self._client.aclose()

	async def __aenter__(self):
		return self

	async def __aexit__(self, exc_type, exc_val, exc_tb):
		await self.close()

	async def embed_text(self, text: str) -> EmbeddingResult:
		"""Generate embedding for a single text."""
		start_time = time.time()

		try:
			response = await self._client.post(
				f"{self.base_url}/api/embeddings",
				json={
					'model': self.model,
					'prompt': text
				}
			)
			response.raise_for_status()
			data = response.json()

			embedding = data.get('embedding', [])
			processing_time = (time.time() - start_time) * 1000

			return EmbeddingResult(
				embedding=embedding,
				model=self.model,
				dimension=len(embedding),
				processing_time_ms=processing_time
			)

		except Exception as e:
			logger.error(f"Embedding generation failed: {e}")
			raise

	async def embed_texts(self, texts: list[str]) -> list[EmbeddingResult]:
		"""Generate embeddings for multiple texts."""
		results = []
		for text in texts:
			result = await self.embed_text(text)
			results.append(result)
		return results

	async def embed_query(self, query: str) -> EmbeddingResult:
		"""Generate embedding for a search query."""
		# For most models, query and document embeddings are the same
		# Some models like nomic-embed-text support task prefixes
		if self.model == 'nomic-embed-text':
			query = f"search_query: {query}"
		return await self.embed_text(query)

	def get_dimension(self) -> int:
		"""Return embedding dimension for this model."""
		return self.DIMENSION_MAP.get(self.model, 768)

	def get_model_name(self) -> str:
		"""Return the model name."""
		return self.model

	async def is_available(self) -> bool:
		"""Check if Ollama server is available with the embedding model."""
		try:
			response = await self._client.get(f"{self.base_url}/api/tags")
			if response.status_code != 200:
				return False

			models = response.json().get('models', [])
			model_names = [m.get('name', '').split(':')[0] for m in models]
			return self.model.split(':')[0] in model_names
		except Exception:
			return False

	async def pull_model(self) -> bool:
		"""Pull the embedding model if not present."""
		try:
			response = await self._client.post(
				f"{self.base_url}/api/pull",
				json={'name': self.model},
				timeout=600.0
			)
			return response.status_code == 200
		except Exception as e:
			logger.error(f"Failed to pull model {self.model}: {e}")
			return False


def get_embedding_service(
	provider: str = 'ollama',
	**kwargs
) -> EmbeddingService:
	"""
	Factory function to get an embedding service.

	Args:
		provider: Provider name ('ollama', 'openai', etc.)
		**kwargs: Provider-specific configuration

	Returns:
		EmbeddingService instance
	"""
	if provider == 'ollama':
		return OllamaEmbeddings(
			base_url=kwargs.get('base_url', 'http://localhost:11434'),
			model=kwargs.get('model', 'nomic-embed-text'),
			timeout=kwargs.get('timeout', 60.0)
		)
	else:
		raise ValueError(f"Unsupported embedding provider: {provider}")

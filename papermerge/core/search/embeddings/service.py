import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class EmbeddingResult:
	"""Result from embedding generation."""
	embedding: list[float]
	model: str
	dimension: int
	tokens: int = 0
	processing_time_ms: float = 0
	metadata: dict[str, Any] = field(default_factory=dict)


class EmbeddingService(ABC):
	"""Abstract base class for embedding services."""

	@abstractmethod
	async def embed_text(self, text: str) -> EmbeddingResult:
		"""
		Generate embedding for a single text.

		Args:
			text: Text to embed

		Returns:
			EmbeddingResult with vector and metadata
		"""
		pass

	@abstractmethod
	async def embed_texts(self, texts: list[str]) -> list[EmbeddingResult]:
		"""
		Generate embeddings for multiple texts.

		Args:
			texts: List of texts to embed

		Returns:
			List of EmbeddingResult objects
		"""
		pass

	@abstractmethod
	async def embed_query(self, query: str) -> EmbeddingResult:
		"""
		Generate embedding for a search query.

		Some models use different embeddings for queries vs documents.

		Args:
			query: Search query text

		Returns:
			EmbeddingResult with vector and metadata
		"""
		pass

	@abstractmethod
	def get_dimension(self) -> int:
		"""Return embedding dimension for this model."""
		pass

	@abstractmethod
	def get_model_name(self) -> str:
		"""Return the model name."""
		pass

	@abstractmethod
	async def is_available(self) -> bool:
		"""Check if embedding service is available."""
		pass

	def chunk_text(
		self,
		text: str,
		chunk_size: int = 500,
		overlap: int = 50
	) -> list[str]:
		"""
		Split text into overlapping chunks for embedding.

		Args:
			text: Text to chunk
			chunk_size: Maximum characters per chunk
			overlap: Character overlap between chunks

		Returns:
			List of text chunks
		"""
		if len(text) <= chunk_size:
			return [text]

		chunks = []
		start = 0

		while start < len(text):
			end = start + chunk_size

			# Try to break at sentence boundary
			if end < len(text):
				# Look for sentence end
				for sep in ['. ', '! ', '? ', '\n\n', '\n']:
					last_sep = text[start:end].rfind(sep)
					if last_sep > chunk_size // 2:
						end = start + last_sep + len(sep)
						break

			chunk = text[start:end].strip()
			if chunk:
				chunks.append(chunk)

			start = end - overlap

		return chunks

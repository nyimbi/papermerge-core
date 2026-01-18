# (c) Copyright Datacraft, 2026
"""Abstract storage backend interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import AsyncIterator, BinaryIO


class StorageTier(str, Enum):
	"""Storage tier classification for lifecycle management."""
	HOT = "hot"
	WARM = "warm"
	COLD = "cold"
	ARCHIVE = "archive"


@dataclass
class StorageObject:
	"""Metadata about a stored object."""
	key: str
	size: int
	last_modified: datetime
	etag: str | None = None
	content_type: str | None = None
	tier: StorageTier = StorageTier.HOT
	metadata: dict[str, str] | None = None


@dataclass
class UploadResult:
	"""Result of an upload operation."""
	key: str
	etag: str
	version_id: str | None = None
	size: int = 0


@dataclass
class PresignedUrl:
	"""Pre-signed URL for direct access."""
	url: str
	expires_at: datetime
	method: str = "GET"


class StorageBackend(ABC):
	"""Abstract base class for storage backends."""

	@abstractmethod
	async def put(
		self,
		key: str,
		data: bytes | BinaryIO,
		content_type: str | None = None,
		metadata: dict[str, str] | None = None,
		tier: StorageTier = StorageTier.HOT,
	) -> UploadResult:
		"""Upload data to storage.

		Args:
			key: Object key/path
			data: Binary data or file-like object
			content_type: MIME type
			metadata: Custom metadata
			tier: Storage tier

		Returns:
			Upload result with ETag and version
		"""
		...

	@abstractmethod
	async def put_file(
		self,
		key: str,
		file_path: Path,
		content_type: str | None = None,
		metadata: dict[str, str] | None = None,
		tier: StorageTier = StorageTier.HOT,
	) -> UploadResult:
		"""Upload a file to storage.

		Args:
			key: Object key/path
			file_path: Local file path
			content_type: MIME type (auto-detected if None)
			metadata: Custom metadata
			tier: Storage tier

		Returns:
			Upload result
		"""
		...

	@abstractmethod
	async def get(self, key: str) -> bytes:
		"""Download object data.

		Args:
			key: Object key/path

		Returns:
			Object data as bytes

		Raises:
			ObjectNotFoundError: If object doesn't exist
		"""
		...

	@abstractmethod
	async def get_stream(self, key: str) -> AsyncIterator[bytes]:
		"""Stream object data in chunks.

		Args:
			key: Object key/path

		Yields:
			Data chunks

		Raises:
			ObjectNotFoundError: If object doesn't exist
		"""
		...

	@abstractmethod
	async def get_to_file(self, key: str, file_path: Path) -> None:
		"""Download object to a local file.

		Args:
			key: Object key/path
			file_path: Destination file path

		Raises:
			ObjectNotFoundError: If object doesn't exist
		"""
		...

	@abstractmethod
	async def delete(self, key: str) -> None:
		"""Delete an object.

		Args:
			key: Object key/path
		"""
		...

	@abstractmethod
	async def delete_many(self, keys: list[str]) -> list[str]:
		"""Delete multiple objects.

		Args:
			keys: List of object keys

		Returns:
			List of keys that failed to delete
		"""
		...

	@abstractmethod
	async def exists(self, key: str) -> bool:
		"""Check if an object exists.

		Args:
			key: Object key/path

		Returns:
			True if object exists
		"""
		...

	@abstractmethod
	async def head(self, key: str) -> StorageObject:
		"""Get object metadata without downloading content.

		Args:
			key: Object key/path

		Returns:
			Object metadata

		Raises:
			ObjectNotFoundError: If object doesn't exist
		"""
		...

	@abstractmethod
	async def list_objects(
		self,
		prefix: str = "",
		max_keys: int = 1000,
		continuation_token: str | None = None,
	) -> tuple[list[StorageObject], str | None]:
		"""List objects with optional prefix.

		Args:
			prefix: Filter by key prefix
			max_keys: Maximum objects to return
			continuation_token: Token for pagination

		Returns:
			Tuple of (objects, next_continuation_token)
		"""
		...

	@abstractmethod
	async def copy(
		self,
		source_key: str,
		dest_key: str,
		metadata: dict[str, str] | None = None,
	) -> UploadResult:
		"""Copy an object within the same bucket.

		Args:
			source_key: Source object key
			dest_key: Destination object key
			metadata: New metadata (copies source if None)

		Returns:
			Upload result for new object
		"""
		...

	@abstractmethod
	async def move(
		self,
		source_key: str,
		dest_key: str,
		metadata: dict[str, str] | None = None,
	) -> UploadResult:
		"""Move an object within the same bucket.

		Args:
			source_key: Source object key
			dest_key: Destination object key
			metadata: New metadata

		Returns:
			Upload result for new object
		"""
		...

	@abstractmethod
	async def set_tier(self, key: str, tier: StorageTier) -> None:
		"""Change object storage tier.

		Args:
			key: Object key/path
			tier: New storage tier
		"""
		...

	@abstractmethod
	async def generate_presigned_url(
		self,
		key: str,
		expires_in: int = 3600,
		method: str = "GET",
	) -> PresignedUrl:
		"""Generate a pre-signed URL for direct access.

		Args:
			key: Object key/path
			expires_in: URL validity in seconds
			method: HTTP method (GET or PUT)

		Returns:
			Pre-signed URL object
		"""
		...

	@abstractmethod
	async def generate_presigned_upload_url(
		self,
		key: str,
		content_type: str,
		expires_in: int = 3600,
		metadata: dict[str, str] | None = None,
	) -> PresignedUrl:
		"""Generate a pre-signed URL for direct upload.

		Args:
			key: Object key/path
			content_type: Expected content type
			expires_in: URL validity in seconds
			metadata: Metadata to set on upload

		Returns:
			Pre-signed URL for PUT upload
		"""
		...


class ObjectNotFoundError(Exception):
	"""Raised when requested object doesn't exist."""

	def __init__(self, key: str):
		self.key = key
		super().__init__(f"Object not found: {key}")


class StorageError(Exception):
	"""General storage operation error."""

	def __init__(self, message: str, cause: Exception | None = None):
		self.cause = cause
		super().__init__(message)

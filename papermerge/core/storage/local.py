# (c) Copyright Datacraft, 2026
"""Local filesystem storage backend for development and testing."""

import hashlib
import json
import mimetypes
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, BinaryIO

import aiofiles
import aiofiles.os

from .base import (
	ObjectNotFoundError,
	PresignedUrl,
	StorageBackend,
	StorageError,
	StorageObject,
	StorageTier,
	UploadResult,
)


class LocalStorageBackend(StorageBackend):
	"""Local filesystem storage backend for development and testing."""

	def __init__(self, base_path: str | Path, prefix: str = ""):
		"""Initialize local storage backend.

		Args:
			base_path: Base directory for storage
			prefix: Optional key prefix
		"""
		self.base_path = Path(base_path)
		self.prefix = prefix.strip("/")
		self.metadata_dir = self.base_path / ".metadata"

		self.base_path.mkdir(parents=True, exist_ok=True)
		self.metadata_dir.mkdir(parents=True, exist_ok=True)

	def _full_path(self, key: str) -> Path:
		"""Get full filesystem path for key."""
		if self.prefix:
			return self.base_path / self.prefix / key.lstrip("/")
		return self.base_path / key.lstrip("/")

	def _metadata_path(self, key: str) -> Path:
		"""Get metadata file path for key."""
		safe_key = key.replace("/", "__")
		if self.prefix:
			safe_key = f"{self.prefix}__{safe_key}"
		return self.metadata_dir / f"{safe_key}.json"

	def _compute_etag(self, data: bytes) -> str:
		"""Compute MD5 ETag for data."""
		return hashlib.md5(data).hexdigest()

	async def _save_metadata(
		self,
		key: str,
		content_type: str | None,
		metadata: dict[str, str] | None,
		tier: StorageTier,
	) -> None:
		"""Save object metadata to file."""
		meta = {
			"content_type": content_type,
			"metadata": metadata or {},
			"tier": tier.value,
		}
		async with aiofiles.open(self._metadata_path(key), "w") as f:
			await f.write(json.dumps(meta))

	async def _load_metadata(self, key: str) -> dict:
		"""Load object metadata from file."""
		path = self._metadata_path(key)
		if path.exists():
			async with aiofiles.open(path, "r") as f:
				return json.loads(await f.read())
		return {"content_type": None, "metadata": {}, "tier": StorageTier.HOT.value}

	async def put(
		self,
		key: str,
		data: bytes | BinaryIO,
		content_type: str | None = None,
		metadata: dict[str, str] | None = None,
		tier: StorageTier = StorageTier.HOT,
	) -> UploadResult:
		path = self._full_path(key)
		body = data if isinstance(data, bytes) else data.read()

		try:
			path.parent.mkdir(parents=True, exist_ok=True)
			async with aiofiles.open(path, "wb") as f:
				await f.write(body)

			await self._save_metadata(key, content_type, metadata, tier)

			return UploadResult(
				key=key,
				etag=self._compute_etag(body),
				size=len(body),
			)
		except Exception as e:
			raise StorageError(f"Failed to upload {key}", e) from e

	async def put_file(
		self,
		key: str,
		file_path: Path,
		content_type: str | None = None,
		metadata: dict[str, str] | None = None,
		tier: StorageTier = StorageTier.HOT,
	) -> UploadResult:
		if not content_type:
			content_type, _ = mimetypes.guess_type(str(file_path))

		dest_path = self._full_path(key)

		try:
			dest_path.parent.mkdir(parents=True, exist_ok=True)
			shutil.copy2(file_path, dest_path)

			await self._save_metadata(key, content_type, metadata, tier)

			async with aiofiles.open(dest_path, "rb") as f:
				data = await f.read()

			return UploadResult(
				key=key,
				etag=self._compute_etag(data),
				size=dest_path.stat().st_size,
			)
		except Exception as e:
			raise StorageError(f"Failed to upload file {key}", e) from e

	async def get(self, key: str) -> bytes:
		path = self._full_path(key)

		if not path.exists():
			raise ObjectNotFoundError(key)

		try:
			async with aiofiles.open(path, "rb") as f:
				return await f.read()
		except Exception as e:
			raise StorageError(f"Failed to get {key}", e) from e

	async def get_stream(self, key: str) -> AsyncIterator[bytes]:
		path = self._full_path(key)

		if not path.exists():
			raise ObjectNotFoundError(key)

		try:
			async with aiofiles.open(path, "rb") as f:
				while chunk := await f.read(8192):
					yield chunk
		except Exception as e:
			raise StorageError(f"Failed to stream {key}", e) from e

	async def get_to_file(self, key: str, file_path: Path) -> None:
		path = self._full_path(key)

		if not path.exists():
			raise ObjectNotFoundError(key)

		try:
			file_path.parent.mkdir(parents=True, exist_ok=True)
			shutil.copy2(path, file_path)
		except Exception as e:
			raise StorageError(f"Failed to download {key}", e) from e

	async def delete(self, key: str) -> None:
		path = self._full_path(key)
		meta_path = self._metadata_path(key)

		try:
			if path.exists():
				await aiofiles.os.remove(path)
			if meta_path.exists():
				await aiofiles.os.remove(meta_path)
		except Exception as e:
			raise StorageError(f"Failed to delete {key}", e) from e

	async def delete_many(self, keys: list[str]) -> list[str]:
		failed: list[str] = []
		for key in keys:
			try:
				await self.delete(key)
			except Exception:
				failed.append(key)
		return failed

	async def exists(self, key: str) -> bool:
		return self._full_path(key).exists()

	async def head(self, key: str) -> StorageObject:
		path = self._full_path(key)

		if not path.exists():
			raise ObjectNotFoundError(key)

		try:
			stat = path.stat()
			meta = await self._load_metadata(key)

			async with aiofiles.open(path, "rb") as f:
				data = await f.read()

			return StorageObject(
				key=key,
				size=stat.st_size,
				last_modified=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
				etag=self._compute_etag(data),
				content_type=meta.get("content_type"),
				tier=StorageTier(meta.get("tier", "hot")),
				metadata=meta.get("metadata"),
			)
		except ObjectNotFoundError:
			raise
		except Exception as e:
			raise StorageError(f"Failed to head {key}", e) from e

	async def list_objects(
		self,
		prefix: str = "",
		max_keys: int = 1000,
		continuation_token: str | None = None,
	) -> tuple[list[StorageObject], str | None]:
		search_path = self._full_path(prefix) if prefix else self.base_path
		if self.prefix and not prefix:
			search_path = self.base_path / self.prefix

		objects: list[StorageObject] = []
		start_after = continuation_token or ""

		try:
			if search_path.is_file():
				files = [search_path]
			elif search_path.exists():
				files = sorted(search_path.rglob("*"))
			else:
				files = []

			for path in files:
				if not path.is_file() or path.name.endswith(".json"):
					continue

				rel_path = path.relative_to(self.base_path)
				key = str(rel_path)

				if self.prefix and key.startswith(self.prefix + "/"):
					key = key[len(self.prefix) + 1 :]

				if key <= start_after:
					continue

				if len(objects) >= max_keys:
					return objects, key

				stat = path.stat()
				meta = await self._load_metadata(key)

				async with aiofiles.open(path, "rb") as f:
					data = await f.read()

				objects.append(
					StorageObject(
						key=key,
						size=stat.st_size,
						last_modified=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
						etag=self._compute_etag(data),
						tier=StorageTier(meta.get("tier", "hot")),
					)
				)

			return objects, None

		except Exception as e:
			raise StorageError("Failed to list objects", e) from e

	async def copy(
		self,
		source_key: str,
		dest_key: str,
		metadata: dict[str, str] | None = None,
	) -> UploadResult:
		source_path = self._full_path(source_key)
		dest_path = self._full_path(dest_key)

		if not source_path.exists():
			raise ObjectNotFoundError(source_key)

		try:
			dest_path.parent.mkdir(parents=True, exist_ok=True)
			shutil.copy2(source_path, dest_path)

			source_meta = await self._load_metadata(source_key)
			if metadata is not None:
				source_meta["metadata"] = metadata

			await self._save_metadata(
				dest_key,
				source_meta.get("content_type"),
				source_meta.get("metadata"),
				StorageTier(source_meta.get("tier", "hot")),
			)

			async with aiofiles.open(dest_path, "rb") as f:
				data = await f.read()

			return UploadResult(
				key=dest_key,
				etag=self._compute_etag(data),
				size=len(data),
			)
		except ObjectNotFoundError:
			raise
		except Exception as e:
			raise StorageError(f"Failed to copy {source_key} to {dest_key}", e) from e

	async def move(
		self,
		source_key: str,
		dest_key: str,
		metadata: dict[str, str] | None = None,
	) -> UploadResult:
		result = await self.copy(source_key, dest_key, metadata)
		await self.delete(source_key)
		return result

	async def set_tier(self, key: str, tier: StorageTier) -> None:
		path = self._full_path(key)

		if not path.exists():
			raise ObjectNotFoundError(key)

		meta = await self._load_metadata(key)
		meta["tier"] = tier.value

		async with aiofiles.open(self._metadata_path(key), "w") as f:
			await f.write(json.dumps(meta))

	async def generate_presigned_url(
		self,
		key: str,
		expires_in: int = 3600,
		method: str = "GET",
	) -> PresignedUrl:
		# Local backend returns file:// URL for development
		path = self._full_path(key)
		return PresignedUrl(
			url=f"file://{path}",
			expires_at=datetime.now(timezone.utc).replace(
				second=datetime.now(timezone.utc).second + expires_in
			),
			method=method.upper(),
		)

	async def generate_presigned_upload_url(
		self,
		key: str,
		content_type: str,
		expires_in: int = 3600,
		metadata: dict[str, str] | None = None,
	) -> PresignedUrl:
		path = self._full_path(key)
		return PresignedUrl(
			url=f"file://{path}",
			expires_at=datetime.now(timezone.utc).replace(
				second=datetime.now(timezone.utc).second + expires_in
			),
			method="PUT",
		)

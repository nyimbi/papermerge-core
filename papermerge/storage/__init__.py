import os
from pathlib import Path

from papermerge.storage.base import StorageBackend, get_storage_backend


def abs_path(path: str | Path) -> Path:
	"""Convert relative path to absolute path using MEDIA_ROOT."""
	if isinstance(path, str):
		path = Path(path)
	if path.is_absolute():
		return path
	media_root = Path(os.environ.get("PM_MEDIA_ROOT", "/app/media"))
	return media_root / path


def get_storage_instance() -> StorageBackend:
	"""Alias for get_storage_backend for backward compatibility."""
	return get_storage_backend()


__all__ = ["StorageBackend", "get_storage_backend", "abs_path", "get_storage_instance"]

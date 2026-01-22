# (c) Copyright Datacraft, 2026
"""Storage backend abstraction layer."""
import os
from pathlib import Path

from .base import StorageBackend, StorageTier
from .factory import get_storage_backend, StorageConfig

MEDIA_ROOT = os.environ.get("PAPERMERGE__MAIN__MEDIA_ROOT", os.environ.get("PM_MEDIA_ROOT", "./media"))


def abs_path(path: str | Path) -> Path:
	"""Convert relative path to absolute path using MEDIA_ROOT."""
	if isinstance(path, str):
		path = Path(path)
	if path.is_absolute():
		return path
	return Path(MEDIA_ROOT) / path


def get_storage_instance() -> StorageBackend:
	"""Get configured storage backend instance."""
	return get_storage_backend()


__all__ = [
	"StorageBackend",
	"StorageTier",
	"get_storage_backend",
	"StorageConfig",
	"abs_path",
	"get_storage_instance",
]

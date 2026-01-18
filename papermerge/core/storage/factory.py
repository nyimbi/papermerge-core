# (c) Copyright Datacraft, 2026
"""Storage backend factory."""

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from .base import StorageBackend


class StorageBackendType(str, Enum):
	"""Supported storage backend types."""
	LOCAL = "local"
	LINODE = "linode"
	S3 = "s3"
	R2 = "r2"


@dataclass
class StorageConfig:
	"""Storage configuration."""
	backend: StorageBackendType = StorageBackendType.LOCAL

	# Local backend settings
	local_path: str = "/var/lib/papermerge/storage"

	# S3-compatible settings (Linode, AWS S3, Cloudflare R2)
	access_key_id: str = ""
	secret_access_key: str = ""
	bucket: str = ""
	prefix: str = ""

	# Linode specific
	linode_cluster_id: str = "us-east-1"

	# AWS S3 specific
	s3_region: str = "us-east-1"
	s3_endpoint_url: str | None = None

	# Cloudflare R2 specific
	r2_account_id: str = ""

	@classmethod
	def from_env(cls) -> "StorageConfig":
		"""Create config from environment variables."""
		backend_str = os.getenv("PM_STORAGE_BACKEND", "local").lower()

		try:
			backend = StorageBackendType(backend_str)
		except ValueError:
			backend = StorageBackendType.LOCAL

		return cls(
			backend=backend,
			local_path=os.getenv("PM_STORAGE_LOCAL_PATH", "/var/lib/papermerge/storage"),
			access_key_id=os.getenv("PM_STORAGE_ACCESS_KEY_ID", os.getenv("AWS_ACCESS_KEY_ID", "")),
			secret_access_key=os.getenv("PM_STORAGE_SECRET_ACCESS_KEY", os.getenv("AWS_SECRET_ACCESS_KEY", "")),
			bucket=os.getenv("PM_STORAGE_BUCKET", ""),
			prefix=os.getenv("PM_STORAGE_PREFIX", ""),
			linode_cluster_id=os.getenv("LINODE_CLUSTER_ID", "us-east-1"),
			s3_region=os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1")),
			s3_endpoint_url=os.getenv("PM_STORAGE_S3_ENDPOINT_URL"),
			r2_account_id=os.getenv("CLOUDFLARE_ACCOUNT_ID", ""),
		)


_storage_backend: StorageBackend | None = None


def get_storage_backend(config: StorageConfig | None = None) -> StorageBackend:
	"""Get configured storage backend.

	Args:
		config: Storage configuration (uses env vars if None)

	Returns:
		Storage backend instance
	"""
	global _storage_backend

	if _storage_backend is not None and config is None:
		return _storage_backend

	if config is None:
		config = StorageConfig.from_env()

	backend = _create_backend(config)

	if _storage_backend is None:
		_storage_backend = backend

	return backend


def _create_backend(config: StorageConfig) -> StorageBackend:
	"""Create storage backend from config."""
	if config.backend == StorageBackendType.LOCAL:
		from .local import LocalStorageBackend
		return LocalStorageBackend(
			base_path=config.local_path,
			prefix=config.prefix,
		)

	elif config.backend == StorageBackendType.LINODE:
		from .linode import LinodeStorageBackend
		return LinodeStorageBackend(
			access_key_id=config.access_key_id,
			secret_access_key=config.secret_access_key,
			bucket=config.bucket,
			cluster_id=config.linode_cluster_id,
			prefix=config.prefix,
		)

	elif config.backend == StorageBackendType.S3:
		from .s3 import S3StorageBackend
		return S3StorageBackend(
			access_key_id=config.access_key_id,
			secret_access_key=config.secret_access_key,
			bucket=config.bucket,
			region=config.s3_region,
			endpoint_url=config.s3_endpoint_url,
			prefix=config.prefix,
		)

	elif config.backend == StorageBackendType.R2:
		from .r2 import R2StorageBackend
		return R2StorageBackend(
			access_key_id=config.access_key_id,
			secret_access_key=config.secret_access_key,
			bucket=config.bucket,
			account_id=config.r2_account_id,
			prefix=config.prefix,
		)

	else:
		raise ValueError(f"Unknown storage backend: {config.backend}")


def reset_storage_backend() -> None:
	"""Reset cached storage backend (for testing)."""
	global _storage_backend
	_storage_backend = None

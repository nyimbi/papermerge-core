# (c) Copyright Datacraft, 2026
"""Tests for storage backend factory, including MinIO."""
import os
import pytest

os.environ.setdefault("PM_DB_URL", "postgresql+asyncpg://x:x@localhost/x")

from papermerge.core.storage.factory import (
    StorageConfig,
    StorageBackendType,
    _create_backend,
    get_storage_backend,
    reset_storage_backend,
)
from papermerge.core.storage.local import LocalStorageBackend

try:
    from papermerge.core.storage.s3 import S3StorageBackend
    HAS_AIOBOTO3 = True
except ImportError:
    HAS_AIOBOTO3 = False

skip_no_aioboto3 = pytest.mark.skipif(not HAS_AIOBOTO3, reason="aioboto3 not installed")


def test_local_backend_created_by_default():
    reset_storage_backend()
    config = StorageConfig(backend=StorageBackendType.LOCAL, local_path="/tmp/test-storage")
    backend = _create_backend(config)
    assert isinstance(backend, LocalStorageBackend)


@skip_no_aioboto3
def test_minio_backend_creates_s3_backend():
    config = StorageConfig(
        backend=StorageBackendType.MINIO,
        access_key_id="pjsadmin",
        secret_access_key="secret",
        bucket="darchiva",
        minio_endpoint="http://localhost:9000",
    )
    backend = _create_backend(config)
    assert isinstance(backend, S3StorageBackend)
    assert backend.bucket == "darchiva"
    assert backend._endpoint_url == "http://localhost:9000"


def test_minio_from_env(monkeypatch):
    monkeypatch.setenv("PM_STORAGE_BACKEND", "minio")
    monkeypatch.setenv("PM_MINIO_ACCESS_KEY", "test-access")
    monkeypatch.setenv("PM_MINIO_SECRET_KEY", "test-secret")
    monkeypatch.setenv("PM_MINIO_BUCKET", "test-bucket")
    monkeypatch.setenv("PM_MINIO_ENDPOINT", "http://localhost:9000")

    config = StorageConfig.from_env()
    assert config.backend == StorageBackendType.MINIO
    assert config.access_key_id == "test-access"
    assert config.secret_access_key == "test-secret"
    assert config.bucket == "test-bucket"
    assert config.minio_endpoint == "http://localhost:9000"


@skip_no_aioboto3
def test_s3_backend_uses_s3_class():
    config = StorageConfig(
        backend=StorageBackendType.S3,
        access_key_id="key",
        secret_access_key="secret",
        bucket="mybucket",
        s3_region="us-east-1",
    )
    backend = _create_backend(config)
    assert isinstance(backend, S3StorageBackend)
    assert backend._endpoint_url is None


def test_unknown_backend_raises():
    config = StorageConfig.__new__(StorageConfig)
    config.backend = "unknown-backend"
    with pytest.raises((ValueError, Exception)):
        _create_backend(config)


def test_get_storage_backend_caches(monkeypatch):
    """get_storage_backend() without explicit config returns same singleton."""
    reset_storage_backend()
    # Point env at LOCAL so from_env() returns a valid config
    monkeypatch.setenv("PM_STORAGE_BACKEND", "local")
    monkeypatch.setenv("PM_STORAGE_LOCAL_PATH", "/tmp/cache-test")
    b1 = get_storage_backend()   # seeds cache
    b2 = get_storage_backend()   # must return cached instance
    assert b1 is b2
    reset_storage_backend()

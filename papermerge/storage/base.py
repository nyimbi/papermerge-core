from abc import ABC, abstractmethod
from uuid import UUID

from fastapi import UploadFile

from papermerge.core.types import ImagePreviewSize


class StorageBackend(ABC):
    """Abstract base class for cloud storage backends."""

    DEFAULT_VALID_FOR_SECONDS = 600

    @abstractmethod
    def sign_url(self, url: str, valid_for: int = DEFAULT_VALID_FOR_SECONDS) -> str:
        """
        Sign a URL for secure access.

        :param url: The URL or resource path to sign
        :param valid_for: Number of seconds the URL will be valid for
        :return: Signed URL
        """
        pass

    @abstractmethod
    def doc_thumbnail_signed_url(self, uid: UUID) -> str:
        """Generate a signed URL for a document thumbnail."""
        pass

    @abstractmethod
    def page_image_jpg_signed_url(self, uid: UUID, size: ImagePreviewSize) -> str:
        """Generate a signed URL for a page preview image."""
        pass

    @abstractmethod
    def doc_ver_signed_url(self, doc_ver_id: UUID, file_name: str) -> str:
        """Generate a signed URL for downloading a document version."""
        pass

    @abstractmethod
    async def upload_file(
        self,
        file: UploadFile,
        object_key: str,
        content_type: str,
        max_file_size: int
    ) -> int:
        """Upload file and return actual size in bytes"""
        pass

    async def upload_bytes(
        self,
        data: bytes,
        object_key: str,
        content_type: str,
    ) -> int:
        """Upload raw bytes. Default wraps in UploadFile and calls upload_file."""
        from io import BytesIO
        from starlette.datastructures import Headers

        fake = UploadFile(
            file=BytesIO(data),
            size=len(data),
            filename=object_key.rsplit("/", 1)[-1],
            headers=Headers({"content-type": content_type}),
        )
        result = await self.upload_file(
            file=fake,
            object_key=object_key,
            content_type=content_type,
            max_file_size=200 * 1024 * 1024,
        )
        # upload_file may return (size, content) tuple (local backend) or just int
        return result[0] if isinstance(result, tuple) else result


def get_storage_backend() -> StorageBackend:
    """
    Factory function to get the appropriate storage backend
    based on configuration.
    """
    from papermerge.core.config import get_settings
    from papermerge.core import types

    settings = get_settings()

    if settings.storage_backend == types.StorageBackend.S3:
        from papermerge.storage.backends.cloudfront import CloudFrontBackend
        return CloudFrontBackend()
    elif settings.storage_backend == types.StorageBackend.R2:
        from papermerge.storage.backends.r2 import R2Backend
        return R2Backend()
    elif settings.storage_backend == types.StorageBackend.LINODE:
        from papermerge.storage.backends.linode import LinodeBackend
        return LinodeBackend()
    else:
        from papermerge.storage.backends.local import LocalBackend
        return LocalBackend()

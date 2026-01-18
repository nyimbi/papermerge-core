# (c) Copyright Datacraft, 2026
"""Linode Object Storage backend using S3-compatible API."""

import mimetypes
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, AsyncIterator, BinaryIO

import aioboto3
from botocore.config import Config

from .base import (
	ObjectNotFoundError,
	PresignedUrl,
	StorageBackend,
	StorageError,
	StorageObject,
	StorageTier,
	UploadResult,
)

if TYPE_CHECKING:
	from types_aiobotocore_s3 import S3Client


# Linode cluster endpoints
LINODE_CLUSTERS = {
	"us-east-1": "us-east-1.linodeobjects.com",
	"eu-central-1": "eu-central-1.linodeobjects.com",
	"ap-south-1": "ap-south-1.linodeobjects.com",
	"us-southeast-1": "us-southeast-1.linodeobjects.com",
	"us-iad-1": "us-iad-1.linodeobjects.com",
	"fr-par-1": "fr-par-1.linodeobjects.com",
	"se-sto-1": "se-sto-1.linodeobjects.com",
	"in-maa-1": "in-maa-1.linodeobjects.com",
	"jp-osa-1": "jp-osa-1.linodeobjects.com",
	"id-cgk-1": "id-cgk-1.linodeobjects.com",
	"br-gru-1": "br-gru-1.linodeobjects.com",
	"it-mil-1": "it-mil-1.linodeobjects.com",
	"nl-ams-1": "nl-ams-1.linodeobjects.com",
}

# Storage class mapping for Linode
TIER_TO_STORAGE_CLASS = {
	StorageTier.HOT: "STANDARD",
	StorageTier.WARM: "STANDARD_IA",
	StorageTier.COLD: "GLACIER",
	StorageTier.ARCHIVE: "DEEP_ARCHIVE",
}

STORAGE_CLASS_TO_TIER = {v: k for k, v in TIER_TO_STORAGE_CLASS.items()}


class LinodeStorageBackend(StorageBackend):
	"""Linode Object Storage backend using S3-compatible API."""

	def __init__(
		self,
		access_key_id: str,
		secret_access_key: str,
		bucket: str,
		cluster_id: str = "us-east-1",
		prefix: str = "",
	):
		"""Initialize Linode storage backend.

		Args:
			access_key_id: Linode access key
			secret_access_key: Linode secret key
			bucket: Bucket name
			cluster_id: Linode cluster ID
			prefix: Optional key prefix for all operations
		"""
		self.bucket = bucket
		self.prefix = prefix.strip("/")

		if cluster_id not in LINODE_CLUSTERS:
			raise ValueError(f"Unknown Linode cluster: {cluster_id}")

		endpoint_url = f"https://{LINODE_CLUSTERS[cluster_id]}"

		self._session = aioboto3.Session(
			aws_access_key_id=access_key_id,
			aws_secret_access_key=secret_access_key,
		)
		self._endpoint_url = endpoint_url
		self._config = Config(
			signature_version="s3v4",
			s3={"addressing_style": "virtual"},
			retries={"max_attempts": 3, "mode": "adaptive"},
		)

	def _full_key(self, key: str) -> str:
		"""Get full key with prefix."""
		if self.prefix:
			return f"{self.prefix}/{key.lstrip('/')}"
		return key.lstrip("/")

	async def _get_client(self) -> "S3Client":
		"""Get S3 client from context manager."""
		return self._session.client(
			"s3",
			endpoint_url=self._endpoint_url,
			config=self._config,
		)

	async def put(
		self,
		key: str,
		data: bytes | BinaryIO,
		content_type: str | None = None,
		metadata: dict[str, str] | None = None,
		tier: StorageTier = StorageTier.HOT,
	) -> UploadResult:
		full_key = self._full_key(key)
		body = data if isinstance(data, bytes) else data.read()

		params: dict = {
			"Bucket": self.bucket,
			"Key": full_key,
			"Body": body,
			"StorageClass": TIER_TO_STORAGE_CLASS[tier],
		}

		if content_type:
			params["ContentType"] = content_type
		if metadata:
			params["Metadata"] = metadata

		try:
			async with await self._get_client() as client:
				response = await client.put_object(**params)
				return UploadResult(
					key=key,
					etag=response.get("ETag", "").strip('"'),
					version_id=response.get("VersionId"),
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

		full_key = self._full_key(key)

		params: dict = {
			"Bucket": self.bucket,
			"Key": full_key,
			"StorageClass": TIER_TO_STORAGE_CLASS[tier],
		}

		if content_type:
			params["ContentType"] = content_type
		if metadata:
			params["Metadata"] = metadata

		try:
			async with await self._get_client() as client:
				with open(file_path, "rb") as f:
					params["Body"] = f
					response = await client.put_object(**params)

				return UploadResult(
					key=key,
					etag=response.get("ETag", "").strip('"'),
					version_id=response.get("VersionId"),
					size=file_path.stat().st_size,
				)
		except Exception as e:
			raise StorageError(f"Failed to upload file {key}", e) from e

	async def get(self, key: str) -> bytes:
		full_key = self._full_key(key)

		try:
			async with await self._get_client() as client:
				response = await client.get_object(Bucket=self.bucket, Key=full_key)
				async with response["Body"] as stream:
					return await stream.read()
		except client.exceptions.NoSuchKey:
			raise ObjectNotFoundError(key)
		except Exception as e:
			if "NoSuchKey" in str(e) or "404" in str(e):
				raise ObjectNotFoundError(key)
			raise StorageError(f"Failed to get {key}", e) from e

	async def get_stream(self, key: str) -> AsyncIterator[bytes]:
		full_key = self._full_key(key)

		try:
			async with await self._get_client() as client:
				response = await client.get_object(Bucket=self.bucket, Key=full_key)
				async with response["Body"] as stream:
					async for chunk in stream.iter_chunks():
						yield chunk
		except Exception as e:
			if "NoSuchKey" in str(e) or "404" in str(e):
				raise ObjectNotFoundError(key)
			raise StorageError(f"Failed to stream {key}", e) from e

	async def get_to_file(self, key: str, file_path: Path) -> None:
		full_key = self._full_key(key)

		try:
			async with await self._get_client() as client:
				response = await client.get_object(Bucket=self.bucket, Key=full_key)
				file_path.parent.mkdir(parents=True, exist_ok=True)
				with open(file_path, "wb") as f:
					async with response["Body"] as stream:
						async for chunk in stream.iter_chunks():
							f.write(chunk)
		except Exception as e:
			if "NoSuchKey" in str(e) or "404" in str(e):
				raise ObjectNotFoundError(key)
			raise StorageError(f"Failed to download {key}", e) from e

	async def delete(self, key: str) -> None:
		full_key = self._full_key(key)

		try:
			async with await self._get_client() as client:
				await client.delete_object(Bucket=self.bucket, Key=full_key)
		except Exception as e:
			raise StorageError(f"Failed to delete {key}", e) from e

	async def delete_many(self, keys: list[str]) -> list[str]:
		if not keys:
			return []

		objects = [{"Key": self._full_key(k)} for k in keys]
		failed: list[str] = []

		try:
			async with await self._get_client() as client:
				response = await client.delete_objects(
					Bucket=self.bucket,
					Delete={"Objects": objects, "Quiet": False},
				)

				for error in response.get("Errors", []):
					key = error.get("Key", "")
					if self.prefix and key.startswith(self.prefix):
						key = key[len(self.prefix) + 1 :]
					failed.append(key)

		except Exception as e:
			raise StorageError("Failed to delete objects", e) from e

		return failed

	async def exists(self, key: str) -> bool:
		full_key = self._full_key(key)

		try:
			async with await self._get_client() as client:
				await client.head_object(Bucket=self.bucket, Key=full_key)
				return True
		except Exception:
			return False

	async def head(self, key: str) -> StorageObject:
		full_key = self._full_key(key)

		try:
			async with await self._get_client() as client:
				response = await client.head_object(Bucket=self.bucket, Key=full_key)

				storage_class = response.get("StorageClass", "STANDARD")
				tier = STORAGE_CLASS_TO_TIER.get(storage_class, StorageTier.HOT)

				return StorageObject(
					key=key,
					size=response.get("ContentLength", 0),
					last_modified=response.get("LastModified", datetime.now(timezone.utc)),
					etag=response.get("ETag", "").strip('"'),
					content_type=response.get("ContentType"),
					tier=tier,
					metadata=response.get("Metadata"),
				)
		except Exception as e:
			if "404" in str(e) or "NoSuchKey" in str(e):
				raise ObjectNotFoundError(key)
			raise StorageError(f"Failed to head {key}", e) from e

	async def list_objects(
		self,
		prefix: str = "",
		max_keys: int = 1000,
		continuation_token: str | None = None,
	) -> tuple[list[StorageObject], str | None]:
		full_prefix = self._full_key(prefix) if prefix else self.prefix

		params: dict = {
			"Bucket": self.bucket,
			"MaxKeys": max_keys,
		}
		if full_prefix:
			params["Prefix"] = full_prefix
		if continuation_token:
			params["ContinuationToken"] = continuation_token

		try:
			async with await self._get_client() as client:
				response = await client.list_objects_v2(**params)

				objects = []
				for obj in response.get("Contents", []):
					key = obj["Key"]
					if self.prefix and key.startswith(self.prefix):
						key = key[len(self.prefix) + 1 :]

					storage_class = obj.get("StorageClass", "STANDARD")
					tier = STORAGE_CLASS_TO_TIER.get(storage_class, StorageTier.HOT)

					objects.append(
						StorageObject(
							key=key,
							size=obj.get("Size", 0),
							last_modified=obj.get("LastModified", datetime.now(timezone.utc)),
							etag=obj.get("ETag", "").strip('"'),
							tier=tier,
						)
					)

				next_token = response.get("NextContinuationToken")
				return objects, next_token

		except Exception as e:
			raise StorageError("Failed to list objects", e) from e

	async def copy(
		self,
		source_key: str,
		dest_key: str,
		metadata: dict[str, str] | None = None,
	) -> UploadResult:
		source_full = self._full_key(source_key)
		dest_full = self._full_key(dest_key)

		params: dict = {
			"Bucket": self.bucket,
			"CopySource": {"Bucket": self.bucket, "Key": source_full},
			"Key": dest_full,
		}

		if metadata is not None:
			params["Metadata"] = metadata
			params["MetadataDirective"] = "REPLACE"

		try:
			async with await self._get_client() as client:
				response = await client.copy_object(**params)
				return UploadResult(
					key=dest_key,
					etag=response.get("CopyObjectResult", {}).get("ETag", "").strip('"'),
					version_id=response.get("VersionId"),
				)
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
		full_key = self._full_key(key)

		try:
			async with await self._get_client() as client:
				await client.copy_object(
					Bucket=self.bucket,
					CopySource={"Bucket": self.bucket, "Key": full_key},
					Key=full_key,
					StorageClass=TIER_TO_STORAGE_CLASS[tier],
					MetadataDirective="COPY",
				)
		except Exception as e:
			raise StorageError(f"Failed to change tier for {key}", e) from e

	async def generate_presigned_url(
		self,
		key: str,
		expires_in: int = 3600,
		method: str = "GET",
	) -> PresignedUrl:
		full_key = self._full_key(key)
		operation = "get_object" if method.upper() == "GET" else "put_object"

		try:
			async with await self._get_client() as client:
				url = await client.generate_presigned_url(
					operation,
					Params={"Bucket": self.bucket, "Key": full_key},
					ExpiresIn=expires_in,
				)

				return PresignedUrl(
					url=url,
					expires_at=datetime.now(timezone.utc).replace(
						second=datetime.now(timezone.utc).second + expires_in
					),
					method=method.upper(),
				)
		except Exception as e:
			raise StorageError(f"Failed to generate presigned URL for {key}", e) from e

	async def generate_presigned_upload_url(
		self,
		key: str,
		content_type: str,
		expires_in: int = 3600,
		metadata: dict[str, str] | None = None,
	) -> PresignedUrl:
		full_key = self._full_key(key)

		params: dict = {
			"Bucket": self.bucket,
			"Key": full_key,
			"ContentType": content_type,
		}
		if metadata:
			params["Metadata"] = metadata

		try:
			async with await self._get_client() as client:
				url = await client.generate_presigned_url(
					"put_object",
					Params=params,
					ExpiresIn=expires_in,
				)

				return PresignedUrl(
					url=url,
					expires_at=datetime.now(timezone.utc).replace(
						second=datetime.now(timezone.utc).second + expires_in
					),
					method="PUT",
				)
		except Exception as e:
			raise StorageError(f"Failed to generate upload URL for {key}", e) from e

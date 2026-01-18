import logging
from uuid import UUID
from pathlib import Path

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from fastapi import UploadFile

from papermerge.core.config import get_settings
from papermerge.core import pathlib as plib
from papermerge.core.types import ImagePreviewSize
from papermerge.storage.base import StorageBackend
from papermerge.storage.exc import StorageUploadError, FileTooLargeError

logger = logging.getLogger(__name__)


class LinodeBackend(StorageBackend):
	"""
	Linode Object Storage backend using S3-compatible presigned URLs.

	Linode Object Storage is S3-compatible, so we use boto3 with a custom endpoint.
	Clusters: us-east-1, us-southeast-1, eu-central-1, ap-south-1
	"""

	def __init__(self):
		self.settings = get_settings()
		self._validate_settings()
		self._client = None

	def _validate_settings(self):
		if not self.settings.linode_cluster_id:
			raise ValueError("LINODE_CLUSTER_ID is not configured")
		if not self.settings.linode_access_key_id:
			raise ValueError("LINODE_ACCESS_KEY_ID is not configured")
		if not self.settings.linode_secret_access_key:
			raise ValueError("LINODE_SECRET_ACCESS_KEY is not configured")
		if not self.settings.linode_bucket_name:
			raise ValueError("LINODE_BUCKET_NAME is not configured")

	@property
	def client(self):
		"""Lazy-loaded boto3 S3 client for Linode Object Storage."""
		if self._client is None:
			self._client = boto3.client(
				's3',
				endpoint_url=self.settings.linode_endpoint_url,
				aws_access_key_id=self.settings.linode_access_key_id,
				aws_secret_access_key=self.settings.linode_secret_access_key,
				config=Config(signature_version='s3v4'),
				region_name=self.settings.linode_cluster_id,
			)
		return self._client

	async def upload_file(
		self,
		file: UploadFile,
		object_key: str,
		content_type: str,
		max_file_size: int
	) -> int:
		"""Stream file to Linode Object Storage."""
		content = await file.read()

		if len(content) > max_file_size:
			raise FileTooLargeError(
				f"File size {len(content)} exceeds maximum {max_file_size}"
			)

		prefix = Path(self.settings.prefix)
		full_key = str(prefix / object_key) if prefix else object_key

		try:
			self.client.put_object(
				Bucket=self.settings.linode_bucket_name,
				Key=full_key,
				Body=content,
				ContentType=content_type
			)
			logger.info(f"Uploaded file to Linode: {full_key}")
			return len(content)
		except Exception as e:
			logger.error(f"Linode upload failed for {full_key}: {e}")
			raise StorageUploadError(f"Upload failed: {e}")

	def download_file(self, object_key: str) -> bytes:
		"""Download file from Linode Object Storage."""
		prefix = Path(self.settings.prefix)
		full_key = str(prefix / object_key) if prefix else object_key

		try:
			response = self.client.get_object(
				Bucket=self.settings.linode_bucket_name,
				Key=full_key
			)
			return response['Body'].read()
		except ClientError as e:
			logger.error(f"Linode download failed for {full_key}: {e}")
			raise

	def delete_file(self, object_key: str) -> None:
		"""Delete file from Linode Object Storage."""
		prefix = Path(self.settings.prefix)
		full_key = str(prefix / object_key) if prefix else object_key

		try:
			self.client.delete_object(
				Bucket=self.settings.linode_bucket_name,
				Key=full_key
			)
			logger.info(f"Deleted file from Linode: {full_key}")
		except ClientError as e:
			logger.error(f"Linode delete failed for {full_key}: {e}")
			raise

	def file_exists(self, object_key: str) -> bool:
		"""Check if file exists in Linode Object Storage."""
		prefix = Path(self.settings.prefix)
		full_key = str(prefix / object_key) if prefix else object_key

		try:
			self.client.head_object(
				Bucket=self.settings.linode_bucket_name,
				Key=full_key
			)
			return True
		except ClientError:
			return False

	def _build_object_key(self, resource_path) -> str:
		"""Build the S3 object key with optional prefix."""
		prefix = self.settings.prefix
		path_str = str(resource_path)

		if prefix:
			return f"{prefix}/{path_str}"
		return path_str

	def sign_url(self, url: str, valid_for: int = StorageBackend.DEFAULT_VALID_FOR_SECONDS) -> str:
		"""
		Sign a URL for Linode access.

		Note: For Linode, the 'url' parameter is interpreted as the object key/path,
		not a full URL.
		"""
		object_key = url
		return self._generate_presigned_url(object_key, valid_for)

	def _generate_presigned_url(
		self,
		object_key: str,
		valid_for: int = StorageBackend.DEFAULT_VALID_FOR_SECONDS
	) -> str:
		"""Generate a presigned URL for downloading an object from Linode."""
		try:
			url = self.client.generate_presigned_url(
				'get_object',
				Params={
					'Bucket': self.settings.linode_bucket_name,
					'Key': object_key,
				},
				ExpiresIn=valid_for,
			)
			return url
		except ClientError as e:
			logger.error(f"Failed to generate presigned URL for {object_key}: {e}")
			raise

	def generate_upload_url(
		self,
		object_key: str,
		content_type: str,
		valid_for: int = 3600
	) -> str:
		"""Generate a presigned URL for uploading an object to Linode."""
		prefix = Path(self.settings.prefix)
		full_key = str(prefix / object_key) if prefix else object_key

		try:
			url = self.client.generate_presigned_url(
				'put_object',
				Params={
					'Bucket': self.settings.linode_bucket_name,
					'Key': full_key,
					'ContentType': content_type,
				},
				ExpiresIn=valid_for,
			)
			return url
		except ClientError as e:
			logger.error(f"Failed to generate upload URL for {full_key}: {e}")
			raise

	def doc_thumbnail_signed_url(self, uid: UUID) -> str:
		resource_path = plib.thumbnail_path(uid)
		object_key = self._build_object_key(resource_path)
		return self._generate_presigned_url(object_key)

	def page_image_jpg_signed_url(self, uid: UUID, size: ImagePreviewSize) -> str:
		resource_path = plib.page_preview_jpg_path(uid, size=size)
		object_key = self._build_object_key(resource_path)
		return self._generate_presigned_url(object_key)

	def doc_ver_signed_url(self, doc_ver_id: UUID, file_name: str) -> str:
		resource_path = plib.docver_path(doc_ver_id, file_name=file_name)
		object_key = self._build_object_key(resource_path)
		return self._generate_presigned_url(object_key)

	def list_objects(self, prefix: str = '', max_keys: int = 1000) -> list[dict]:
		"""List objects in the bucket with optional prefix filter."""
		base_prefix = self.settings.prefix
		full_prefix = f"{base_prefix}/{prefix}" if base_prefix else prefix

		try:
			response = self.client.list_objects_v2(
				Bucket=self.settings.linode_bucket_name,
				Prefix=full_prefix,
				MaxKeys=max_keys
			)
			return response.get('Contents', [])
		except ClientError as e:
			logger.error(f"Failed to list objects with prefix {full_prefix}: {e}")
			raise

	def copy_object(self, source_key: str, dest_key: str) -> None:
		"""Copy object within the bucket."""
		prefix = Path(self.settings.prefix)
		full_source = str(prefix / source_key) if prefix else source_key
		full_dest = str(prefix / dest_key) if prefix else dest_key

		try:
			self.client.copy_object(
				Bucket=self.settings.linode_bucket_name,
				CopySource={
					'Bucket': self.settings.linode_bucket_name,
					'Key': full_source
				},
				Key=full_dest
			)
			logger.info(f"Copied {full_source} to {full_dest}")
		except ClientError as e:
			logger.error(f"Failed to copy {full_source} to {full_dest}: {e}")
			raise

	def get_object_metadata(self, object_key: str) -> dict:
		"""Get metadata for an object."""
		prefix = Path(self.settings.prefix)
		full_key = str(prefix / object_key) if prefix else object_key

		try:
			response = self.client.head_object(
				Bucket=self.settings.linode_bucket_name,
				Key=full_key
			)
			return {
				'content_type': response.get('ContentType'),
				'content_length': response.get('ContentLength'),
				'last_modified': response.get('LastModified'),
				'etag': response.get('ETag'),
				'metadata': response.get('Metadata', {})
			}
		except ClientError as e:
			logger.error(f"Failed to get metadata for {full_key}: {e}")
			raise

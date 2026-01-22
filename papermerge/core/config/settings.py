# (c) Copyright Datacraft, 2026
"""Application settings configuration."""
from pathlib import Path

from pydantic import PostgresDsn, RedisDsn, Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

from papermerge.core.types import DocumentLang, StorageBackend


class Settings(BaseSettings):
	db_url: PostgresDsn
	db_ssl: bool = False
	log_config: Path | None = Path("/app/log_config.yaml")
	api_prefix: str = ''
	default_lang: DocumentLang = DocumentLang.deu

	# Redis
	cache_enabled: bool = False
	redis_url: RedisDsn | None = None

	# File storage
	media_root: Path = Path("media")
	max_file_size_mb: int = Field(gt=0, default=25)
	storage_backend: StorageBackend = StorageBackend.LOCAL

	# AWS CloudFront settings
	cf_sign_url_private_key: str | None = None
	cf_sign_url_key_id: str | None = None
	cf_domain: str | None = None

	# Cloudflare R2 settings
	r2_account_id: str | None = None
	r2_access_key_id: str | None = None
	r2_secret_access_key: str | None = None
	bucket_name: str | None = None

	# Linode Object Storage settings
	linode_access_key_id: str | None = None
	linode_secret_access_key: str | None = None
	linode_bucket_name: str | None = None
	linode_cluster_id: str | None = None

	# Search backend settings
	search_backend: str = 'postgres'
	elasticsearch_hosts: str | None = None
	elasticsearch_api_key: str | None = None
	elasticsearch_index: str = 'documents'
	meilisearch_host: str = 'http://localhost:7700'
	meilisearch_api_key: str | None = None
	meilisearch_index: str = 'documents'

	# Semantic search / embeddings settings
	embedding_provider: str = 'ollama'
	embedding_model: str = 'nomic-embed-text'
	ollama_base_url: str = 'http://localhost:11434'
	semantic_search_enabled: bool = False
	semantic_search_threshold: float = 0.5
	hybrid_search_semantic_weight: float = 0.5

	preview_page_size_sm: int = Field(gt=0, default=200)
	prefix: str = ''

	# Multi-tenancy configuration
	deployment_mode: str = 'single_tenant'
	tenant_resolution: str = 'token'
	tenant_base_domain: str = 'localhost'
	default_tenant_slug: str | None = None
	require_tenant: bool = False

	# Security
	csrf_secret_key: str = Field(default="change-me-in-production")
	rate_limit_requests_per_minute: int = Field(gt=0, default=100)
	rate_limit_enabled: bool = False

	# Remote user config
	remote_user_header: str = "X-Forwarded-User"
	remote_groups_header: str = "X-Forwarded-Groups"
	remote_roles_header: str = "X-Forwarded-Roles"
	remote_name_header: str = "X-Forwarded-Name"
	remote_email_header: str = "X-Forwarded-Email"

	@computed_field
	@property
	def async_db_url(self) -> str:
		url = str(self.db_url)
		# Handle various PostgreSQL URL formats
		if "postgresql+psycopg://" in url:
			return url.replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
		elif "postgresql://" in url:
			return url.replace("postgresql://", "postgresql+asyncpg://", 1)
		return url

	@computed_field
	@property
	def r2_endpoint_url(self) -> str | None:
		if self.r2_account_id:
			return f"https://{self.r2_account_id}.r2.cloudflarestorage.com"
		return None

	@computed_field
	@property
	def linode_endpoint_url(self) -> str | None:
		if self.linode_cluster_id:
			return f"https://{self.linode_cluster_id}.linodeobjects.com"
		return None

	model_config = SettingsConfigDict(
		env_prefix='pm_',
		env_file='.env',
		env_file_encoding='utf-8',
		extra='ignore',
	)


_settings: Settings | None = None


def get_settings() -> Settings:
	global _settings
	if _settings is None:
		_settings = Settings()
	return _settings

# (c) Copyright Datacraft, 2026
"""Factory for LLM clients."""
import os
from functools import lru_cache

from .base import LLMClient, LLMConfig
from .azure_openai import AzureOpenAIClient
from .ollama import OllamaClient


@lru_cache(maxsize=1)
def get_llm_config() -> LLMConfig:
	"""Get LLM configuration from environment variables."""
	provider = os.getenv("LLM_PROVIDER", "ollama")

	return LLMConfig(
		provider=provider,
		model=os.getenv("LLM_MODEL", "llama3.2"),
		# Azure OpenAI
		azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT", ""),
		azure_api_key=os.getenv("AZURE_OPENAI_API_KEY", ""),
		azure_api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01"),
		azure_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT", ""),
		# Ollama
		ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
		# Common
		temperature=float(os.getenv("LLM_TEMPERATURE", "0.7")),
		max_tokens=int(os.getenv("LLM_MAX_TOKENS", "4096")),
		timeout=float(os.getenv("LLM_TIMEOUT", "60.0")),
	)


def get_llm_client(config: LLMConfig | None = None) -> LLMClient:
	"""Get an LLM client based on configuration."""
	if config is None:
		config = get_llm_config()

	if config.provider == "azure_openai":
		return AzureOpenAIClient(config)
	elif config.provider == "ollama":
		return OllamaClient(config)
	else:
		raise ValueError(f"Unknown LLM provider: {config.provider}")

# (c) Copyright Datacraft, 2026
"""Base LLM client interface."""
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)


@dataclass
class LLMConfig:
	"""Configuration for LLM clients."""
	provider: str = "ollama"  # ollama | azure_openai
	model: str = "llama3.2"
	# Azure OpenAI specific
	azure_endpoint: str = ""
	azure_api_key: str = ""
	azure_api_version: str = "2024-02-01"
	azure_deployment: str = ""
	# Ollama specific
	ollama_base_url: str = "http://localhost:11434"
	# Common settings
	temperature: float = 0.7
	max_tokens: int = 4096
	timeout: float = 60.0


class LLMResponse(BaseModel):
	"""Structured LLM response."""
	model_config = ConfigDict(extra="forbid")

	content: str
	model: str
	usage: dict[str, int] = field(default_factory=dict)
	finish_reason: str | None = None
	raw_response: dict[str, Any] | None = None


def _log_llm_request(provider: str, model: str) -> str:
	return f"LLM request to {provider}/{model}"


class LLMClient(ABC):
	"""Abstract base class for LLM clients."""

	def __init__(self, config: LLMConfig):
		self.config = config

	@abstractmethod
	async def complete(
		self,
		prompt: str,
		system_prompt: str | None = None,
		temperature: float | None = None,
		max_tokens: int | None = None,
	) -> LLMResponse:
		"""Generate a completion from the LLM."""
		pass

	@abstractmethod
	async def complete_json(
		self,
		prompt: str,
		system_prompt: str | None = None,
		schema: dict[str, Any] | None = None,
	) -> dict[str, Any]:
		"""Generate a JSON completion from the LLM."""
		pass

	@abstractmethod
	async def health_check(self) -> bool:
		"""Check if the LLM service is available."""
		pass

# (c) Copyright Datacraft, 2026
"""Azure OpenAI client implementation."""
import json
import logging
from typing import Any

import httpx

from .base import LLMClient, LLMConfig, LLMResponse, _log_llm_request

logger = logging.getLogger(__name__)


class AzureOpenAIClient(LLMClient):
	"""Azure OpenAI API client."""

	def __init__(self, config: LLMConfig):
		super().__init__(config)
		assert config.azure_endpoint, "Azure endpoint is required"
		assert config.azure_api_key, "Azure API key is required"
		assert config.azure_deployment, "Azure deployment is required"
		self._base_url = f"{config.azure_endpoint}/openai/deployments/{config.azure_deployment}"
		self._headers = {
			"api-key": config.azure_api_key,
			"Content-Type": "application/json",
		}

	async def complete(
		self,
		prompt: str,
		system_prompt: str | None = None,
		temperature: float | None = None,
		max_tokens: int | None = None,
	) -> LLMResponse:
		"""Generate a completion using Azure OpenAI."""
		messages = []
		if system_prompt:
			messages.append({"role": "system", "content": system_prompt})
		messages.append({"role": "user", "content": prompt})

		payload = {
			"messages": messages,
			"temperature": temperature or self.config.temperature,
			"max_tokens": max_tokens or self.config.max_tokens,
		}

		url = f"{self._base_url}/chat/completions?api-version={self.config.azure_api_version}"
		logger.debug(_log_llm_request("azure_openai", self.config.azure_deployment))

		async with httpx.AsyncClient(timeout=self.config.timeout) as client:
			response = await client.post(url, headers=self._headers, json=payload)
			response.raise_for_status()
			data = response.json()

		choice = data["choices"][0]
		return LLMResponse(
			content=choice["message"]["content"],
			model=data.get("model", self.config.azure_deployment),
			usage=data.get("usage", {}),
			finish_reason=choice.get("finish_reason"),
			raw_response=data,
		)

	async def complete_json(
		self,
		prompt: str,
		system_prompt: str | None = None,
		schema: dict[str, Any] | None = None,
	) -> dict[str, Any]:
		"""Generate a JSON completion using Azure OpenAI."""
		json_system = (system_prompt or "") + "\n\nRespond with valid JSON only."
		if schema:
			json_system += f"\n\nExpected JSON schema:\n{json.dumps(schema, indent=2)}"

		messages = [
			{"role": "system", "content": json_system},
			{"role": "user", "content": prompt},
		]

		payload = {
			"messages": messages,
			"temperature": 0.3,
			"max_tokens": self.config.max_tokens,
			"response_format": {"type": "json_object"},
		}

		url = f"{self._base_url}/chat/completions?api-version={self.config.azure_api_version}"
		logger.debug(_log_llm_request("azure_openai", self.config.azure_deployment))

		async with httpx.AsyncClient(timeout=self.config.timeout) as client:
			response = await client.post(url, headers=self._headers, json=payload)
			response.raise_for_status()
			data = response.json()

		content = data["choices"][0]["message"]["content"]
		return json.loads(content)

	async def health_check(self) -> bool:
		"""Check if Azure OpenAI is available."""
		try:
			response = await self.complete("Say 'ok'", max_tokens=10)
			return bool(response.content)
		except Exception as e:
			logger.error(f"Azure OpenAI health check failed: {e}")
			return False

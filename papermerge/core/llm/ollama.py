# (c) Copyright Datacraft, 2026
"""Ollama client implementation."""
import json
import logging
from typing import Any

import httpx

from .base import LLMClient, LLMConfig, LLMResponse, _log_llm_request

logger = logging.getLogger(__name__)


class OllamaClient(LLMClient):
	"""Ollama API client for local LLM inference."""

	def __init__(self, config: LLMConfig):
		super().__init__(config)
		self._base_url = config.ollama_base_url.rstrip("/")

	async def complete(
		self,
		prompt: str,
		system_prompt: str | None = None,
		temperature: float | None = None,
		max_tokens: int | None = None,
	) -> LLMResponse:
		"""Generate a completion using Ollama."""
		messages = []
		if system_prompt:
			messages.append({"role": "system", "content": system_prompt})
		messages.append({"role": "user", "content": prompt})

		payload = {
			"model": self.config.model,
			"messages": messages,
			"stream": False,
			"options": {
				"temperature": temperature or self.config.temperature,
				"num_predict": max_tokens or self.config.max_tokens,
			},
		}

		url = f"{self._base_url}/api/chat"
		logger.debug(_log_llm_request("ollama", self.config.model))

		async with httpx.AsyncClient(timeout=self.config.timeout) as client:
			response = await client.post(url, json=payload)
			response.raise_for_status()
			data = response.json()

		return LLMResponse(
			content=data["message"]["content"],
			model=data.get("model", self.config.model),
			usage={
				"prompt_tokens": data.get("prompt_eval_count", 0),
				"completion_tokens": data.get("eval_count", 0),
				"total_tokens": data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
			},
			finish_reason=data.get("done_reason"),
			raw_response=data,
		)

	async def complete_json(
		self,
		prompt: str,
		system_prompt: str | None = None,
		schema: dict[str, Any] | None = None,
	) -> dict[str, Any]:
		"""Generate a JSON completion using Ollama."""
		json_system = (system_prompt or "") + "\n\nRespond with valid JSON only. No markdown, no explanation."
		if schema:
			json_system += f"\n\nExpected JSON schema:\n{json.dumps(schema, indent=2)}"

		messages = [
			{"role": "system", "content": json_system},
			{"role": "user", "content": prompt},
		]

		payload = {
			"model": self.config.model,
			"messages": messages,
			"stream": False,
			"format": "json",
			"options": {
				"temperature": 0.3,
				"num_predict": self.config.max_tokens,
			},
		}

		url = f"{self._base_url}/api/chat"
		logger.debug(_log_llm_request("ollama", self.config.model))

		async with httpx.AsyncClient(timeout=self.config.timeout) as client:
			response = await client.post(url, json=payload)
			response.raise_for_status()
			data = response.json()

		content = data["message"]["content"]
		# Handle potential markdown code blocks
		if content.startswith("```"):
			lines = content.split("\n")
			content = "\n".join(lines[1:-1])
		return json.loads(content)

	async def health_check(self) -> bool:
		"""Check if Ollama is available."""
		try:
			async with httpx.AsyncClient(timeout=5.0) as client:
				response = await client.get(f"{self._base_url}/api/tags")
				return response.status_code == 200
		except Exception as e:
			logger.error(f"Ollama health check failed: {e}")
			return False

	async def list_models(self) -> list[str]:
		"""List available models in Ollama."""
		async with httpx.AsyncClient(timeout=10.0) as client:
			response = await client.get(f"{self._base_url}/api/tags")
			response.raise_for_status()
			data = response.json()
		return [m["name"] for m in data.get("models", [])]

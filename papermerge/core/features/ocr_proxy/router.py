"""
OCR Proxy Router

Proxies browser-side VLM OCR requests to avoid CORS issues.
Supports Ollama Cloud and other VLM providers.
"""
import logging
from typing import Annotated

import httpx
from fastapi import APIRouter, Security, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from papermerge.core import schema
from papermerge.core.features.auth import get_current_user, scopes

logger = logging.getLogger(__name__)

router = APIRouter(
	prefix="/ocr-proxy",
	tags=["ocr-proxy"],
)


class OllamaTagsResponse(BaseModel):
	"""Response from Ollama tags endpoint"""
	models: list[dict] = []


class OllamaChatRequest(BaseModel):
	"""Request body for Ollama chat endpoint"""
	model: str
	messages: list[dict]
	stream: bool = False
	options: dict | None = None


@router.get("/ollama/tags")
async def proxy_ollama_tags(
	request: Request,
	user: Annotated[schema.User, Security(get_current_user, scopes=[])],
):
	"""
	Proxy requests to Ollama Cloud /api/tags endpoint.
	This avoids CORS issues when calling from the browser.
	"""
	# Get API key from header
	api_key = request.headers.get("X-Ollama-Api-Key", "")
	host = request.headers.get("X-Ollama-Host", "https://ollama.com")

	# Normalize host URL
	base_url = host.rstrip("/")

	headers = {}
	if api_key:
		headers["Authorization"] = f"Bearer {api_key}"

	try:
		async with httpx.AsyncClient(timeout=30.0) as client:
			response = await client.get(
				f"{base_url}/api/tags",
				headers=headers,
			)

			return Response(
				content=response.content,
				status_code=response.status_code,
				media_type="application/json",
			)
	except httpx.TimeoutException:
		raise HTTPException(status_code=504, detail="Ollama request timed out")
	except httpx.RequestError as e:
		logger.error(f"Ollama proxy error: {e}")
		raise HTTPException(status_code=502, detail=f"Failed to connect to Ollama: {str(e)}")


@router.post("/ollama/chat")
async def proxy_ollama_chat(
	request: Request,
	chat_request: OllamaChatRequest,
	user: Annotated[schema.User, Security(get_current_user, scopes=[])],
):
	"""
	Proxy requests to Ollama Cloud /api/chat endpoint.
	This is used for VLM-based OCR processing.
	"""
	# Get API key from header
	api_key = request.headers.get("X-Ollama-Api-Key", "")
	host = request.headers.get("X-Ollama-Host", "https://ollama.com")

	# Normalize host URL
	base_url = host.rstrip("/")

	headers = {"Content-Type": "application/json"}
	if api_key:
		headers["Authorization"] = f"Bearer {api_key}"

	try:
		async with httpx.AsyncClient(timeout=120.0) as client:
			response = await client.post(
				f"{base_url}/api/chat",
				headers=headers,
				json=chat_request.model_dump(),
			)

			return Response(
				content=response.content,
				status_code=response.status_code,
				media_type="application/json",
			)
	except httpx.TimeoutException:
		raise HTTPException(status_code=504, detail="Ollama OCR request timed out")
	except httpx.RequestError as e:
		logger.error(f"Ollama proxy error: {e}")
		raise HTTPException(status_code=502, detail=f"Failed to connect to Ollama: {str(e)}")


@router.post("/anthropic/messages")
async def proxy_anthropic_messages(
	request: Request,
	user: Annotated[schema.User, Security(get_current_user, scopes=[])],
):
	"""
	Proxy requests to Anthropic API for Claude Vision OCR.
	"""
	api_key = request.headers.get("X-Anthropic-Api-Key", "")
	if not api_key:
		raise HTTPException(status_code=400, detail="Anthropic API key required")

	body = await request.body()

	headers = {
		"Content-Type": "application/json",
		"x-api-key": api_key,
		"anthropic-version": "2023-06-01",
	}

	try:
		async with httpx.AsyncClient(timeout=120.0) as client:
			response = await client.post(
				"https://api.anthropic.com/v1/messages",
				headers=headers,
				content=body,
			)

			return Response(
				content=response.content,
				status_code=response.status_code,
				media_type="application/json",
			)
	except httpx.TimeoutException:
		raise HTTPException(status_code=504, detail="Anthropic request timed out")
	except httpx.RequestError as e:
		logger.error(f"Anthropic proxy error: {e}")
		raise HTTPException(status_code=502, detail=f"Failed to connect to Anthropic: {str(e)}")


@router.post("/openai/chat/completions")
async def proxy_openai_chat(
	request: Request,
	user: Annotated[schema.User, Security(get_current_user, scopes=[])],
):
	"""
	Proxy requests to OpenAI API for GPT-4 Vision OCR.
	"""
	api_key = request.headers.get("X-OpenAI-Api-Key", "")
	if not api_key:
		raise HTTPException(status_code=400, detail="OpenAI API key required")

	body = await request.body()

	headers = {
		"Content-Type": "application/json",
		"Authorization": f"Bearer {api_key}",
	}

	try:
		async with httpx.AsyncClient(timeout=120.0) as client:
			response = await client.post(
				"https://api.openai.com/v1/chat/completions",
				headers=headers,
				content=body,
			)

			return Response(
				content=response.content,
				status_code=response.status_code,
				media_type="application/json",
			)
	except httpx.TimeoutException:
		raise HTTPException(status_code=504, detail="OpenAI request timed out")
	except httpx.RequestError as e:
		logger.error(f"OpenAI proxy error: {e}")
		raise HTTPException(status_code=502, detail=f"Failed to connect to OpenAI: {str(e)}")


@router.post("/azure-openai/chat/completions")
async def proxy_azure_openai_chat(
	request: Request,
	user: Annotated[schema.User, Security(get_current_user, scopes=[])],
):
	"""
	Proxy requests to Azure OpenAI API for GPT-4 Vision OCR.
	"""
	api_key = request.headers.get("X-Azure-Api-Key", "")
	endpoint = request.headers.get("X-Azure-Endpoint", "")
	deployment = request.headers.get("X-Azure-Deployment", "")
	api_version = request.headers.get("X-Azure-Api-Version", "2024-02-15-preview")

	if not api_key:
		raise HTTPException(status_code=400, detail="Azure OpenAI API key required")
	if not endpoint:
		raise HTTPException(status_code=400, detail="Azure OpenAI endpoint required")
	if not deployment:
		raise HTTPException(status_code=400, detail="Azure OpenAI deployment name required")

	body = await request.body()

	# Normalize endpoint
	endpoint = endpoint.rstrip("/")

	# Azure OpenAI URL format
	url = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version={api_version}"

	headers = {
		"Content-Type": "application/json",
		"api-key": api_key,
	}

	try:
		async with httpx.AsyncClient(timeout=120.0) as client:
			response = await client.post(
				url,
				headers=headers,
				content=body,
			)

			return Response(
				content=response.content,
				status_code=response.status_code,
				media_type="application/json",
			)
	except httpx.TimeoutException:
		raise HTTPException(status_code=504, detail="Azure OpenAI request timed out")
	except httpx.RequestError as e:
		logger.error(f"Azure OpenAI proxy error: {e}")
		raise HTTPException(status_code=502, detail=f"Failed to connect to Azure OpenAI: {str(e)}")

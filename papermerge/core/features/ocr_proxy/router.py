"""
OCR Proxy Router

Proxies browser-side VLM OCR requests to avoid CORS issues.
Supports the configured OpenAI-compatible LiteLLM gateway.

Credentials and the gateway URL are taken from server configuration only —
clients cannot redirect the proxy to an arbitrary host (SSRF prevention) or
inject their own API key.
"""
import logging
from typing import Annotated

import httpx
from fastapi import APIRouter, Security, HTTPException, Request, Response

from papermerge.core import schema
from papermerge.core.config import get_settings
from papermerge.core.features.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(
	prefix="/ocr-proxy",
	tags=["ocr-proxy"],
)


@router.post("/openai/chat/completions")
async def proxy_openai_chat(
	request: Request,
	user: Annotated[schema.User, Security(get_current_user, scopes=[])],
):
	"""
	Proxy OpenAI-compatible OCR requests through the configured LiteLLM gateway.
	"""
	settings = get_settings()
	api_key = settings.litellm_api_key
	base_url = (settings.litellm_base_url or "").rstrip("/")

	if not api_key or not base_url:
		raise HTTPException(
			status_code=503,
			detail="LiteLLM gateway not configured",
		)

	body = await request.body()

	headers = {
		"Content-Type": "application/json",
		"Authorization": f"Bearer {api_key}",
	}

	try:
		async with httpx.AsyncClient(timeout=120.0) as client:
			response = await client.post(
				f"{base_url}/chat/completions",
				headers=headers,
				content=body,
			)

			return Response(
				content=response.content,
				status_code=response.status_code,
				media_type="application/json",
			)
	except httpx.TimeoutException:
		raise HTTPException(status_code=504, detail="LiteLLM OCR request timed out")
	except httpx.RequestError as e:
		logger.error(f"LiteLLM proxy error: {e}")
		raise HTTPException(status_code=502, detail=f"Failed to connect to LiteLLM: {str(e)}")

# (c) Copyright Datacraft, 2026
"""Security middleware for CSRF protection and Rate Limiting."""
import hmac
import hashlib
import time
import logging
from typing import Optional

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse

from papermerge.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

class CSRFMiddleware(BaseHTTPMiddleware):
    """
    Middleware to prevent Cross-Site Request Forgery (CSRF).
    """
    # Path suffixes that don't require CSRF validation (without api_prefix)
    EXEMPT_PATH_SUFFIXES = [
        "/auth/token",  # Login endpoint
        "/auth/refresh",  # Token refresh
        "/auth/logout",  # Logout
    ]

    def _is_exempt_path(self, path: str) -> bool:
        """Check if path is exempt from CSRF validation."""
        # Get configured API prefix
        api_prefix = settings.api_prefix or ""

        for suffix in self.EXEMPT_PATH_SUFFIXES:
            exempt_path = f"{api_prefix}{suffix}"
            if path == exempt_path or path == suffix:
                return True
        return False

    def _has_bearer_token(self, request: Request) -> bool:
        """Check if request has Bearer token authentication.

        Requests with Bearer tokens are exempt from CSRF validation because
        JWT authentication via Authorization header is inherently CSRF-safe.
        """
        auth_header = request.headers.get("Authorization", "")
        return auth_header.startswith("Bearer ")
    
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Safe methods don't need CSRF validation
        if request.method in ("GET", "HEAD", "OPTIONS", "TRACE"):
            response = await call_next(request)
            
            # Set CSRF cookie if not present
            if "csrftoken" not in request.cookies:
                token = self._generate_token()
                response.set_cookie(
                    "csrftoken", 
                    token, 
                    httponly=False,  # Frontend needs to read it
                    samesite="lax",
                    secure=False  # Changed to False for local development
                )
            return response

        # Exempt certain paths from CSRF validation
        if self._is_exempt_path(request.url.path):
            return await call_next(request)

        # Exempt requests with Bearer token authentication (CSRF-safe)
        if self._has_bearer_token(request):
            return await call_next(request)

        # Validate CSRF token for unsafe methods
        cookie_token = request.cookies.get("csrftoken")
        header_token = request.headers.get("X-CSRF-Token")

        if not cookie_token or not header_token or not hmac.compare_digest(cookie_token, header_token):
            logger.warning(f"CSRF validation failed for {request.method} {request.url.path}")
            return JSONResponse(
                status_code=403,
                content={"detail": "CSRF token missing or invalid"}
            )

        return await call_next(request)

    def _generate_token(self) -> str:
        return hashlib.sha256(f"{settings.csrf_secret_key}{time.time()}".encode()).hexdigest()


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Redis-based rate limiting middleware.
    """
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not settings.rate_limit_enabled or not settings.redis_url:
            return await call_next(request)

        # Identify client (IP or User ID)
        client_id = request.client.host
        # TODO: If authenticated, use user_id instead of IP
        
        key = f"rate_limit:{client_id}"
        
        # Simple fixed-window counter in Redis
        # In a real system, we'd use a more sophisticated library or Lua script
        try:
            import redis.asyncio as redis
            r = redis.from_url(str(settings.redis_url))
            
            current_count = await r.incr(key)
            if current_count == 1:
                await r.expire(key, 60)  # 1 minute window
                
            if current_count > settings.rate_limit_requests_per_minute:
                logger.warning(f"Rate limit exceeded for {client_id}")
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many requests. Please try again later."}
                )
        except Exception as e:
            logger.error(f"Rate limiting error: {e}")
            # Fail open if Redis is down? Or fail closed? 
            # Usually fail open for rate limiting to avoid downtime.
            pass

        return await call_next(request)

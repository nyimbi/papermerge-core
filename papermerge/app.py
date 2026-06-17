import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from logging.config import dictConfig

import yaml
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, status
from fastapi.middleware.cors import CORSMiddleware
from papermerge.core.middleware.security import CSRFMiddleware, RateLimitMiddleware

from papermerge.core.router_loader import discover_routers
from papermerge.core.version import __version__
from papermerge.core.config import get_settings
from papermerge.core.routers.version import router as version_router
from papermerge.core.routers.scopes import router as scopes_router
from papermerge.core.openapi import create_custom_openapi_generator

logger = logging.getLogger(__name__)
config = get_settings()
prefix = config.api_prefix

# Background task references
_state_sync_task = None
_state_sync_poller = None


@asynccontextmanager
async def lifespan(app: FastAPI):
	"""Application lifespan handler for startup/shutdown events."""
	global _state_sync_task, _state_sync_poller

	# Startup
	logger.info("Starting dArchiva API server...")

	# Start workflow state sync poller if Prefect is enabled
	try:
		from papermerge.core.config.prefect import get_prefect_settings
		from papermerge.core.features.workflows.state_sync import StateSyncPoller
		from papermerge.core.db.engine import async_session_factory

		prefect_settings = get_prefect_settings()
		if prefect_settings.enabled:
			_state_sync_poller = StateSyncPoller(async_session_factory)
			_state_sync_task = asyncio.create_task(_state_sync_poller.start())
			logger.info("Workflow state sync poller started")
	except ImportError as e:
		logger.debug(f"Prefect/workflow features not available: {e}")
	except Exception as e:
		logger.warning(f"Failed to start state sync poller: {e}")

	yield

	# Shutdown
	logger.info("Shutting down dArchiva API server...")

	# Stop state sync poller
	if _state_sync_poller:
		await _state_sync_poller.stop()
	if _state_sync_task:
		_state_sync_task.cancel()
		try:
			await _state_sync_task
		except asyncio.CancelledError:
			pass
		logger.info("Workflow state sync poller stopped")


app = FastAPI(
	title="Papermerge DMS REST API",
	version=__version__,
	lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[
        "Content-Disposition",  # This is crucial!
        "Content-Type",
        "Content-Length",
        "Accept-Ranges",
        "Last-Modified",
        "ETag"
    ]
)

# Add Security Middleware
app.add_middleware(CSRFMiddleware)
app.add_middleware(RateLimitMiddleware)

# Add tenant middleware for multi-tenant deployments
if config.deployment_mode == 'multi_tenant':
    from papermerge.core.tenancy.middleware import (
        TenantMiddleware,
        ChainedStrategy,
        TokenClaimStrategy,
        HeaderStrategy,
        HostHeaderStrategy,
        PathPrefixStrategy,
    )

    # Build resolution strategy based on config
    strategies = []
    if 'token' in config.tenant_resolution:
        strategies.append(TokenClaimStrategy())
    if 'header' in config.tenant_resolution:
        strategies.append(HeaderStrategy())
    if 'host' in config.tenant_resolution:
        strategies.append(HostHeaderStrategy(base_domain=config.tenant_base_domain))
    if 'path' in config.tenant_resolution:
        strategies.append(PathPrefixStrategy())

    # Default strategy if none configured
    if not strategies:
        strategies = [TokenClaimStrategy(), HeaderStrategy()]

    app.add_middleware(
        TenantMiddleware,
        strategy=ChainedStrategy(strategies),
        require_tenant=config.require_tenant,
        default_tenant_slug=config.default_tenant_slug,
    )

# Auto-discover and register all feature routers
features_path = Path(__file__).parent / "core"
routers = discover_routers(features_path)

for router, feature_name in routers:
    app.include_router(router, prefix=prefix)

app.include_router(version_router, prefix=prefix)
app.include_router(scopes_router, prefix=prefix)


@app.websocket("/ws/notifications")
async def ws_notifications(
    websocket: WebSocket,
    token: str | None = Query(default=None),
):
    """Real-time WebSocket endpoint for dArchiva notifications.

    Clients connect with: ws://host/ws/notifications?token=<bearer_token>
    Messages are pushed from Redis pub/sub channel darchiva:notifications:{tenant_id}.
    """
    from fastapi.security import SecurityScopes
    from papermerge.core.db.engine import AsyncSessionLocal
    from papermerge.core.features.api_tokens.db.api import is_pat_token
    from papermerge.core.features.auth import (
        _authenticate_with_pat,
        _authenticate_with_jwt,
    )
    from papermerge.core.features.notifications.websocket import notifications_handler

    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    async with AsyncSessionLocal() as db_session:
        security_scopes = SecurityScopes(scopes=[])
        try:
            if is_pat_token(token):
                user = await _authenticate_with_pat(token, db_session, security_scopes)
            else:
                user = await _authenticate_with_jwt(token, db_session, security_scopes)
        except Exception:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        if not user:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        tenant_id = str(user.tenant_id) if user.tenant_id else str(user.id)
        await notifications_handler(websocket, tenant_id)


@app.websocket("/ws/workflows/notifications")
async def ws_workflow_notifications(
    websocket: WebSocket,
    token: str | None = Query(default=None),
):
    """Real-time WebSocket endpoint for workflow notifications.

    Clients connect with: ws://host/ws/workflows/notifications?token=<bearer_token>
    """
    from fastapi.security import SecurityScopes
    from papermerge.core.db.engine import AsyncSessionLocal
    from papermerge.core.features.api_tokens.db.api import is_pat_token
    from papermerge.core.features.auth import (
        _authenticate_with_pat,
        _authenticate_with_jwt,
    )
    from papermerge.core.features.workflows.websocket import workflow_notifications_handler

    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    async with AsyncSessionLocal() as db_session:
        security_scopes = SecurityScopes(scopes=[])
        try:
            if is_pat_token(token):
                user = await _authenticate_with_pat(token, db_session, security_scopes)
            else:
                user = await _authenticate_with_jwt(token, db_session, security_scopes)
        except Exception:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        if not user:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        await workflow_notifications_handler(websocket, user.id, user.tenant_id)


logging_config_path = Path(
    os.environ.get("PAPERMERGE__MAIN__LOGGING_CFG", "/etc/papermerge/logging.yaml")
)

if logging_config_path.exists() and logging_config_path.is_file():
    with open(logging_config_path, "r") as stream:
        config = yaml.load(stream, Loader=yaml.FullLoader)

    dictConfig(config)


app.openapi = create_custom_openapi_generator(app)

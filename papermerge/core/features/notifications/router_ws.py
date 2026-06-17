# (c) Copyright Datacraft, 2026
"""
WebSocket router for dArchiva real-time notifications.

Endpoint: GET /ws/notifications?token=<bearer_token>

This file is named router_ws.py so it is auto-discovered by router_loader
(which picks up all router_*.py files).  The router exposes no HTTP routes —
the WebSocket route is registered directly on the FastAPI app in papermerge/app.py
because FastAPI's APIRouter does not support @router.websocket() registration
via include_router in all versions.  This module exists as the logical home for
the WS endpoint and is imported by app.py.
"""
from fastapi import APIRouter

# Empty HTTP router so router_loader does not error on import.
# The actual WebSocket endpoint lives in papermerge/app.py.
router = APIRouter(
	prefix="/ws",
	tags=["notifications-ws"],
)

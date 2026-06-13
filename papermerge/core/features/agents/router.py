"""FastAPI router for the scan agent registry."""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.auth import get_current_user
from papermerge.core.db.engine import get_db
from papermerge.core.features.users.schema import User

from . import service
from .views import (
	AgentConfigUpdate,
	AgentOut,
	AgentRegisterRequest,
	AgentRegisterResponse,
	HeartbeatResponse,
	PushedConfig,
)

router = APIRouter(prefix="/agents", tags=["agents"])


def _client_ip(request: Request) -> str | None:
	xff = request.headers.get("X-Forwarded-For")
	if xff:
		return xff.split(",")[0].strip()
	return request.client.host if request.client else None


# ── Registration (no user auth — agent posts its token) ──────────────────────

@router.post("/register", response_model=AgentRegisterResponse, status_code=201)
async def register_agent(
	req: AgentRegisterRequest,
	request: Request,
	current_user: User = Depends(get_current_user),
	db: AsyncSession = Depends(get_db),
):
	"""Called by the scan agent on startup to register itself with the server."""
	agent = await service.register(
		db,
		tenant_id=str(current_user.tenant_id),
		req=req,
		ip_address=_client_ip(request),
	)
	pushed = PushedConfig(**agent.pushed_config) if agent.pushed_config else None
	return AgentRegisterResponse(agent_id=agent.id, pushed_config=pushed)


# ── Heartbeat ─────────────────────────────────────────────────────────────────

@router.get("/{agent_id}/heartbeat", status_code=200)
async def agent_heartbeat(
	agent_id: str,
	current_user: User = Depends(get_current_user),
	db: AsyncSession = Depends(get_db),
):
	"""Called every 60 s by the agent. Returns pushed_config if updated."""
	agent = await service.heartbeat(
		db, tenant_id=str(current_user.tenant_id), agent_id=agent_id
	)
	if agent is None:
		raise HTTPException(status_code=404, detail="Agent not found")

	if not agent.pushed_config:
		# 204 = no config update; agent treats this as a clean heartbeat
		from fastapi.responses import Response
		return Response(status_code=204)

	return HeartbeatResponse(pushed_config=PushedConfig(**agent.pushed_config))


# ── Fleet management (admin UI) ───────────────────────────────────────────────

@router.get("", response_model=list[AgentOut])
async def list_agents(
	current_user: User = Depends(get_current_user),
	db: AsyncSession = Depends(get_db),
):
	"""List all registered agents for the tenant."""
	return await service.list_agents(db, tenant_id=str(current_user.tenant_id))


@router.get("/{agent_id}", response_model=AgentOut)
async def get_agent(
	agent_id: str,
	current_user: User = Depends(get_current_user),
	db: AsyncSession = Depends(get_db),
):
	agent = await service.get_agent(
		db, tenant_id=str(current_user.tenant_id), agent_id=agent_id
	)
	if agent is None:
		raise HTTPException(status_code=404, detail="Agent not found")
	return agent


@router.put("/{agent_id}/config", response_model=AgentOut)
async def push_agent_config(
	agent_id: str,
	body: AgentConfigUpdate,
	current_user: User = Depends(get_current_user),
	db: AsyncSession = Depends(get_db),
):
	"""Push a config update to the agent. It will apply on next heartbeat."""
	config = body.model_dump(exclude_none=True)
	agent = await service.push_config(
		db,
		tenant_id=str(current_user.tenant_id),
		agent_id=agent_id,
		config=config,
	)
	if agent is None:
		raise HTTPException(status_code=404, detail="Agent not found")
	return agent


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(
	agent_id: str,
	current_user: User = Depends(get_current_user),
	db: AsyncSession = Depends(get_db),
):
	deleted = await service.delete_agent(
		db, tenant_id=str(current_user.tenant_id), agent_id=agent_id
	)
	if not deleted:
		raise HTTPException(status_code=404, detail="Agent not found")

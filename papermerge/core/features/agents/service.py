"""Business logic for the scan agent registry."""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import AgentModel
from .views import AgentOut, AgentRegisterRequest, PushedConfig


_ONLINE_THRESHOLD = timedelta(seconds=90)


def _to_out(agent: AgentModel) -> AgentOut:
	now = datetime.now(timezone.utc)
	online = (
		agent.last_seen is not None
		and (now - agent.last_seen.replace(tzinfo=timezone.utc)) < _ONLINE_THRESHOLD
	)
	pushed = None
	if agent.pushed_config:
		pushed = PushedConfig(**agent.pushed_config)
	return AgentOut(
		id=agent.id,
		name=agent.name,
		hostname=agent.hostname,
		platform=agent.platform,
		version=agent.version,
		port=agent.port,
		ip_address=agent.ip_address,
		online=online,
		last_seen=agent.last_seen,
		pushed_config=pushed,
		created_at=agent.created_at,
	)


async def register(
	db: AsyncSession,
	tenant_id: str,
	req: AgentRegisterRequest,
	ip_address: str | None,
) -> AgentModel:
	"""Create or update a scan agent registration."""
	agent = None

	# Try to find existing record by provided agent_id
	if req.agent_id:
		result = await db.execute(
			select(AgentModel).where(
				AgentModel.id == req.agent_id,
				AgentModel.tenant_id == tenant_id,
			)
		)
		agent = result.scalar_one_or_none()

	if agent is None:
		# New agent — check if same hostname already exists
		result = await db.execute(
			select(AgentModel).where(
				AgentModel.hostname == req.hostname,
				AgentModel.tenant_id == tenant_id,
			)
		)
		agent = result.scalar_one_or_none()

	if agent is None:
		agent = AgentModel(
			id=str(uuid.uuid4()),
			tenant_id=tenant_id,
		)
		db.add(agent)

	agent.name = req.name or req.hostname
	agent.hostname = req.hostname
	agent.platform = req.platform
	agent.version = req.version
	agent.port = req.port
	agent.ip_address = ip_address
	agent.last_seen = datetime.now(timezone.utc)

	await db.commit()
	await db.refresh(agent)
	return agent


async def heartbeat(
	db: AsyncSession,
	tenant_id: str,
	agent_id: str,
) -> AgentModel | None:
	"""Record a heartbeat and return the agent (with any pushed config)."""
	result = await db.execute(
		select(AgentModel).where(
			AgentModel.id == agent_id,
			AgentModel.tenant_id == tenant_id,
		)
	)
	agent = result.scalar_one_or_none()
	if agent is None:
		return None

	agent.last_seen = datetime.now(timezone.utc)
	await db.commit()
	await db.refresh(agent)
	return agent


async def list_agents(db: AsyncSession, tenant_id: str) -> list[AgentOut]:
	result = await db.execute(
		select(AgentModel)
		.where(AgentModel.tenant_id == tenant_id)
		.order_by(AgentModel.name)
	)
	return [_to_out(a) for a in result.scalars()]


async def get_agent(
	db: AsyncSession, tenant_id: str, agent_id: str
) -> AgentOut | None:
	result = await db.execute(
		select(AgentModel).where(
			AgentModel.id == agent_id,
			AgentModel.tenant_id == tenant_id,
		)
	)
	agent = result.scalar_one_or_none()
	return _to_out(agent) if agent else None


async def push_config(
	db: AsyncSession,
	tenant_id: str,
	agent_id: str,
	config: dict,
) -> AgentOut | None:
	result = await db.execute(
		select(AgentModel).where(
			AgentModel.id == agent_id,
			AgentModel.tenant_id == tenant_id,
		)
	)
	agent = result.scalar_one_or_none()
	if agent is None:
		return None

	agent.pushed_config = config
	await db.commit()
	await db.refresh(agent)
	return _to_out(agent)


async def delete_agent(
	db: AsyncSession, tenant_id: str, agent_id: str
) -> bool:
	result = await db.execute(
		select(AgentModel).where(
			AgentModel.id == agent_id,
			AgentModel.tenant_id == tenant_id,
		)
	)
	agent = result.scalar_one_or_none()
	if agent is None:
		return False
	await db.delete(agent)
	await db.commit()
	return True

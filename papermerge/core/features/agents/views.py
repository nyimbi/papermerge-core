"""Pydantic schemas for the scan agent registry feature."""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AgentRegisterRequest(BaseModel):
	model_config = ConfigDict(extra="ignore")

	agent_id: str | None = None          # omit on first registration
	name: str = ""
	hostname: str
	platform: str                        # linux | darwin | windows
	version: str = "unknown"
	port: int = 7780


class PushedConfig(BaseModel):
	"""Subset of agent config the admin can push remotely."""
	server_url: str | None = None
	default_project_id: str | None = None
	hotkeys: dict[str, str] | None = None


class AgentRegisterResponse(BaseModel):
	agent_id: str
	pushed_config: PushedConfig | None = None


class HeartbeatResponse(BaseModel):
	pushed_config: PushedConfig | None = None


class AgentConfigUpdate(BaseModel):
	"""Admin pushes this to override agent config remotely."""
	model_config = ConfigDict(extra="forbid")

	server_url: str | None = None
	default_project_id: str | None = None
	hotkeys: dict[str, str] | None = None


class AgentOut(BaseModel):
	"""Public representation of a registered agent."""
	id: str
	name: str
	hostname: str
	platform: str
	version: str
	port: int
	ip_address: str | None
	online: bool                         # True if last_seen within 90s
	last_seen: datetime | None
	pushed_config: PushedConfig | None
	created_at: datetime

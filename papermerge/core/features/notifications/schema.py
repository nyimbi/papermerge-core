from typing import Literal
from pydantic import BaseModel


class NotificationOut(BaseModel):
	id: str
	type: Literal['success', 'error', 'warning', 'info']
	title: str
	message: str
	timestamp: str  # ISO format
	read: bool
	link: str | None = None
	metadata: dict | None = None

	model_config = {"from_attributes": True}


class NotificationCreate(BaseModel):
	type: Literal['success', 'error', 'warning', 'info']
	title: str
	message: str
	link: str | None = None
	metadata: dict | None = None
	user_id: str  # target user

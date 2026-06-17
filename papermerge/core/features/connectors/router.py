# (c) Copyright Datacraft, 2026
"""FastAPI router for external connector management.

Auto-discovered by the router-scanning mechanism in the app factory.
"""
from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

import requests
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.engine import get_db
from papermerge.core.features.auth import get_current_user
from papermerge.core.features.connectors.db.orm import ConnectorConfig
from papermerge.core.features.connectors.service import (
	list_dropbox_folders,
	list_dropbox_files_preview,
	sync_dropbox_folder,
	sync_local_folder,
)

router = APIRouter(prefix="/connectors", tags=["connectors"])
_log = logging.getLogger(__name__)

DROPBOX_TOKEN_URL = "https://api.dropboxapi.com/oauth2/token"


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ConnectorOut(BaseModel):
	id: str
	name: str
	connector_type: str
	watch_folder_id: str | None
	watch_folder_name: str | None
	destination_folder_id: str | None
	last_sync_at: str | None
	last_file_count: int
	is_active: bool
	sync_interval_minutes: int
	tenant_id: str
	created_by_id: str
	created_at: str

	model_config = {"from_attributes": True}

	@classmethod
	def from_orm_obj(cls, obj: ConnectorConfig) -> "ConnectorOut":
		return cls(
			id=str(obj.id),
			name=obj.name,
			connector_type=obj.connector_type,
			watch_folder_id=obj.watch_folder_id,
			watch_folder_name=obj.watch_folder_name,
			destination_folder_id=obj.destination_folder_id,
			last_sync_at=obj.last_sync_at.isoformat() if obj.last_sync_at else None,
			last_file_count=obj.last_file_count,
			is_active=obj.is_active,
			sync_interval_minutes=obj.sync_interval_minutes,
			tenant_id=str(obj.tenant_id),
			created_by_id=str(obj.created_by_id),
			created_at=obj.created_at.isoformat(),
		)


class ConnectorCreate(BaseModel):
	name: str
	connector_type: str
	config_json: str = "{}"
	watch_folder_id: str | None = None
	watch_folder_name: str | None = None
	destination_folder_id: str | None = None
	sync_interval_minutes: int = 60


class ConnectorUpdate(BaseModel):
	name: str | None = None
	config_json: str | None = None
	watch_folder_id: str | None = None
	watch_folder_name: str | None = None
	destination_folder_id: str | None = None
	is_active: bool | None = None
	sync_interval_minutes: int | None = None


class SyncResult(BaseModel):
	new_files: int
	status: str  # "ok" | "error"
	message: str | None = None


class DropboxTokenExchange(BaseModel):
	code: str
	redirect_uri: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tenant_str(user) -> str:
	tid = getattr(user, "tenant_id", None)
	return str(tid) if tid else str(user.id)


async def _get_owned(db: AsyncSession, connector_id: str, tenant_id: str) -> ConnectorConfig:
	try:
		cid = UUID(connector_id)
	except ValueError:
		raise HTTPException(status_code=404, detail="Connector not found")

	result = await db.execute(
		select(ConnectorConfig).where(
			ConnectorConfig.id == cid,
			ConnectorConfig.tenant_id == tenant_id,
		)
	)
	obj = result.scalar_one_or_none()
	if obj is None:
		raise HTTPException(status_code=404, detail="Connector not found")
	return obj


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/", response_model=list[ConnectorOut])
async def list_connectors(
	user=Depends(get_current_user),
	db: AsyncSession = Depends(get_db),
) -> list[ConnectorOut]:
	"""List all connector configs for the current tenant."""
	tid = _tenant_str(user)
	result = await db.execute(
		select(ConnectorConfig)
		.where(ConnectorConfig.tenant_id == tid)
		.order_by(ConnectorConfig.created_at.desc())
	)
	rows = result.scalars().all()
	return [ConnectorOut.from_orm_obj(r) for r in rows]


@router.post("/", response_model=ConnectorOut, status_code=201)
async def create_connector(
	body: ConnectorCreate,
	user=Depends(get_current_user),
	db: AsyncSession = Depends(get_db),
) -> ConnectorOut:
	"""Create a new connector configuration."""
	tid = _tenant_str(user)
	uid = str(user.id)

	obj = ConnectorConfig(
		name=body.name,
		connector_type=body.connector_type,
		config_json=body.config_json,
		watch_folder_id=body.watch_folder_id,
		watch_folder_name=body.watch_folder_name,
		destination_folder_id=body.destination_folder_id,
		sync_interval_minutes=body.sync_interval_minutes,
		tenant_id=tid,
		created_by_id=uid,
	)
	db.add(obj)
	await db.commit()
	await db.refresh(obj)
	_log.info("connector created id=%s tenant=%s type=%s", obj.id, tid, obj.connector_type)
	return ConnectorOut.from_orm_obj(obj)


@router.patch("/{connector_id}", response_model=ConnectorOut)
async def update_connector(
	connector_id: str,
	body: ConnectorUpdate,
	user=Depends(get_current_user),
	db: AsyncSession = Depends(get_db),
) -> ConnectorOut:
	"""Update a connector configuration."""
	tid = _tenant_str(user)
	obj = await _get_owned(db, connector_id, tid)

	if body.name is not None:
		obj.name = body.name
	if body.config_json is not None:
		obj.config_json = body.config_json
	if body.watch_folder_id is not None:
		obj.watch_folder_id = body.watch_folder_id
	if body.watch_folder_name is not None:
		obj.watch_folder_name = body.watch_folder_name
	if body.destination_folder_id is not None:
		obj.destination_folder_id = body.destination_folder_id
	if body.is_active is not None:
		obj.is_active = body.is_active
	if body.sync_interval_minutes is not None:
		obj.sync_interval_minutes = body.sync_interval_minutes

	await db.commit()
	await db.refresh(obj)
	return ConnectorOut.from_orm_obj(obj)


@router.delete("/{connector_id}", status_code=204)
async def delete_connector(
	connector_id: str,
	user=Depends(get_current_user),
	db: AsyncSession = Depends(get_db),
) -> None:
	"""Delete a connector configuration."""
	tid = _tenant_str(user)
	obj = await _get_owned(db, connector_id, tid)
	await db.delete(obj)
	await db.commit()


@router.post("/{connector_id}/sync", response_model=SyncResult)
async def trigger_sync(
	connector_id: str,
	user=Depends(get_current_user),
	db: AsyncSession = Depends(get_db),
) -> SyncResult:
	"""Trigger an immediate manual sync for a connector."""
	tid = _tenant_str(user)
	obj = await _get_owned(db, connector_id, tid)

	try:
		if obj.connector_type == "dropbox":
			new_files = await sync_dropbox_folder(obj, db)
		elif obj.connector_type == "local_folder":
			new_files = await sync_local_folder(obj, db)
		else:
			return SyncResult(
				new_files=0,
				status="error",
				message=f"Sync not implemented for connector type: {obj.connector_type}",
			)
	except Exception as exc:
		_log.error("trigger_sync: connector=%s error=%s", connector_id, exc)
		return SyncResult(new_files=0, status="error", message=str(exc))

	return SyncResult(new_files=new_files, status="ok")


@router.get("/{connector_id}/preview", response_model=list[dict[str, Any]])
async def preview_connector(
	connector_id: str,
	user=Depends(get_current_user),
	db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
	"""List the first 20 files in the watched folder (preview only)."""
	tid = _tenant_str(user)
	obj = await _get_owned(db, connector_id, tid)

	cfg = json.loads(obj.config_json or "{}")

	if obj.connector_type == "dropbox":
		access_token = cfg.get("access_token", "")
		folder_path = obj.watch_folder_id or cfg.get("folder_path", "")
		try:
			return await list_dropbox_files_preview(access_token, folder_path)
		except Exception as exc:
			raise HTTPException(status_code=502, detail=f"Dropbox API error: {exc}")

	elif obj.connector_type == "local_folder":
		from pathlib import Path

		root = Path(cfg.get("folder_path", obj.watch_folder_id or ""))
		if not root.is_dir():
			raise HTTPException(status_code=400, detail="Folder path not found")
		files = sorted(root.iterdir())[:20]
		return [
			{
				"name": f.name,
				"path": str(f),
				"size": f.stat().st_size if f.is_file() else 0,
			}
			for f in files
			if f.is_file()
		]

	raise HTTPException(status_code=400, detail=f"Preview not supported for type: {obj.connector_type}")


@router.post("/dropbox/exchange-token")
async def exchange_dropbox_token(
	body: DropboxTokenExchange,
	user=Depends(get_current_user),
) -> dict[str, str]:
	"""
	Exchange a Dropbox OAuth2 authorization code for an access token.

	Requires DROPBOX_APP_KEY and DROPBOX_APP_SECRET env vars.
	"""
	import os

	app_key = os.environ.get("DROPBOX_APP_KEY", "")
	app_secret = os.environ.get("DROPBOX_APP_SECRET", "")
	if not app_key or not app_secret:
		raise HTTPException(
			status_code=500,
			detail="Dropbox OAuth app credentials not configured (DROPBOX_APP_KEY / DROPBOX_APP_SECRET)",
		)

	params: dict[str, str] = {
		"code": body.code,
		"grant_type": "authorization_code",
	}
	if body.redirect_uri:
		params["redirect_uri"] = body.redirect_uri

	try:
		resp = requests.post(
			DROPBOX_TOKEN_URL,
			data=params,
			auth=(app_key, app_secret),
			timeout=15,
		)
		resp.raise_for_status()
	except requests.HTTPError as exc:
		raise HTTPException(status_code=502, detail=f"Dropbox token exchange failed: {exc}")

	data = resp.json()
	return {
		"access_token": data.get("access_token", ""),
		"token_type": data.get("token_type", "bearer"),
		"account_id": data.get("account_id", ""),
		"uid": data.get("uid", ""),
	}


@router.get("/dropbox/folders")
async def list_dropbox_folder_tree(
	access_token: str,
	user=Depends(get_current_user),
) -> list[dict[str, str]]:
	"""List root-level Dropbox folders for a given access token."""
	try:
		folders = await list_dropbox_folders(access_token)
	except Exception as exc:
		raise HTTPException(status_code=502, detail=f"Dropbox API error: {exc}")
	return folders

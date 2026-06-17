# (c) Copyright Datacraft, 2026
"""Sync logic for external connector types: Dropbox and local folder."""
from __future__ import annotations

import json
import logging
import mimetypes
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import requests
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.features.connectors.db.orm import ConnectorConfig

_log = logging.getLogger(__name__)

DROPBOX_API_BASE = "https://api.dropboxapi.com/2"
DROPBOX_CONTENT_BASE = "https://content.dropboxapi.com/2"

# ---------------------------------------------------------------------------
# Dropbox helpers
# ---------------------------------------------------------------------------


def _dropbox_headers(access_token: str) -> dict[str, str]:
	return {"Authorization": f"Bearer {access_token}"}


def _list_dropbox_entries(access_token: str, folder_path: str = "") -> list[dict]:
	"""Return all file entries in a Dropbox folder (handles cursor pagination)."""
	url = f"{DROPBOX_API_BASE}/files/list_folder"
	headers = {**_dropbox_headers(access_token), "Content-Type": "application/json"}
	body: dict = {"path": folder_path or "", "recursive": False, "limit": 200}
	entries: list[dict] = []

	while True:
		resp = requests.post(url, headers=headers, json=body, timeout=30)
		resp.raise_for_status()
		data = resp.json()
		entries.extend(
			e for e in data.get("entries", []) if e.get(".tag") == "file"
		)
		if not data.get("has_more"):
			break
		# continue with cursor
		url = f"{DROPBOX_API_BASE}/files/list_folder/continue"
		body = {"cursor": data["cursor"]}  # type: ignore[assignment]

	return entries


def _download_dropbox_file(access_token: str, dropbox_path: str) -> bytes:
	url = f"{DROPBOX_CONTENT_BASE}/files/download"
	headers = {
		**_dropbox_headers(access_token),
		"Dropbox-API-Arg": json.dumps({"path": dropbox_path}),
	}
	resp = requests.post(url, headers=headers, timeout=120)
	resp.raise_for_status()
	return resp.content


async def _ingest_bytes(
	content: bytes,
	filename: str,
	destination_folder_id: str | None,
	session: AsyncSession,
) -> bool:
	"""
	Ingest a file into papermerge as a document.

	Returns True if successfully ingested.
	"""
	try:
		from papermerge.core.features.documents.db import api as docs_api

		mime_type, _ = mimetypes.guess_type(filename)
		mime_type = mime_type or "application/octet-stream"

		# Write to a temp file then hand off to the document ingest pipeline
		import tempfile

		with tempfile.NamedTemporaryFile(suffix=Path(filename).suffix, delete=False) as tmp:
			tmp.write(content)
			tmp_path = tmp.name

		try:
			await docs_api.upload_file(
				session=session,
				file_path=tmp_path,
				filename=filename,
				mime_type=mime_type,
				parent_id=destination_folder_id,
			)
		finally:
			os.unlink(tmp_path)

		return True
	except Exception as exc:
		_log.error("_ingest_bytes: failed for %s: %s", filename, exc)
		return False


# ---------------------------------------------------------------------------
# Public sync functions
# ---------------------------------------------------------------------------


async def list_dropbox_folders(access_token: str) -> list[dict]:
	"""
	List root-level folders in the user's Dropbox.

	Returns list of dicts: {id, name, path}.
	"""
	headers = {**_dropbox_headers(access_token), "Content-Type": "application/json"}
	resp = requests.post(
		f"{DROPBOX_API_BASE}/files/list_folder",
		headers=headers,
		json={"path": "", "recursive": False},
		timeout=30,
	)
	resp.raise_for_status()
	data = resp.json()
	folders = [
		{
			"id": e.get("id", e["path_lower"]),
			"name": e["name"],
			"path": e["path_lower"],
		}
		for e in data.get("entries", [])
		if e.get(".tag") == "folder"
	]
	return folders


async def list_dropbox_files_preview(access_token: str, folder_path: str = "") -> list[dict]:
	"""Return first 20 file entries in a Dropbox folder for preview."""
	entries = _list_dropbox_entries(access_token, folder_path)
	return [
		{
			"name": e["name"],
			"path": e["path_lower"],
			"size": e.get("size", 0),
			"modified": e.get("client_modified"),
		}
		for e in entries[:20]
	]


async def sync_dropbox_folder(config: ConnectorConfig, session: AsyncSession) -> int:
	"""
	Download new files from the watched Dropbox folder and ingest them.

	Returns the count of newly ingested files.
	"""
	cfg = json.loads(config.config_json or "{}")
	access_token: str | None = cfg.get("access_token")
	if not access_token:
		_log.error("sync_dropbox_folder: no access_token for connector %s", config.id)
		return 0

	folder_path: str = config.watch_folder_id or cfg.get("folder_path", "")
	last_sync = config.last_sync_at

	try:
		entries = _list_dropbox_entries(access_token, folder_path)
	except requests.HTTPError as exc:
		_log.error("sync_dropbox_folder: Dropbox API error: %s", exc)
		return 0

	new_count = 0
	for entry in entries:
		modified_str: str | None = entry.get("client_modified")
		if last_sync and modified_str:
			try:
				modified_dt = datetime.fromisoformat(modified_str.replace("Z", "+00:00"))
				if modified_dt <= last_sync:
					continue
			except ValueError:
				pass  # fall through and ingest anyway

		try:
			content = _download_dropbox_file(access_token, entry["path_lower"])
		except Exception as exc:
			_log.error("sync_dropbox_folder: download failed for %s: %s", entry["name"], exc)
			continue

		ok = await _ingest_bytes(
			content,
			entry["name"],
			config.destination_folder_id,
			session,
		)
		if ok:
			new_count += 1

	# Update sync metadata
	config.last_sync_at = datetime.now(timezone.utc)
	config.last_file_count = new_count
	await session.commit()

	_log.info(
		"sync_dropbox_folder: connector=%s new_files=%d",
		config.id,
		new_count,
	)
	return new_count


async def sync_local_folder(config: ConnectorConfig, session: AsyncSession) -> int:
	"""
	Watch a local filesystem path and ingest any new files since last sync.

	Returns the count of newly ingested files.
	"""
	cfg = json.loads(config.config_json or "{}")
	folder_path: str | None = cfg.get("folder_path") or config.watch_folder_id
	if not folder_path:
		_log.error("sync_local_folder: no folder_path for connector %s", config.id)
		return 0

	root = Path(folder_path)
	if not root.is_dir():
		_log.error("sync_local_folder: path not found or not a dir: %s", root)
		return 0

	last_sync = config.last_sync_at
	new_count = 0

	for fpath in sorted(root.iterdir()):
		if not fpath.is_file():
			continue
		mtime = datetime.fromtimestamp(fpath.stat().st_mtime, tz=timezone.utc)
		if last_sync and mtime <= last_sync:
			continue

		try:
			content = fpath.read_bytes()
		except OSError as exc:
			_log.error("sync_local_folder: cannot read %s: %s", fpath, exc)
			continue

		ok = await _ingest_bytes(
			content,
			fpath.name,
			config.destination_folder_id,
			session,
		)
		if ok:
			new_count += 1

	config.last_sync_at = datetime.now(timezone.utc)
	config.last_file_count = new_count
	await session.commit()

	_log.info("sync_local_folder: connector=%s new_files=%d", config.id, new_count)
	return new_count

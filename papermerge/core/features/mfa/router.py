# (c) Copyright Datacraft, 2026
"""MFA (Multi-Factor Authentication) router — TOTP and backup codes."""
import hashlib
import io
import logging
import secrets
import uuid
from datetime import datetime
from typing import Annotated, Any

import pyotp
import qrcode
from fastapi import APIRouter, Depends, HTTPException, Security, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core import schema
from papermerge.core.db.engine import get_db
from papermerge.core.features.auth import get_current_user
from papermerge.core.features.mfa.db.orm import UserMFASettings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mfa", tags=["mfa"])

_BACKUP_CODE_COUNT = 10


def _hash_code(code: str) -> str:
	return hashlib.sha256(code.strip().lower().encode()).hexdigest()


def _generate_backup_codes() -> tuple[list[str], list[str]]:
	"""Return (plaintext_codes, hashed_codes)."""
	plain = [secrets.token_hex(4).upper() for _ in range(_BACKUP_CODE_COUNT)]
	hashed = [_hash_code(c) for c in plain]
	return plain, hashed


async def _get_or_create_mfa(db: AsyncSession, user_id: uuid.UUID) -> UserMFASettings:
	row = (await db.execute(
		select(UserMFASettings).where(UserMFASettings.user_id == user_id)
	)).scalar_one_or_none()
	if row is None:
		row = UserMFASettings(user_id=user_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
		db.add(row)
		await db.flush()
	return row


@router.get("/status")
async def get_mfa_status(
	user: Annotated[schema.User, Depends(get_current_user)],
	db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
	"""Return MFA status for the current user."""
	row = (await db.execute(
		select(UserMFASettings).where(UserMFASettings.user_id == user.id)
	)).scalar_one_or_none()
	return {
		"totp_enabled": row.totp_enabled if row else False,
		"backup_codes_remaining": len([c for c in (row.backup_codes or [])]) if row else 0,
	}


@router.post("/totp/setup")
async def setup_totp(
	user: Annotated[schema.User, Depends(get_current_user)],
	db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
	"""Generate a new TOTP secret and return provisioning URI + QR code data URL."""
	mfa = await _get_or_create_mfa(db, user.id)
	secret = pyotp.random_base32()
	mfa.totp_secret = secret
	mfa.totp_enabled = False
	mfa.updated_at = datetime.utcnow()
	await db.commit()

	issuer = "dArchiva"
	label = user.email or user.username
	uri = pyotp.totp.TOTP(secret).provisioning_uri(name=label, issuer_name=issuer)

	# Generate QR code as data URL
	img = qrcode.make(uri)
	buf = io.BytesIO()
	img.save(buf, format="PNG")
	import base64
	qr_b64 = base64.b64encode(buf.getvalue()).decode()

	return {
		"secret": secret,
		"otpauth_url": uri,
		"qr_code_url": f"data:image/png;base64,{qr_b64}",
	}


@router.post("/totp/enable")
async def enable_totp(
	body: dict[str, Any],
	user: Annotated[schema.User, Depends(get_current_user)],
	db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
	"""Verify TOTP code and enable TOTP for the user."""
	code = str(body.get("code", "")).strip()
	mfa = (await db.execute(
		select(UserMFASettings).where(UserMFASettings.user_id == user.id)
	)).scalar_one_or_none()
	if not mfa or not mfa.totp_secret:
		raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="TOTP not configured. Call /mfa/totp/setup first.")

	totp = pyotp.TOTP(mfa.totp_secret)
	if not totp.verify(code, valid_window=1):
		raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid TOTP code")

	mfa.totp_enabled = True
	mfa.updated_at = datetime.utcnow()
	await db.commit()
	return {"success": True}


@router.post("/totp/verify")
async def verify_totp(
	body: dict[str, Any],
	user: Annotated[schema.User, Depends(get_current_user)],
	db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
	"""Verify a TOTP code (used during 2FA login step)."""
	code = str(body.get("code", "")).strip()
	mfa = (await db.execute(
		select(UserMFASettings).where(UserMFASettings.user_id == user.id)
	)).scalar_one_or_none()
	if not mfa or not mfa.totp_enabled or not mfa.totp_secret:
		raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="TOTP not enabled")

	totp = pyotp.TOTP(mfa.totp_secret)
	if not totp.verify(code, valid_window=1):
		raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid TOTP code")

	return {"success": True}


@router.post("/totp/disable")
async def disable_totp(
	body: dict[str, Any],
	user: Annotated[schema.User, Depends(get_current_user)],
	db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
	"""Disable TOTP after verifying the current code."""
	code = str(body.get("code", "")).strip()
	mfa = (await db.execute(
		select(UserMFASettings).where(UserMFASettings.user_id == user.id)
	)).scalar_one_or_none()
	if not mfa or not mfa.totp_enabled or not mfa.totp_secret:
		raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="TOTP not enabled")

	totp = pyotp.TOTP(mfa.totp_secret)
	if not totp.verify(code, valid_window=1):
		raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid TOTP code")

	mfa.totp_enabled = False
	mfa.totp_secret = None
	mfa.updated_at = datetime.utcnow()
	await db.commit()
	return {"success": True}


@router.post("/backup-codes/regenerate")
async def regenerate_backup_codes(
	body: dict[str, Any],
	user: Annotated[schema.User, Depends(get_current_user)],
	db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
	"""Regenerate backup codes. Requires current TOTP code for verification."""
	code = str(body.get("code", "")).strip()
	mfa = await _get_or_create_mfa(db, user.id)

	if mfa.totp_enabled and mfa.totp_secret:
		totp = pyotp.TOTP(mfa.totp_secret)
		if not totp.verify(code, valid_window=1):
			raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid TOTP code")

	plain_codes, hashed_codes = _generate_backup_codes()
	mfa.backup_codes = hashed_codes
	mfa.backup_codes_generated_at = datetime.utcnow()
	mfa.updated_at = datetime.utcnow()
	await db.commit()

	return {"codes": plain_codes, "remaining": len(plain_codes)}


@router.post("/backup-codes/verify")
async def verify_backup_code(
	body: dict[str, Any],
	user: Annotated[schema.User, Depends(get_current_user)],
	db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
	"""Consume a backup code (one-time use)."""
	code = str(body.get("code", "")).strip()
	hashed = _hash_code(code)
	mfa = (await db.execute(
		select(UserMFASettings).where(UserMFASettings.user_id == user.id)
	)).scalar_one_or_none()
	if not mfa or not mfa.backup_codes:
		raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No backup codes available")

	if hashed not in mfa.backup_codes:
		raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid backup code")

	# Consume the code (remove it so it can't be reused)
	mfa.backup_codes = [c for c in mfa.backup_codes if c != hashed]
	mfa.updated_at = datetime.utcnow()
	await db.commit()
	return {"success": True}

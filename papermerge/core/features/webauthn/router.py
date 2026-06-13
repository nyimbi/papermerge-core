# (c) Copyright Datacraft, 2026
"""WebAuthn / FIDO2 passkeys router using py_webauthn."""
import base64
import logging
import uuid
from datetime import datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core import schema
from papermerge.core.features.auth import get_current_user
from papermerge.core.db.engine import get_db
from .db.orm import UserPasskey, WebAuthnChallenge

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webauthn", tags=["webauthn"])

_CHALLENGE_TTL_SECONDS = 300


def _rp_id_and_origin(request: Request) -> tuple[str, str]:
	origin = request.headers.get("origin") or str(request.base_url).rstrip("/")
	from urllib.parse import urlparse
	parsed = urlparse(origin)
	rp_id = parsed.hostname or "localhost"
	return rp_id, origin


def _b64url_encode(data: bytes) -> str:
	return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
	padding = 4 - len(s) % 4
	if padding != 4:
		s += "=" * padding
	return base64.urlsafe_b64decode(s)


@router.get("/passkeys")
async def list_passkeys(
	user: Annotated[schema.User, Depends(get_current_user)],
	db_session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
	"""List registered passkeys for the current user."""
	result = await db_session.execute(
		select(UserPasskey).where(UserPasskey.user_id == user.id)
	)
	passkeys = result.scalars().all()
	return {
		"passkeys": [
			{
				"id": str(pk.id),
				"name": pk.name,
				"created_at": pk.created_at.isoformat() if pk.created_at else None,
				"last_used_at": pk.last_used_at.isoformat() if pk.last_used_at else None,
			}
			for pk in passkeys
		]
	}


@router.post("/register/begin")
async def register_begin(
	request: Request,
	body: dict[str, Any],
	user: Annotated[schema.User, Depends(get_current_user)],
	db_session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
	"""Begin passkey registration (WebAuthn ceremony step 1)."""
	try:
		import webauthn
		from webauthn.helpers.structs import AuthenticatorSelectionCriteria, UserVerificationRequirement
	except ImportError:
		raise HTTPException(status_code=501, detail="WebAuthn library not installed on this server.")

	rp_id, origin = _rp_id_and_origin(request)

	existing = await db_session.execute(
		select(UserPasskey).where(UserPasskey.user_id == user.id)
	)
	existing_credentials = [
		webauthn.helpers.structs.PublicKeyCredentialDescriptor(id=pk.credential_id)
		for pk in existing.scalars().all()
	]

	options = webauthn.generate_registration_options(
		rp_id=rp_id,
		rp_name="dArchiva",
		user_id=str(user.id).encode(),
		user_name=user.username,
		user_display_name=user.username,
		exclude_credentials=existing_credentials,
		authenticator_selection=AuthenticatorSelectionCriteria(
			user_verification=UserVerificationRequirement.PREFERRED,
		),
	)

	# Store challenge
	now = datetime.utcnow()
	db_session.add(WebAuthnChallenge(
		id=uuid.uuid4(),
		user_id=user.id,
		challenge=options.challenge,
		challenge_type="registration",
		created_at=now,
		expires_at=now + timedelta(seconds=_CHALLENGE_TTL_SECONDS),
	))
	await db_session.commit()

	options_json = webauthn.options_to_json(options)
	import json
	return json.loads(options_json)


@router.post("/register/complete")
async def register_complete(
	request: Request,
	body: dict[str, Any],
	user: Annotated[schema.User, Depends(get_current_user)],
	db_session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
	"""Complete passkey registration (WebAuthn ceremony step 2)."""
	try:
		import webauthn
		from webauthn.helpers.structs import RegistrationCredential
		from webauthn.helpers.exceptions import InvalidCBORData, InvalidRegistrationResponse
	except ImportError:
		raise HTTPException(status_code=501, detail="WebAuthn library not installed.")

	rp_id, origin = _rp_id_and_origin(request)
	passkey_name = body.pop("passkey_name", "Passkey") or "Passkey"

	# Retrieve and validate challenge
	now = datetime.utcnow()
	result = await db_session.execute(
		select(WebAuthnChallenge).where(
			WebAuthnChallenge.user_id == user.id,
			WebAuthnChallenge.challenge_type == "registration",
			WebAuthnChallenge.expires_at > now,
		).order_by(WebAuthnChallenge.created_at.desc()).limit(1)
	)
	challenge_row = result.scalar_one_or_none()
	if not challenge_row:
		raise HTTPException(status_code=400, detail="No valid registration challenge found. Begin registration first.")

	expected_challenge = challenge_row.challenge

	# Delete challenge (single use)
	await db_session.execute(sa_delete(WebAuthnChallenge).where(WebAuthnChallenge.id == challenge_row.id))

	try:
		import json
		credential = RegistrationCredential.parse_raw(json.dumps(body))
		verified = webauthn.verify_registration_response(
			credential=credential,
			expected_challenge=expected_challenge,
			expected_rp_id=rp_id,
			expected_origin=origin,
		)
	except Exception as exc:
		logger.warning("WebAuthn registration verification failed: %s", exc)
		raise HTTPException(status_code=400, detail=f"Registration verification failed: {exc}")

	passkey = UserPasskey(
		id=uuid.uuid4(),
		user_id=user.id,
		credential_id=verified.credential_id,
		public_key=verified.credential_public_key,
		sign_count=verified.sign_count,
		name=passkey_name,
		created_at=datetime.utcnow(),
	)
	db_session.add(passkey)
	await db_session.commit()

	return {"success": True, "passkeyId": str(passkey.id), "passkeyName": passkey.name}


@router.post("/authenticate/begin")
async def authenticate_begin(
	request: Request,
	body: dict[str, Any],
	db_session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
	"""Begin passkey authentication."""
	try:
		import webauthn
		from webauthn.helpers.structs import UserVerificationRequirement
	except ImportError:
		raise HTTPException(status_code=501, detail="WebAuthn library not installed.")

	rp_id, _origin = _rp_id_and_origin(request)

	options = webauthn.generate_authentication_options(
		rp_id=rp_id,
		user_verification=UserVerificationRequirement.PREFERRED,
	)

	now = datetime.utcnow()
	db_session.add(WebAuthnChallenge(
		id=uuid.uuid4(),
		user_id=None,
		challenge=options.challenge,
		challenge_type="authentication",
		created_at=now,
		expires_at=now + timedelta(seconds=_CHALLENGE_TTL_SECONDS),
	))
	await db_session.commit()

	import json
	options_json = webauthn.options_to_json(options)
	return json.loads(options_json)


@router.post("/authenticate/complete")
async def authenticate_complete(
	request: Request,
	body: dict[str, Any],
	db_session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
	"""Complete passkey authentication. Returns user_id on success."""
	try:
		import webauthn
		from webauthn.helpers.structs import AuthenticationCredential
	except ImportError:
		raise HTTPException(status_code=501, detail="WebAuthn library not installed.")

	rp_id, origin = _rp_id_and_origin(request)

	now = datetime.utcnow()
	result = await db_session.execute(
		select(WebAuthnChallenge).where(
			WebAuthnChallenge.challenge_type == "authentication",
			WebAuthnChallenge.expires_at > now,
		).order_by(WebAuthnChallenge.created_at.desc()).limit(1)
	)
	challenge_row = result.scalar_one_or_none()
	if not challenge_row:
		raise HTTPException(status_code=400, detail="No valid authentication challenge. Begin authentication first.")

	expected_challenge = challenge_row.challenge
	await db_session.execute(sa_delete(WebAuthnChallenge).where(WebAuthnChallenge.id == challenge_row.id))

	# Look up passkey by credential_id from the response
	try:
		raw_id = _b64url_decode(body.get("rawId") or body.get("id", ""))
	except Exception:
		raise HTTPException(status_code=400, detail="Invalid credential ID in request.")

	pk_result = await db_session.execute(
		select(UserPasskey).where(UserPasskey.credential_id == raw_id)
	)
	passkey = pk_result.scalar_one_or_none()
	if not passkey:
		raise HTTPException(status_code=401, detail="Unknown passkey.")

	try:
		import json
		credential = AuthenticationCredential.parse_raw(json.dumps(body))
		verified = webauthn.verify_authentication_response(
			credential=credential,
			expected_challenge=expected_challenge,
			expected_rp_id=rp_id,
			expected_origin=origin,
			credential_public_key=passkey.public_key,
			credential_current_sign_count=passkey.sign_count,
		)
	except Exception as exc:
		logger.warning("WebAuthn authentication verification failed: %s", exc)
		raise HTTPException(status_code=401, detail=f"Authentication failed: {exc}")

	passkey.sign_count = verified.new_sign_count
	passkey.last_used_at = datetime.utcnow()
	await db_session.commit()

	return {"success": True, "userId": str(passkey.user_id)}


@router.patch("/passkeys/{passkey_id}")
async def rename_passkey(
	passkey_id: uuid.UUID,
	body: dict[str, Any],
	user: Annotated[schema.User, Depends(get_current_user)],
	db_session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
	"""Rename a passkey."""
	result = await db_session.execute(
		select(UserPasskey).where(UserPasskey.id == passkey_id, UserPasskey.user_id == user.id)
	)
	passkey = result.scalar_one_or_none()
	if not passkey:
		raise HTTPException(status_code=404, detail="Passkey not found.")
	new_name = body.get("name", "").strip()
	if not new_name:
		raise HTTPException(status_code=422, detail="Name must not be empty.")
	passkey.name = new_name
	await db_session.commit()
	return {"id": str(passkey.id), "name": passkey.name}


@router.delete("/passkeys/{passkey_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_passkey(
	passkey_id: uuid.UUID,
	user: Annotated[schema.User, Depends(get_current_user)],
	db_session: AsyncSession = Depends(get_db),
) -> None:
	"""Delete a passkey."""
	result = await db_session.execute(
		sa_delete(UserPasskey).where(
			UserPasskey.id == passkey_id,
			UserPasskey.user_id == user.id,
		).returning(UserPasskey.id)
	)
	await db_session.commit()
	if not result.fetchall():
		raise HTTPException(status_code=404, detail="Passkey not found.")

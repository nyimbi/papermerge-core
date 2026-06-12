# (c) Copyright Datacraft, 2026
"""WebAuthn / FIDO2 passkeys router.

Full WebAuthn registration and authentication requires py_webauthn and
a challenge store (Redis/DB). This router provides the correct API surface
so the frontend doesn't error, returning empty passkey lists and 501 for
write operations until the full implementation is added.
"""
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status

from papermerge.core import schema
from papermerge.core.features.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webauthn", tags=["webauthn"])


@router.get("/passkeys")
async def list_passkeys(
	user: Annotated[schema.User, Depends(get_current_user)],
) -> dict[str, Any]:
	"""List registered passkeys for the current user."""
	return {"passkeys": []}


@router.post("/register/begin")
async def register_begin(
	body: dict[str, Any],
	user: Annotated[schema.User, Depends(get_current_user)],
) -> dict[str, Any]:
	"""Begin passkey registration (WebAuthn ceremony step 1)."""
	raise HTTPException(
		status_code=status.HTTP_501_NOT_IMPLEMENTED,
		detail="Passkey registration requires py_webauthn — not yet configured on this deployment.",
	)


@router.post("/register/complete")
async def register_complete(
	body: dict[str, Any],
	user: Annotated[schema.User, Depends(get_current_user)],
) -> dict[str, Any]:
	"""Complete passkey registration (WebAuthn ceremony step 2)."""
	raise HTTPException(
		status_code=status.HTTP_501_NOT_IMPLEMENTED,
		detail="Passkey registration not yet implemented.",
	)


@router.post("/authenticate/begin")
async def authenticate_begin(
	body: dict[str, Any],
) -> dict[str, Any]:
	"""Begin passkey authentication."""
	raise HTTPException(
		status_code=status.HTTP_501_NOT_IMPLEMENTED,
		detail="Passkey authentication not yet implemented.",
	)


@router.post("/authenticate/complete")
async def authenticate_complete(
	body: dict[str, Any],
) -> dict[str, Any]:
	"""Complete passkey authentication."""
	raise HTTPException(
		status_code=status.HTTP_501_NOT_IMPLEMENTED,
		detail="Passkey authentication not yet implemented.",
	)


@router.patch("/passkeys/{passkey_id}")
async def rename_passkey(
	passkey_id: str,
	body: dict[str, Any],
	user: Annotated[schema.User, Depends(get_current_user)],
) -> dict[str, Any]:
	"""Rename a passkey."""
	raise HTTPException(
		status_code=status.HTTP_404_NOT_FOUND,
		detail="Passkey not found — passkeys are not yet implemented.",
	)


@router.delete("/passkeys/{passkey_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_passkey(
	passkey_id: str,
	user: Annotated[schema.User, Depends(get_current_user)],
) -> None:
	"""Delete a passkey."""
	raise HTTPException(
		status_code=status.HTTP_404_NOT_FOUND,
		detail="Passkey not found — passkeys are not yet implemented.",
	)

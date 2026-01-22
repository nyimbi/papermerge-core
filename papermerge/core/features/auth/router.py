# (c) Copyright Datacraft, 2026
"""
Local authentication router for username/password login.

This provides a simple JWT-based authentication flow for local development
and deployments without external OIDC providers.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import selectinload
from passlib.hash import pbkdf2_sha256
import json
import base64

from papermerge.core.db.engine import get_db
from papermerge.core.features.users.db import api as usr_dbapi
from papermerge.core.features.users.db import orm as user_orm
from papermerge.core.features.roles.db import orm as role_orm
from papermerge.core.features.auth import scopes

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


class Token(BaseModel):
	access_token: str
	token_type: str = "bearer"
	expires_in: int = 3600


class TokenPayload(BaseModel):
	sub: str
	preferred_username: str
	email: str | None = None
	scopes: list[str] = []
	exp: int
	iat: int


def create_jwt_token(user_id: str, username: str, email: str | None, user_scopes: list[str]) -> str:
	"""Create a simple JWT token (unsigned, for local dev)."""
	now = datetime.now(timezone.utc)
	exp = now + timedelta(hours=24)

	payload = {
		"sub": user_id,
		"preferred_username": username,
		"email": email or f"{username}@local",
		"scopes": user_scopes,
		"exp": int(exp.timestamp()),
		"iat": int(now.timestamp()),
	}

	# Create unsigned JWT (header.payload.signature)
	# Use compact JSON (no spaces) for proper JWT format
	header = {"alg": "none", "typ": "JWT"}
	header_b64 = base64.urlsafe_b64encode(json.dumps(header, separators=(',', ':')).encode()).decode().rstrip("=")
	payload_b64 = base64.urlsafe_b64encode(json.dumps(payload, separators=(',', ':')).encode()).decode().rstrip("=")

	return f"{header_b64}.{payload_b64}."


@router.post("/token", response_model=Token)
async def login(
	form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
	db_session: AsyncSession = Depends(get_db),
) -> Token:
	"""
	Authenticate with username and password, return JWT token.

	This is intended for local development and simple deployments.
	For production, use OIDC with OAuth2-Proxy.
	"""
	# Get user ORM object directly to access password
	# Eagerly load user_roles and nested role relationship to avoid lazy loading issues
	stmt = (
		select(user_orm.User)
		.where(user_orm.User.username == form_data.username)
		.options(
			selectinload(user_orm.User.user_roles).selectinload(role_orm.UserRole.role)
		)
	)
	result = await db_session.execute(stmt)
	user = result.scalar_one_or_none()

	if user is None:
		logger.warning(f"Login failed: user '{form_data.username}' not found")
		raise HTTPException(
			status_code=status.HTTP_401_UNAUTHORIZED,
			detail="Incorrect username or password",
			headers={"WWW-Authenticate": "Bearer"},
		)

	# Verify password
	if not pbkdf2_sha256.verify(form_data.password, user.password):
		logger.warning(f"Login failed: incorrect password for '{form_data.username}'")
		raise HTTPException(
			status_code=status.HTTP_401_UNAUTHORIZED,
			detail="Incorrect username or password",
			headers={"WWW-Authenticate": "Bearer"},
		)

	# Build scopes list
	user_scopes = []
	if user.is_superuser:
		user_scopes = list(scopes.SCOPES.keys())
	else:
		# Use active_roles property which filters out deleted roles
		active_roles = user.active_roles
		role_scopes = await usr_dbapi.get_user_scopes_from_roles(
			db_session,
			user_id=user.id,
			roles=[r.name for r in active_roles] if active_roles else [],
		)
		user_scopes = list(role_scopes)

	# Create token
	token = create_jwt_token(
		user_id=str(user.id),
		username=user.username,
		email=user.email,
		user_scopes=user_scopes,
	)

	logger.info(f"Login successful for user '{form_data.username}'")

	return Token(access_token=token, expires_in=86400)


@router.get("/me")
async def get_current_user_info(
	db_session: AsyncSession = Depends(get_db),
):
	"""Get current user info (placeholder - requires auth)."""
	return {"message": "Use Authorization header with Bearer token"}

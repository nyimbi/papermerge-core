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
from jose import jwt

from papermerge.core.config import get_settings
from papermerge.core.db.engine import get_db
from papermerge.core.features.users.db import api as usr_dbapi
from papermerge.core.features.users.db import orm as user_orm
from papermerge.core.features.roles.db import orm as role_orm
from papermerge.core.features.auth import scopes
from papermerge.core.features.auth import oauth2_scheme

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
	"""Create a signed HS256 JWT token."""
	cfg = get_settings()
	now = datetime.now(timezone.utc)
	exp = now + timedelta(hours=cfg.jwt_expire_hours)

	payload = {
		"sub": user_id,
		"preferred_username": username,
		"email": email or f"{username}@local",
		"scopes": user_scopes,
		"exp": int(exp.timestamp()),
		"iat": int(now.timestamp()),
	}

	return jwt.encode(payload, cfg.jwt_secret_key, algorithm=cfg.jwt_algorithm)


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


@router.post("/token/refresh", response_model=Token)
async def refresh_token(
	token: Annotated[str | None, Depends(oauth2_scheme)],
	db_session: AsyncSession = Depends(get_db),
) -> Token:
	"""
	Refresh a JWT token. Accepts the current (non-expired) token and returns
	a new one with a fresh expiry.
	"""
	from papermerge.core.features.auth import extract_token_data
	from papermerge.core import exceptions as exc

	if not token:
		raise HTTPException(
			status_code=status.HTTP_401_UNAUTHORIZED,
			detail="Missing token",
			headers={"WWW-Authenticate": "Bearer"},
		)

	try:
		token_data = extract_token_data(token)
	except HTTPException:
		raise
	except Exception:
		raise HTTPException(
			status_code=status.HTTP_401_UNAUTHORIZED,
			detail="Invalid token",
			headers={"WWW-Authenticate": "Bearer"},
		)

	if token_data is None:
		raise HTTPException(
			status_code=status.HTTP_401_UNAUTHORIZED,
			detail="Invalid token",
			headers={"WWW-Authenticate": "Bearer"},
		)

	new_token = create_jwt_token(
		user_id=token_data.user_id,
		username=token_data.username,
		email=token_data.email,
		user_scopes=token_data.scopes,
	)
	return Token(access_token=new_token, expires_in=86400)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
	token: Annotated[str | None, Depends(oauth2_scheme)],
) -> None:
	"""
	Logout endpoint. For JWT-only flows this is a no-op (tokens are stateless).
	PAT tokens should be revoked via DELETE /api-tokens/{id}.
	"""
	# Stateless JWT — client drops the token. Nothing server-side to invalidate.
	return None


@router.get("/me")
async def get_current_user_info(
	token: Annotated[str | None, Depends(oauth2_scheme)],
	db_session: AsyncSession = Depends(get_db),
):
	"""Get current authenticated user info from token."""
	from papermerge.core.features.auth import extract_token_data

	if not token:
		raise HTTPException(
			status_code=status.HTTP_401_UNAUTHORIZED,
			detail="Not authenticated",
			headers={"WWW-Authenticate": "Bearer"},
		)

	token_data = extract_token_data(token)
	if token_data is None:
		raise HTTPException(
			status_code=status.HTTP_401_UNAUTHORIZED,
			detail="Invalid token",
		)

	return {
		"user_id": token_data.user_id,
		"username": token_data.username,
		"email": token_data.email,
		"scopes": token_data.scopes,
	}

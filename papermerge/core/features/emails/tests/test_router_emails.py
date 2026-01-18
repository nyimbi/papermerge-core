# (c) Copyright Datacraft, 2026
"""
Email router tests.
"""
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.features.emails.models import (
	EmailAccountModel,
	EmailImportModel,
)
from papermerge.core.tests.types import AuthTestClient


async def test_list_email_accounts_empty(
	auth_api_client: AuthTestClient,
	db_session: AsyncSession,
):
	"""Test listing email accounts when none exist."""
	response = await auth_api_client.get("/emails/accounts")

	assert response.status_code == 200, response.json()
	data = response.json()
	assert data["items"] == []
	assert data["total"] == 0


async def test_create_email_account(
	auth_api_client: AuthTestClient,
	db_session: AsyncSession,
):
	"""Test creating an email account."""
	count_before = await db_session.scalar(select(func.count(EmailAccountModel.id)))
	assert count_before == 0

	response = await auth_api_client.post(
		"/emails/accounts",
		json={
			"name": "Work Email",
			"account_type": "imap",
			"email_address": "work@company.com",
			"server_host": "imap.company.com",
			"server_port": 993,
			"username": "work@company.com",
			"password": "secret123",
			"use_ssl": True,
		},
	)

	assert response.status_code == 201, response.json()
	data = response.json()
	assert data["name"] == "Work Email"
	assert data["email_address"] == "work@company.com"
	assert data["is_active"] is True

	count_after = await db_session.scalar(select(func.count(EmailAccountModel.id)))
	assert count_after == 1


async def test_get_email_account(
	auth_api_client: AuthTestClient,
	make_email_account,
):
	"""Test getting a single email account."""
	account = await make_email_account(name="Test Account")

	response = await auth_api_client.get(f"/emails/accounts/{account.id}")

	assert response.status_code == 200, response.json()
	data = response.json()
	assert data["id"] == account.id
	assert data["name"] == "Test Account"


async def test_update_email_account(
	auth_api_client: AuthTestClient,
	make_email_account,
):
	"""Test updating an email account."""
	account = await make_email_account(name="Old Name")

	response = await auth_api_client.patch(
		f"/emails/accounts/{account.id}",
		json={"name": "New Name", "is_active": False},
	)

	assert response.status_code == 200, response.json()
	data = response.json()
	assert data["name"] == "New Name"
	assert data["is_active"] is False


async def test_delete_email_account(
	auth_api_client: AuthTestClient,
	make_email_account,
	db_session: AsyncSession,
):
	"""Test deleting an email account."""
	account = await make_email_account()

	count_before = await db_session.scalar(select(func.count(EmailAccountModel.id)))
	assert count_before == 1

	response = await auth_api_client.delete(f"/emails/accounts/{account.id}")

	assert response.status_code == 204

	count_after = await db_session.scalar(select(func.count(EmailAccountModel.id)))
	assert count_after == 0


async def test_list_email_imports(
	auth_api_client: AuthTestClient,
	make_email_import,
):
	"""Test listing email imports."""
	await make_email_import(subject="First Email")
	await make_email_import(subject="Second Email")

	response = await auth_api_client.get("/emails/imports")

	assert response.status_code == 200, response.json()
	data = response.json()
	assert len(data["items"]) == 2
	assert data["total"] == 2


async def test_list_email_imports_pagination(
	auth_api_client: AuthTestClient,
	make_email_import,
):
	"""Test paginated email imports."""
	for i in range(8):
		await make_email_import(subject=f"Email {i}")

	response = await auth_api_client.get(
		"/emails/imports",
		params={"page": 1, "page_size": 5},
	)

	assert response.status_code == 200, response.json()
	data = response.json()
	assert len(data["items"]) == 5
	assert data["total"] == 8


async def test_get_email_import(
	auth_api_client: AuthTestClient,
	make_email_import,
):
	"""Test getting a single email import."""
	email_import = await make_email_import(subject="Test Subject")

	response = await auth_api_client.get(f"/emails/imports/{email_import.id}")

	assert response.status_code == 200, response.json()
	data = response.json()
	assert data["id"] == email_import.id
	assert data["subject"] == "Test Subject"


async def test_delete_email_import(
	auth_api_client: AuthTestClient,
	make_email_import,
	db_session: AsyncSession,
):
	"""Test deleting an email import."""
	email_import = await make_email_import()

	count_before = await db_session.scalar(select(func.count(EmailImportModel.id)))
	assert count_before == 1

	response = await auth_api_client.delete(f"/emails/imports/{email_import.id}")

	assert response.status_code == 204

	count_after = await db_session.scalar(select(func.count(EmailImportModel.id)))
	assert count_after == 0

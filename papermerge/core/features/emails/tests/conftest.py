# (c) Copyright Datacraft, 2026
"""
Email feature test fixtures.
"""
import pytest
from uuid_extensions import uuid7str
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.features.emails.models import (
	EmailAccountModel,
	EmailImportModel,
	EmailThreadModel,
)


@pytest.fixture
async def make_email_account(db_session: AsyncSession, user):
	"""Factory fixture for creating email accounts."""
	async def _make_email_account(
		name: str = "Test Account",
		account_type: str = "imap",
		email_address: str = "test@example.com",
		**kwargs,
	) -> EmailAccountModel:
		account = EmailAccountModel(
			id=uuid7str(),
			owner_id=user.id,
			name=name,
			account_type=account_type,
			email_address=email_address,
			server_host=kwargs.get("server_host", "imap.example.com"),
			server_port=kwargs.get("server_port", 993),
			username=kwargs.get("username", "test@example.com"),
			password_encrypted=kwargs.get("password_encrypted"),
			use_ssl=kwargs.get("use_ssl", True),
			is_active=kwargs.get("is_active", True),
		)
		db_session.add(account)
		await db_session.commit()
		await db_session.refresh(account)
		return account

	return _make_email_account


@pytest.fixture
async def make_email_thread(db_session: AsyncSession, user):
	"""Factory fixture for creating email threads."""
	async def _make_email_thread(
		subject: str = "Test Thread",
		**kwargs,
	) -> EmailThreadModel:
		thread = EmailThreadModel(
			id=uuid7str(),
			owner_id=user.id,
			thread_id=kwargs.get("thread_id", f"thread-{uuid7str()[:8]}"),
			subject=subject,
			message_count=kwargs.get("message_count", 1),
		)
		db_session.add(thread)
		await db_session.commit()
		await db_session.refresh(thread)
		return thread

	return _make_email_thread


@pytest.fixture
async def make_email_import(db_session: AsyncSession, user, make_email_thread, make_folder):
	"""Factory fixture for creating email imports."""
	async def _make_email_import(
		subject: str = "Test Email",
		**kwargs,
	) -> EmailImportModel:
		thread = kwargs.get("thread") or await make_email_thread(subject=subject)
		folder = kwargs.get("folder") or await make_folder()

		email_import = EmailImportModel(
			id=uuid7str(),
			owner_id=user.id,
			thread_id=thread.id,
			folder_id=folder.id,
			message_id=kwargs.get("message_id", f"<{uuid7str()}@example.com>"),
			subject=subject,
			from_address=kwargs.get("from_address", "sender@example.com"),
			from_name=kwargs.get("from_name", "Test Sender"),
			to_addresses=kwargs.get("to_addresses", ["recipient@example.com"]),
			cc_addresses=kwargs.get("cc_addresses", []),
			bcc_addresses=kwargs.get("bcc_addresses", []),
			body_text=kwargs.get("body_text", "Test email body"),
			body_html=kwargs.get("body_html"),
			received_at=kwargs.get("received_at"),
		)
		db_session.add(email_import)
		await db_session.commit()
		await db_session.refresh(email_import)
		return email_import

	return _make_email_import

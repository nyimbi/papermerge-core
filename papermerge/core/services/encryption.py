# (c) Copyright Datacraft, 2026
"""Document encryption service using envelope encryption."""
import os
import logging
from uuid import UUID
from datetime import datetime, timezone

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend
from sqlalchemy import select
from sqlalchemy.orm import Session

from papermerge.core.features.encryption.db.orm import (
	KeyEncryptionKey,
	DocumentEncryptionKey,
)

logger = logging.getLogger(__name__)


class EncryptionService:
	"""Envelope encryption for documents.

	Uses a three-tier key hierarchy:
	1. Master Key (from environment, never stored in DB)
	2. Key Encryption Key (KEK) - per tenant, encrypted with master key
	3. Data Encryption Key (DEK) - per document, encrypted with KEK
	"""

	def __init__(self, master_key: bytes | None = None):
		if master_key is None:
			master_key_hex = os.environ.get("DARCHIVA_MASTER_KEY")
			if not master_key_hex:
				raise ValueError("DARCHIVA_MASTER_KEY environment variable required")
			self.master_key = bytes.fromhex(master_key_hex)
		else:
			self.master_key = master_key

		assert len(self.master_key) == 32, "Master key must be 32 bytes"

	async def encrypt_document(
		self,
		db: Session,
		document_id: UUID,
		content: bytes,
		tenant_id: UUID,
	) -> bytes:
		"""Encrypt document content with envelope encryption."""
		# Get or create tenant KEK
		kek = await self._get_or_create_tenant_kek(db, tenant_id)

		# Generate document-specific DEK
		dek = os.urandom(32)  # 256-bit key

		# Encrypt content with DEK
		aesgcm = AESGCM(dek)
		nonce = os.urandom(12)
		encrypted_content = aesgcm.encrypt(nonce, content, None)

		# Decrypt KEK first
		decrypted_kek = self._decrypt_kek(kek.encrypted_kek)

		# Encrypt DEK with tenant KEK
		kek_aesgcm = AESGCM(decrypted_kek)
		dek_nonce = os.urandom(12)
		encrypted_dek = dek_nonce + kek_aesgcm.encrypt(
			dek_nonce,
			dek,
			document_id.bytes,
		)

		# Store encrypted DEK
		await self._store_document_key(db, document_id, encrypted_dek, kek.id)

		# Return nonce + encrypted content
		return nonce + encrypted_content

	async def decrypt_document(
		self,
		db: Session,
		document_id: UUID,
		encrypted_content: bytes,
	) -> bytes:
		"""Decrypt document content."""
		# Get document key record
		key_record = await self._get_document_key(db, document_id)
		if not key_record:
			raise ValueError(f"No encryption key found for document {document_id}")

		# Get KEK
		kek = await self._get_kek_by_id(db, key_record.kek_id)
		if not kek:
			raise ValueError(f"KEK not found: {key_record.kek_id}")

		# Decrypt KEK
		decrypted_kek = self._decrypt_kek(kek.encrypted_kek)

		# Decrypt DEK
		dek_nonce = key_record.encrypted_key[:12]
		dek_ciphertext = key_record.encrypted_key[12:]
		kek_aesgcm = AESGCM(decrypted_kek)
		dek = kek_aesgcm.decrypt(dek_nonce, dek_ciphertext, document_id.bytes)

		# Decrypt content
		nonce = encrypted_content[:12]
		ciphertext = encrypted_content[12:]
		aesgcm = AESGCM(dek)

		return aesgcm.decrypt(nonce, ciphertext, None)

	async def rotate_document_key(
		self,
		db: Session,
		document_id: UUID,
		content: bytes,
	) -> bytes:
		"""Rotate document encryption key."""
		# Get current key record
		key_record = await self._get_document_key(db, document_id)
		if not key_record:
			raise ValueError(f"No encryption key found for document {document_id}")

		kek = await self._get_kek_by_id(db, key_record.kek_id)

		# Generate new DEK
		new_dek = os.urandom(32)

		# Encrypt content with new DEK
		aesgcm = AESGCM(new_dek)
		nonce = os.urandom(12)
		encrypted_content = aesgcm.encrypt(nonce, content, None)

		# Encrypt new DEK with KEK
		decrypted_kek = self._decrypt_kek(kek.encrypted_kek)
		kek_aesgcm = AESGCM(decrypted_kek)
		dek_nonce = os.urandom(12)
		encrypted_dek = dek_nonce + kek_aesgcm.encrypt(
			dek_nonce,
			new_dek,
			document_id.bytes,
		)

		# Update key record
		key_record.encrypted_key = encrypted_dek
		key_record.key_version += 1
		key_record.rotated_at = datetime.now(timezone.utc)
		db.commit()

		return nonce + encrypted_content

	async def rotate_tenant_kek(
		self,
		db: Session,
		tenant_id: UUID,
	) -> KeyEncryptionKey:
		"""Rotate tenant KEK - requires re-encrypting all document DEKs."""
		# Deactivate old KEK
		old_kek = await self._get_active_kek(db, tenant_id)
		if old_kek:
			old_kek.is_active = False
			old_kek.rotated_at = datetime.now(timezone.utc)

		# Create new KEK
		new_kek_raw = os.urandom(32)
		encrypted_kek = self._encrypt_kek(new_kek_raw)

		new_kek = KeyEncryptionKey(
			tenant_id=tenant_id,
			key_version=(old_kek.key_version + 1) if old_kek else 1,
			encrypted_kek=encrypted_kek,
			is_active=True,
		)
		db.add(new_kek)
		db.commit()

		logger.info(f"Rotated KEK for tenant {tenant_id}, new version: {new_kek.key_version}")
		return new_kek

	def _encrypt_kek(self, kek: bytes) -> bytes:
		"""Encrypt KEK with master key."""
		aesgcm = AESGCM(self.master_key)
		nonce = os.urandom(12)
		return nonce + aesgcm.encrypt(nonce, kek, None)

	def _decrypt_kek(self, encrypted_kek: bytes) -> bytes:
		"""Decrypt KEK with master key."""
		nonce = encrypted_kek[:12]
		ciphertext = encrypted_kek[12:]
		aesgcm = AESGCM(self.master_key)
		return aesgcm.decrypt(nonce, ciphertext, None)

	async def _get_or_create_tenant_kek(
		self,
		db: Session,
		tenant_id: UUID,
	) -> KeyEncryptionKey:
		"""Get active KEK or create new one."""
		kek = await self._get_active_kek(db, tenant_id)
		if kek:
			return kek

		# Create new KEK
		kek_raw = os.urandom(32)
		encrypted_kek = self._encrypt_kek(kek_raw)

		kek = KeyEncryptionKey(
			tenant_id=tenant_id,
			key_version=1,
			encrypted_kek=encrypted_kek,
			is_active=True,
		)
		db.add(kek)
		db.commit()
		db.refresh(kek)
		return kek

	async def _get_active_kek(
		self,
		db: Session,
		tenant_id: UUID,
	) -> KeyEncryptionKey | None:
		"""Get active KEK for tenant."""
		stmt = select(KeyEncryptionKey).where(
			KeyEncryptionKey.tenant_id == tenant_id,
			KeyEncryptionKey.is_active == True,
		)
		return db.scalar(stmt)

	async def _get_kek_by_id(
		self,
		db: Session,
		kek_id: UUID,
	) -> KeyEncryptionKey | None:
		"""Get KEK by ID."""
		return db.get(KeyEncryptionKey, kek_id)

	async def _store_document_key(
		self,
		db: Session,
		document_id: UUID,
		encrypted_dek: bytes,
		kek_id: UUID,
	) -> DocumentEncryptionKey:
		"""Store document encryption key."""
		dek_record = DocumentEncryptionKey(
			document_id=document_id,
			encrypted_key=encrypted_dek,
			kek_id=kek_id,
		)
		db.add(dek_record)
		db.commit()
		db.refresh(dek_record)
		return dek_record

	async def _get_document_key(
		self,
		db: Session,
		document_id: UUID,
	) -> DocumentEncryptionKey | None:
		"""Get document encryption key."""
		stmt = select(DocumentEncryptionKey).where(
			DocumentEncryptionKey.document_id == document_id
		).order_by(DocumentEncryptionKey.key_version.desc())
		return db.scalar(stmt)

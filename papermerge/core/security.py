# (c) Copyright Datacraft, 2026
"""
Security utilities for secret encryption/decryption.

Uses Fernet symmetric encryption for storing sensitive data
like passwords, API keys, and tokens in the database.
"""
import base64
import logging
import os
from functools import lru_cache

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)


def _log_encrypt() -> str:
	return "Encrypting secret..."


def _log_decrypt() -> str:
	return "Decrypting secret..."


@lru_cache(maxsize=1)
def _get_encryption_key() -> bytes:
	"""
	Get or derive the encryption key from environment.

	Uses SECRET_KEY env var with PBKDF2 to derive a Fernet-compatible key.
	"""
	secret_key = os.environ.get("SECRET_KEY", "")
	if not secret_key:
		raise ValueError("SECRET_KEY environment variable must be set for encryption")

	# Use a fixed salt (stored with the app, not in env for simplicity)
	# In production, this could be a separate env var
	salt = os.environ.get("ENCRYPTION_SALT", "darchiva-encryption-salt-2026").encode()

	kdf = PBKDF2HMAC(
		algorithm=hashes.SHA256(),
		length=32,
		salt=salt,
		iterations=480000,
	)

	key = base64.urlsafe_b64encode(kdf.derive(secret_key.encode()))
	return key


def get_fernet() -> Fernet:
	"""Get Fernet instance for encryption/decryption."""
	return Fernet(_get_encryption_key())


def encrypt_secret(plaintext: str | None) -> str | None:
	"""
	Encrypt a secret string for database storage.

	Args:
		plaintext: The secret to encrypt

	Returns:
		Base64-encoded encrypted string, or None if input is None
	"""
	if plaintext is None:
		return None

	logger.debug(_log_encrypt())

	fernet = get_fernet()
	encrypted = fernet.encrypt(plaintext.encode())
	return encrypted.decode()


def decrypt_secret(ciphertext: str | None) -> str | None:
	"""
	Decrypt a secret string from database.

	Args:
		ciphertext: The encrypted secret

	Returns:
		Decrypted plaintext string, or None if input is None
	"""
	if ciphertext is None:
		return None

	logger.debug(_log_decrypt())

	fernet = get_fernet()
	decrypted = fernet.decrypt(ciphertext.encode())
	return decrypted.decode()


def rotate_encryption_key(
	old_key: str,
	new_key: str,
	ciphertext: str,
) -> str:
	"""
	Re-encrypt data with a new key.

	Useful for key rotation without exposing plaintext.

	Args:
		old_key: The current encryption key
		new_key: The new encryption key
		ciphertext: Data encrypted with old key

	Returns:
		Data encrypted with new key
	"""
	# Decrypt with old key
	old_fernet = Fernet(old_key.encode())
	plaintext = old_fernet.decrypt(ciphertext.encode())

	# Encrypt with new key
	new_fernet = Fernet(new_key.encode())
	new_ciphertext = new_fernet.encrypt(plaintext)

	return new_ciphertext.decode()


def generate_encryption_key() -> str:
	"""Generate a new Fernet encryption key."""
	return Fernet.generate_key().decode()


def hash_password(password: str, salt: bytes | None = None) -> tuple[bytes, bytes]:
	"""
	Hash a password using PBKDF2.

	Args:
		password: The password to hash
		salt: Optional salt (generated if not provided)

	Returns:
		Tuple of (hash, salt)
	"""
	if salt is None:
		salt = os.urandom(16)

	kdf = PBKDF2HMAC(
		algorithm=hashes.SHA256(),
		length=32,
		salt=salt,
		iterations=480000,
	)

	password_hash = kdf.derive(password.encode())
	return password_hash, salt


def verify_password(password: str, password_hash: bytes, salt: bytes) -> bool:
	"""
	Verify a password against its hash.

	Args:
		password: The password to verify
		password_hash: The stored hash
		salt: The salt used for hashing

	Returns:
		True if password matches
	"""
	kdf = PBKDF2HMAC(
		algorithm=hashes.SHA256(),
		length=32,
		salt=salt,
		iterations=480000,
	)

	try:
		kdf.verify(password.encode(), password_hash)
		return True
	except Exception:
		return False

"""
API key hashing helpers.

API keys are hashed with HMAC-SHA256 using a server-side pepper
(``jwt_secret_key``) before being stored, so that a leaked database does not
directly reveal usable plaintext keys and offline dictionary attacks are
infeasible.
"""
import hashlib
import hmac

from papermerge.core.config import get_settings


def hash_key(plaintext: str) -> str:
    """Return the HMAC-SHA256 hex digest of an API key."""
    pepper = get_settings().jwt_secret_key.encode()
    return hmac.new(pepper, plaintext.encode(), hashlib.sha256).hexdigest()

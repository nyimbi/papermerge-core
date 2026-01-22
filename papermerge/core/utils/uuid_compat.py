# Compatibility layer for uuid7
from uuid import UUID, uuid4

try:
    from uuid_extension import uuid7 as _uuid7
except ImportError:
    try:
        from uuid_extensions import uuid7 as _uuid7
    except ImportError:
        # Fallback to uuid4 if uuid7 is not available
        _uuid7 = uuid4


def uuid7() -> UUID:
    """Generate a UUID7."""
    return _uuid7()


def uuid7str() -> str:
    """Generate a UUID7 string."""
    return str(_uuid7())

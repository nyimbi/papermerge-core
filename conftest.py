import os

# Ensure required settings are present before any test module imports the app
# (which instantiates Settings at import time). Overridden by explicit env vars
# in CI or local shells.
os.environ.setdefault("PM_DB_URL", "postgresql+asyncpg://x:x@localhost/x")
os.environ.setdefault("PM_JWT_SECRET_KEY", "test-jwt-secret-key")
os.environ.setdefault("PM_CSRF_SECRET_KEY", "test-csrf-secret-key")

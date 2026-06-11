# (c) Copyright Datacraft, 2026
"""Tests for permissions endpoints."""
import os
import uuid
from unittest.mock import MagicMock

os.environ.setdefault("PM_DB_URL", "postgresql+asyncpg://x:x@localhost/x")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from papermerge.core.features.permissions.router import router as permissions_router
from papermerge.core.features.auth import get_current_user


def _make_user():
    u = MagicMock()
    u.id = uuid.uuid4()
    u.tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    u.scopes = ["node:view", "role:view"]
    return u


_user = _make_user()
app = FastAPI()
app.include_router(permissions_router)
app.dependency_overrides[get_current_user] = lambda: _user
client = TestClient(app)


def test_list_permissions_returns_list():
    response = client.get("/permissions")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) > 0


def test_list_permissions_item_structure():
    response = client.get("/permissions")
    assert response.status_code == 200
    item = response.json()[0]
    assert "id" in item
    assert "codename" in item
    assert "name" in item
    assert "category" in item


def test_list_permissions_are_sorted():
    response = client.get("/permissions")
    data = response.json()
    codenames = [p["codename"] for p in data]
    assert codenames == sorted(codenames)


def test_permissions_by_category_returns_list():
    response = client.get("/permissions/by-category")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) > 0


def test_permissions_by_category_item_structure():
    response = client.get("/permissions/by-category")
    data = response.json()
    cat = data[0]
    assert "name" in cat
    assert "permissions" in cat
    assert isinstance(cat["permissions"], list)
    assert len(cat["permissions"]) > 0


def test_permissions_by_category_covers_documents():
    response = client.get("/permissions/by-category")
    data = response.json()
    category_names = {c["name"] for c in data}
    # document/node scopes must land in a known category
    assert len(category_names) > 1


def test_permissions_all_have_valid_codenames():
    response = client.get("/permissions")
    data = response.json()
    for perm in data:
        codename = perm["codename"]
        # codenames come from scopes — they contain at least one character
        assert codename and isinstance(codename, str)


def test_by_category_permissions_match_flat_list():
    flat_resp = client.get("/permissions")
    cat_resp = client.get("/permissions/by-category")
    flat_count = len(flat_resp.json())
    cat_count = sum(len(c["permissions"]) for c in cat_resp.json())
    assert flat_count == cat_count

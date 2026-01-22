# (c) Copyright Datacraft, 2026
"""Tests for Departmental Sovereignty and RBAC."""
import pytest
import uuid
from unittest.mock import MagicMock, AsyncMock

from papermerge.core.features.policies.service import PolicyService
from papermerge.core.features.policies.engine import PolicyDecision, PolicyEffect

@pytest.mark.asyncio
async def test_department_sovereignty_denied():
    """Test that access is denied to a different department hierarchy."""
    session = AsyncMock()
    service = PolicyService(session)
    
    # Mock can_access_department to return False
    service.can_access_department = AsyncMock(return_value=False)
    
    decision = await service.check_access(
        user_id=str(uuid.uuid4()),
        resource_id="doc-1",
        resource_type="document",
        action="view",
        user_department="Finance",
        resource_department="HR"
    )
    
    assert decision.allowed is False
    assert "Departmental Sovereignty" in decision.reason

@pytest.mark.asyncio
async def test_department_sovereignty_allowed_same_dept():
    """Test that access is allowed within the same department."""
    session = AsyncMock()
    service = PolicyService(session)
    
    # Mock can_access_department to return True
    service.can_access_department = AsyncMock(return_value=True)
    # Mock engine.evaluate to return ALLOW
    service._engine = MagicMock()
    service._engine.evaluate.return_value = PolicyDecision(allowed=True, effect=PolicyEffect.ALLOW)
    service._policies_loaded = True
    
    # Mock dept_api.get_effective_permissions
    from papermerge.core.features.departments.db import api as dept_api
    dept_api.get_effective_permissions = AsyncMock(return_value={"permission_level": "view"})

    decision = await service.check_access(
        user_id=str(uuid.uuid4()),
        resource_id="doc-1",
        resource_type="document",
        action="view",
        user_department="Finance",
        resource_department="Finance"
    )
    
    assert decision.allowed is True

@pytest.mark.asyncio
async def test_department_permission_level():
    """Test that department-level permission levels are respected."""
    session = AsyncMock()
    service = PolicyService(session)
    
    # Mock can_access_department to return True
    service.can_access_department = AsyncMock(return_value=True)
    
    # Mock engine.evaluate to return DENY (no policy matches)
    # But then the engine should check department_permissions
    from papermerge.core.features.policies.engine import PolicyEngine, PolicyContext
    engine = PolicyEngine([])
    service._engine = engine
    service._policies_loaded = True
    
    # Mock dept_api.get_effective_permissions to return 'edit' level
    from papermerge.core.features.departments.db import api as dept_api
    dept_api.get_effective_permissions = AsyncMock(return_value={"permission_level": "edit"})

    # Check 'view' action (should be allowed by 'edit' level)
    decision = await service.check_access(
        user_id=str(uuid.uuid4()),
        resource_id="doc-1",
        resource_type="document",
        action="view",
        user_department="Finance",
        resource_department="Finance"
    )
    assert decision.allowed is True
    assert "Allowed by department permission level" in decision.reason

    # Check 'delete' action (should be denied by 'edit' level)
    decision = await service.check_access(
        user_id=str(uuid.uuid4()),
        resource_id="doc-1",
        resource_type="document",
        action="delete",
        user_department="Finance",
        resource_department="Finance"
    )
    assert decision.allowed is False

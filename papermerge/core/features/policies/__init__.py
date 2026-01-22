# (c) Copyright Datacraft, 2026
"""
Policy-Based Access Control (PBAC) with ABAC Extensions.

This module provides a comprehensive policy engine supporting:
- Attribute-Based Access Control (ABAC) with dynamic attribute evaluation
- Policy-Based Access Control (PBAC) with human-readable policy DSL
- Department isolation and hierarchical access
- Policy approval workflows
- Real-time policy evaluation with caching
"""
from .engine import (
	PolicyEngine, PolicyDecision, PolicyContext,
	SubjectAttributes, ResourceAttributes, EnvironmentAttributes,
	DepartmentIsolationEngine,
)
from .parser import PolicyParser, PolicySyntaxError
from .models import (
	Policy, PolicyCondition, PolicyRule, PolicyApproval,
	PolicyEffect, PolicyStatus, ConditionOperator, AttributeCategory,
)
from .service import PolicyService, get_policy_service

__all__ = [
	# Engine
	"PolicyEngine",
	"PolicyDecision",
	"PolicyContext",
	"SubjectAttributes",
	"ResourceAttributes",
	"EnvironmentAttributes",
	"DepartmentIsolationEngine",
	# Parser
	"PolicyParser",
	"PolicySyntaxError",
	# Models
	"Policy",
	"PolicyCondition",
	"PolicyRule",
	"PolicyApproval",
	"PolicyEffect",
	"PolicyStatus",
	"ConditionOperator",
	"AttributeCategory",
	# Service
	"PolicyService",
	"get_policy_service",
]

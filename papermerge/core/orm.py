# (c) Copyright Datacraft, 2026
"""Central ORM model exports."""
from .features.users.db.orm import User
from .features.document.db.orm import Document, DocumentVersion, Page
from .features.nodes.db.orm import Folder, Node
from .features.tags.db.orm import Tag, NodeTagsAssociation
from .features.custom_fields.db.orm import CustomField, CustomFieldValue
from .features.groups.db.orm import Group, UserGroup
from .features.roles.db.orm import Role, Permission, roles_permissions_association, UserRole
from .features.document_types.db.orm import DocumentType, DocumentTypeCustomField
from .features.shared_nodes.db.orm import SharedNode
from .features.audit.db.orm import AuditLog
from .features.special_folders.db.orm import SpecialFolder
from .features.ownership.db.orm import Ownership

# New dArchiva models
from .features.tenants.db.orm import Tenant, TenantBranding, TenantSettings
from .features.workflows.db.orm import (
	Workflow, WorkflowStep, WorkflowInstance, WorkflowStepExecution
)
from .features.routing.db.orm import RoutingRule, RoutingLog
from .features.bundles.db.orm import Bundle, BundleDocument, BundleSection
from .features.cases.db.orm import Case, CaseDocument, CaseAccess
from .features.portfolios.db.orm import Portfolio, PortfolioAccess
from .features.form_recognition.db.orm import (
	FormTemplate, FormField, FormExtraction, ExtractedFieldValue, Signature
)
from .features.encryption.db.orm import (
	KeyEncryptionKey, DocumentEncryptionKey, HiddenDocumentAccess
)
from .features.ingestion.db.orm import IngestionSource, IngestionJob
from .features.api_tokens.db.orm import APIToken
from .features.departments.db.orm import Department, UserDepartment, DepartmentAccessRule
from .features.inventory.db.orm import PhysicalManifest
from .features.provenance.db.orm import DocumentProvenance, ProvenanceEvent

__all__ = [
	# Existing models
	'User',
	'Document',
	'DocumentVersion',
	'Page',
	'Folder',
	'Node',
	'Tag',
	'NodeTagsAssociation',
	'CustomField',
	'CustomFieldValue',
	'Group',
	'UserGroup',
	'Role',
	'UserRole',
	'roles_permissions_association',
	'Permission',
	'DocumentType',
	'DocumentTypeCustomField',
	'SharedNode',
	'AuditLog',
	'SpecialFolder',
	'Ownership',
	# Tenants
	'Tenant',
	'TenantBranding',
	'TenantSettings',
	# Workflows
	'Workflow',
	'WorkflowStep',
	'WorkflowInstance',
	'WorkflowStepExecution',
	# Routing
	'RoutingRule',
	'RoutingLog',
	# Bundles
	'Bundle',
	'BundleDocument',
	'BundleSection',
	# Cases
	'Case',
	'CaseDocument',
	'CaseAccess',
	# Portfolios
	'Portfolio',
	'PortfolioAccess',
	# Form Recognition
	'FormTemplate',
	'FormField',
	'FormExtraction',
	'ExtractedFieldValue',
	'Signature',
	# Encryption
	'KeyEncryptionKey',
	'DocumentEncryptionKey',
	'HiddenDocumentAccess',
	# Ingestion
	'IngestionSource',
	'IngestionJob',
	# API Tokens
	'APIToken',
	# Departments
	'Department',
	'UserDepartment',
	'DepartmentAccessRule',
	# Inventory
	'PhysicalManifest',
	# Provenance
	'DocumentProvenance',
	'ProvenanceEvent',
]

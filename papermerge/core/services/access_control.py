# (c) Copyright Datacraft, 2026
"""Hierarchical access control resolver."""
import logging
from uuid import UUID
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import select, and_, or_
from sqlalchemy.orm import Session

from papermerge.core.features.portfolios.db.orm import Portfolio, PortfolioAccess
from papermerge.core.features.cases.db.orm import Case, CaseAccess
from papermerge.core.features.bundles.db.orm import Bundle, BundleDocument

logger = logging.getLogger(__name__)


class ResourceType(str, Enum):
	PORTFOLIO = "portfolio"
	CASE = "case"
	BUNDLE = "bundle"
	DOCUMENT = "document"
	PAGE = "page"


class AccessAction(str, Enum):
	VIEW = "view"
	DOWNLOAD = "download"
	PRINT = "print"
	EDIT = "edit"
	SHARE = "share"
	DELETE = "delete"


class AccessResult:
	"""Result of access check."""

	def __init__(
		self,
		allowed: bool,
		source: str | None = None,
		inherited_from: UUID | None = None,
		reason: str | None = None,
	):
		self.allowed = allowed
		self.source = source  # "direct", "inherited", "owner"
		self.inherited_from = inherited_from
		self.reason = reason


class HierarchicalAccessResolver:
	"""Resolve access permissions through the resource hierarchy.

	Hierarchy: Portfolio → Case → Bundle → Document → Page

	Access is checked from most specific (page) to least specific (portfolio).
	Direct access at any level overrides inherited access.
	"""

	def __init__(self, db: Session):
		self.db = db

	async def check_access(
		self,
		user_id: UUID,
		resource_type: ResourceType,
		resource_id: UUID,
		action: AccessAction,
		user_groups: list[UUID] | None = None,
		user_roles: list[UUID] | None = None,
	) -> AccessResult:
		"""Check if user has access to perform action on resource."""
		# Build subject list (user + groups + roles)
		subjects = [("user", user_id)]
		if user_groups:
			subjects.extend([("group", g) for g in user_groups])
		if user_roles:
			subjects.extend([("role", r) for r in user_roles])

		# Check direct access first
		direct = await self._check_direct_access(
			resource_type, resource_id, subjects, action
		)
		if direct.allowed or direct.source == "direct":
			return direct

		# Walk up hierarchy for inherited access
		return await self._check_inherited_access(
			resource_type, resource_id, subjects, action
		)

	async def _check_direct_access(
		self,
		resource_type: ResourceType,
		resource_id: UUID,
		subjects: list[tuple[str, UUID]],
		action: AccessAction,
	) -> AccessResult:
		"""Check direct access on the resource."""
		now = datetime.now(timezone.utc)

		if resource_type == ResourceType.PORTFOLIO:
			return await self._check_portfolio_access(resource_id, subjects, action, now)
		elif resource_type == ResourceType.CASE:
			return await self._check_case_access(resource_id, subjects, action, now)
		elif resource_type == ResourceType.BUNDLE:
			# Bundles inherit from their case
			return AccessResult(allowed=False, reason="Check case access")
		elif resource_type == ResourceType.DOCUMENT:
			# Check if document is in a bundle, then check case access
			return AccessResult(allowed=False, reason="Check parent access")
		elif resource_type == ResourceType.PAGE:
			# Pages inherit from document
			return AccessResult(allowed=False, reason="Check document access")

		return AccessResult(allowed=False, reason="Unknown resource type")

	async def _check_portfolio_access(
		self,
		portfolio_id: UUID,
		subjects: list[tuple[str, UUID]],
		action: AccessAction,
		now: datetime,
	) -> AccessResult:
		"""Check access on a portfolio."""
		# Build conditions for any matching subject
		conditions = []
		for subject_type, subject_id in subjects:
			conditions.append(
				and_(
					PortfolioAccess.subject_type == subject_type,
					PortfolioAccess.subject_id == subject_id,
				)
			)

		stmt = select(PortfolioAccess).where(
			and_(
				PortfolioAccess.portfolio_id == portfolio_id,
				or_(*conditions),
				or_(
					PortfolioAccess.valid_from == None,
					PortfolioAccess.valid_from <= now,
				),
				or_(
					PortfolioAccess.valid_until == None,
					PortfolioAccess.valid_until > now,
				),
			)
		)

		for access in self.db.scalars(stmt):
			if self._has_permission(access, action):
				return AccessResult(
					allowed=True,
					source="direct",
					reason=f"Access granted via {access.subject_type}",
				)

		return AccessResult(allowed=False, source="direct", reason="No access grant found")

	async def _check_case_access(
		self,
		case_id: UUID,
		subjects: list[tuple[str, UUID]],
		action: AccessAction,
		now: datetime,
	) -> AccessResult:
		"""Check access on a case."""
		conditions = []
		for subject_type, subject_id in subjects:
			conditions.append(
				and_(
					CaseAccess.subject_type == subject_type,
					CaseAccess.subject_id == subject_id,
				)
			)

		stmt = select(CaseAccess).where(
			and_(
				CaseAccess.case_id == case_id,
				or_(*conditions),
				or_(
					CaseAccess.valid_from == None,
					CaseAccess.valid_from <= now,
				),
				or_(
					CaseAccess.valid_until == None,
					CaseAccess.valid_until > now,
				),
			)
		)

		for access in self.db.scalars(stmt):
			if self._has_permission(access, action):
				return AccessResult(
					allowed=True,
					source="direct",
					reason=f"Access granted via {access.subject_type}",
				)

		return AccessResult(allowed=False, source="direct", reason="No access grant found")

	async def _check_inherited_access(
		self,
		resource_type: ResourceType,
		resource_id: UUID,
		subjects: list[tuple[str, UUID]],
		action: AccessAction,
	) -> AccessResult:
		"""Check inherited access up the hierarchy."""
		now = datetime.now(timezone.utc)

		if resource_type == ResourceType.PAGE:
			# Get document ID from page
			# TODO: Implement page → document lookup
			return AccessResult(allowed=False, reason="Page access not implemented")

		elif resource_type == ResourceType.DOCUMENT:
			# Check if document is in any bundle
			stmt = select(BundleDocument).where(BundleDocument.document_id == resource_id)
			bundle_doc = self.db.scalar(stmt)

			if bundle_doc:
				# Check bundle's case
				bundle = self.db.get(Bundle, bundle_doc.bundle_id)
				if bundle and bundle.case_id:
					case_result = await self._check_case_access(
						bundle.case_id, subjects, action, now
					)
					if case_result.allowed:
						return AccessResult(
							allowed=True,
							source="inherited",
							inherited_from=bundle.case_id,
							reason="Inherited from case",
						)

					# Check case's portfolio
					case = self.db.get(Case, bundle.case_id)
					if case and case.portfolio_id:
						portfolio_result = await self._check_portfolio_access_with_inheritance(
							case.portfolio_id, subjects, action, now
						)
						if portfolio_result.allowed:
							return AccessResult(
								allowed=True,
								source="inherited",
								inherited_from=case.portfolio_id,
								reason="Inherited from portfolio",
							)

			return AccessResult(allowed=False, reason="No inherited access found")

		elif resource_type == ResourceType.BUNDLE:
			bundle = self.db.get(Bundle, resource_id)
			if bundle and bundle.case_id:
				case_result = await self._check_case_access(
					bundle.case_id, subjects, action, now
				)
				if case_result.allowed:
					return AccessResult(
						allowed=True,
						source="inherited",
						inherited_from=bundle.case_id,
						reason="Inherited from case",
					)

				# Check portfolio
				case = self.db.get(Case, bundle.case_id)
				if case and case.portfolio_id:
					portfolio_result = await self._check_portfolio_access_with_inheritance(
						case.portfolio_id, subjects, action, now
					)
					if portfolio_result.allowed:
						return AccessResult(
							allowed=True,
							source="inherited",
							inherited_from=case.portfolio_id,
							reason="Inherited from portfolio",
						)

			return AccessResult(allowed=False, reason="No inherited access found")

		elif resource_type == ResourceType.CASE:
			case = self.db.get(Case, resource_id)
			if case and case.portfolio_id:
				portfolio_result = await self._check_portfolio_access_with_inheritance(
					case.portfolio_id, subjects, action, now
				)
				if portfolio_result.allowed:
					return AccessResult(
						allowed=True,
						source="inherited",
						inherited_from=case.portfolio_id,
						reason="Inherited from portfolio",
					)

			return AccessResult(allowed=False, reason="No inherited access found")

		return AccessResult(allowed=False, reason="No inheritance path")

	async def _check_portfolio_access_with_inheritance(
		self,
		portfolio_id: UUID,
		subjects: list[tuple[str, UUID]],
		action: AccessAction,
		now: datetime,
	) -> AccessResult:
		"""Check portfolio access with inherit_to_cases flag."""
		conditions = []
		for subject_type, subject_id in subjects:
			conditions.append(
				and_(
					PortfolioAccess.subject_type == subject_type,
					PortfolioAccess.subject_id == subject_id,
				)
			)

		stmt = select(PortfolioAccess).where(
			and_(
				PortfolioAccess.portfolio_id == portfolio_id,
				PortfolioAccess.inherit_to_cases == True,
				or_(*conditions),
				or_(
					PortfolioAccess.valid_from == None,
					PortfolioAccess.valid_from <= now,
				),
				or_(
					PortfolioAccess.valid_until == None,
					PortfolioAccess.valid_until > now,
				),
			)
		)

		for access in self.db.scalars(stmt):
			if self._has_permission(access, action):
				return AccessResult(allowed=True)

		return AccessResult(allowed=False)

	def _has_permission(self, access, action: AccessAction) -> bool:
		"""Check if access grant includes the requested action."""
		if action == AccessAction.VIEW:
			return access.allow_view
		elif action == AccessAction.DOWNLOAD:
			return access.allow_download
		elif action == AccessAction.PRINT:
			return access.allow_print
		elif action == AccessAction.EDIT:
			return access.allow_edit
		elif action == AccessAction.SHARE:
			return access.allow_share
		elif action == AccessAction.DELETE:
			return access.allow_edit  # Delete requires edit permission
		return False

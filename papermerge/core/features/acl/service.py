"""ACL service — permission resolution for documents and folders."""
import logging
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.features.acl.db.orm import DocumentACL

_log = logging.getLogger(__name__)


_OWNER_PERMISSIONS = {
	"can_read": True,
	"can_write": True,
	"can_delete": True,
	"can_share": True,
}

_DEFAULT_PERMISSIONS = {
	"can_read": True,
	"can_write": False,
	"can_delete": False,
	"can_share": False,
}

_NO_PERMISSIONS = {
	"can_read": False,
	"can_write": False,
	"can_delete": False,
	"can_share": False,
}


def _log_permission_check(
	user_id: str, resource_id: str, result: dict
) -> None:
	_log.debug(
		"acl.check user=%s resource=%s result=%s", user_id, resource_id, result
	)


async def is_owner(
	user_id: str,
	resource_id: str,
	session: AsyncSession,
) -> bool:
	"""
	Check whether *user_id* is the creator/owner of *resource_id*.

	We look for a granted_by_id entry where the resource has an ACL row
	granted by the user themselves (i.e. the user who created the resource
	is the one who bootstrapped its first ACL).  If no ACL rows exist at all
	for the resource the caller should fall back to the ownership table.
	"""
	# Owner is the user who granted their own access (self-grant = owner)
	row = (
		await session.execute(
			select(DocumentACL).where(
				DocumentACL.resource_id == resource_id,
				DocumentACL.principal_type == "user",
				DocumentACL.principal_id == user_id,
				DocumentACL.granted_by_id == user_id,
			)
		)
	).scalar_one_or_none()
	return row is not None


async def get_user_permissions(
	user_id: str,
	resource_id: str,
	resource_type: str,
	group_ids: list[str] | None,
	session: AsyncSession,
) -> dict[str, bool]:
	"""
	Resolve effective permissions for *user_id* on *resource_id*.

	Resolution order:
	  1. Direct user ACL entry (if found and not expired → use it)
	  2. Group ACL entries    (union/OR across all groups the user belongs to)
	  3. Fallback             (owner → all perms; otherwise → can_read only)

	*group_ids* is a list of group IDs the user belongs to, obtained from
	the caller (e.g. from the JWT claims or a groups lookup).  Pass [] or
	None to skip group resolution.
	"""
	now = datetime.utcnow()

	# 1. Direct user ACL
	direct = (
		await session.execute(
			select(DocumentACL).where(
				DocumentACL.resource_id == resource_id,
				DocumentACL.resource_type == resource_type,
				DocumentACL.principal_type == "user",
				DocumentACL.principal_id == user_id,
				or_(
					DocumentACL.expires_at.is_(None),
					DocumentACL.expires_at > now,
				),
			)
		)
	).scalar_one_or_none()

	if direct is not None:
		result = {
			"can_read": direct.can_read,
			"can_write": direct.can_write,
			"can_delete": direct.can_delete,
			"can_share": direct.can_share,
		}
		_log_permission_check(user_id, resource_id, result)
		return result

	# 2. Group ACL entries — union (OR) across all groups
	if group_ids:
		group_rows = (
			await session.execute(
				select(DocumentACL).where(
					DocumentACL.resource_id == resource_id,
					DocumentACL.resource_type == resource_type,
					DocumentACL.principal_type == "group",
					DocumentACL.principal_id.in_(group_ids),
					or_(
						DocumentACL.expires_at.is_(None),
						DocumentACL.expires_at > now,
					),
				)
			)
		).scalars().all()

		if group_rows:
			result = {
				"can_read": any(r.can_read for r in group_rows),
				"can_write": any(r.can_write for r in group_rows),
				"can_delete": any(r.can_delete for r in group_rows),
				"can_share": any(r.can_share for r in group_rows),
			}
			_log_permission_check(user_id, resource_id, result)
			return result

	# 3. Fallback — check if any ACL rows exist at all for this resource
	any_acl = (
		await session.execute(
			select(DocumentACL.id).where(
				DocumentACL.resource_id == resource_id,
				DocumentACL.resource_type == resource_type,
			).limit(1)
		)
	).scalar_one_or_none()

	if any_acl is None:
		# No ACL configured yet — resource is effectively private (owner-only)
		# The caller should determine ownership; we return owner perms as
		# the safest default when no ACL exists.
		_log.debug("acl.no_acl resource=%s returning owner defaults", resource_id)
		return dict(_OWNER_PERMISSIONS)

	# ACL exists but this user has no entry → read-only
	_log_permission_check(user_id, resource_id, _DEFAULT_PERMISSIONS)
	return dict(_DEFAULT_PERMISSIONS)

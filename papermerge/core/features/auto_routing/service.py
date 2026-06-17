# (c) Copyright Datacraft, 2026
"""Auto-routing service — applies rules after document classification."""
import logging
import uuid
from uuid import UUID

from sqlalchemy import select, and_, update
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.features.auto_routing.db.orm import AutoRoutingRule

_log = logging.getLogger(__name__)


async def apply_auto_routing(
	document_id: str,
	document_type: str,
	confidence: float,
	tenant_id: str,
	session: AsyncSession,
) -> bool:
	"""
	Find the highest-priority active rule for *document_type* that the
	supplied *confidence* satisfies, then move the document into the rule's
	destination folder.

	Returns True if a rule was applied, False otherwise.
	Failures are caught and logged so that classification is never blocked.
	"""
	try:
		doc_uuid = UUID(str(document_id))
		tenant_uuid = UUID(str(tenant_id))
	except (ValueError, AttributeError) as exc:
		_log.warning("auto_routing: invalid id — %s", exc)
		return False

	try:
		# Fetch active rules for this tenant + document_type, best priority first
		stmt = (
			select(AutoRoutingRule)
			.where(
				and_(
					AutoRoutingRule.tenant_id == tenant_uuid,
					AutoRoutingRule.document_type == document_type,
					AutoRoutingRule.is_active.is_(True),
				)
			)
			.order_by(AutoRoutingRule.priority.desc())
		)
		result = await session.execute(stmt)
		rules: list[AutoRoutingRule] = list(result.scalars().all())

		matched: AutoRoutingRule | None = None
		for rule in rules:
			if confidence >= rule.confidence_threshold:
				matched = rule
				break

		if matched is None:
			_log.debug(
				"auto_routing: no matching rule for doc=%s type=%s confidence=%.3f",
				document_id, document_type, confidence,
			)
			return False

		_log.info(
			"auto_routing: applying rule %r (id=%s) to doc=%s → folder=%s",
			matched.name, matched.id, document_id, matched.destination_folder_id,
		)

		# Move document: update parent_id on the nodes row
		from papermerge.core.features.nodes.db.orm import Node  # local import avoids circular
		await session.execute(
			update(Node)
			.where(Node.id == doc_uuid)
			.values(parent_id=matched.destination_folder_id)
		)

		# Increment applied_count
		await session.execute(
			update(AutoRoutingRule)
			.where(AutoRoutingRule.id == matched.id)
			.values(applied_count=AutoRoutingRule.applied_count + 1)
		)

		# Append to audit_log
		try:
			from papermerge.core.features.audit.db.orm import AuditLog  # optional dep
			audit_entry = AuditLog(
				id=uuid.uuid4(),
				table_name="documents",
				record_id=doc_uuid,
				operation="auto_routing_applied",
				user_id=matched.created_by_id,
				new_values={
					"rule_id": str(matched.id),
					"rule_name": matched.name,
					"document_type": document_type,
					"confidence": confidence,
					"destination_folder_id": str(matched.destination_folder_id),
				},
			)
			session.add(audit_entry)
		except Exception as audit_exc:
			_log.warning("auto_routing: could not write audit entry — %s", audit_exc)

		await session.commit()
		return True

	except Exception as exc:
		_log.exception("auto_routing: unexpected error for doc=%s — %s", document_id, exc)
		await session.rollback()
		return False

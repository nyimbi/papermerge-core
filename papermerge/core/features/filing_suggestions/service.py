"""Smart filing suggestions service.

Given a document, returns the most likely destination folder and tags
based on what other documents with the same document_type ended up in.
The confidence score is simply the fraction of peers that share the
top choice:  count_top / total_peers.
"""
import logging
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def get_filing_suggestions(
	document_id: UUID,
	user_id: UUID,
	session: AsyncSession,
) -> dict:
	"""
	Returns smart suggestions for folder and tags.

	Algorithm:
	  1. Fetch the document's document_type_id (if classified).
	  2. If classified, query the N most common parent_id values among
	     documents of the same type owned by the same user.
	  3. Query the N most common tags applied to those peer documents.
	  4. Build confidence as count / total_peers.

	Returns:
	  {
	    suggested_folders: [{folder_id, folder_path, confidence, document_count}],
	    suggested_tags:    [{tag_id, tag_name, tag_color, confidence, document_count}],
	    suggested_document_type: str | None,
	    based_on_type: str | None,
	    peer_count: int,
	  }
	"""
	# ------------------------------------------------------------------
	# 1. Resolve the document's document_type
	# ------------------------------------------------------------------
	type_sql = text("""
		SELECT
			d.document_type_id,
			dt.name AS document_type_name
		FROM documents d
		JOIN nodes n ON n.id = d.node_id
		LEFT JOIN document_types dt ON dt.id = d.document_type_id
		WHERE d.node_id = :doc_id
	""")
	type_row = (await session.execute(type_sql, {"doc_id": document_id})).fetchone()

	if type_row is None:
		logger.debug("filing_suggestions: document %s not found", document_id)
		return _empty_result()

	document_type_id: UUID | None = type_row.document_type_id
	document_type_name: str | None = type_row.document_type_name

	if document_type_id is None:
		# Not yet classified — no basis for suggestions
		return _empty_result()

	# ------------------------------------------------------------------
	# 2. Suggested folders — top-3 parent folders among same-type peers
	#    owned by the same user, excluding the document itself.
	# ------------------------------------------------------------------
	# peer_count: total same-type docs (excluding this one) with a parent
	peer_count_sql = text("""
		SELECT COUNT(*) AS cnt
		FROM documents d
		JOIN nodes n ON n.id = d.node_id
		WHERE d.document_type_id = :dt_id
		  AND n.user_id = :user_id
		  AND n.parent_id IS NOT NULL
		  AND d.node_id != :doc_id
	""")
	peer_count_row = (
		await session.execute(
			peer_count_sql,
			{"dt_id": document_type_id, "user_id": user_id, "doc_id": document_id},
		)
	).fetchone()
	peer_count = int(peer_count_row.cnt) if peer_count_row else 0

	suggested_folders = []
	if peer_count > 0:
		folder_sql = text("""
			SELECT
				n.parent_id                       AS folder_id,
				fn.title                          AS folder_title,
				COUNT(*)                          AS doc_count
			FROM documents d
			JOIN nodes n  ON n.id  = d.node_id
			JOIN nodes fn ON fn.id = n.parent_id
			WHERE d.document_type_id = :dt_id
			  AND n.user_id          = :user_id
			  AND n.parent_id IS NOT NULL
			  AND d.node_id          != :doc_id
			GROUP BY n.parent_id, fn.title
			ORDER BY doc_count DESC
			LIMIT 3
		""")
		folder_rows = (
			await session.execute(
				folder_sql,
				{"dt_id": document_type_id, "user_id": user_id, "doc_id": document_id},
			)
		).fetchall()

		for row in folder_rows:
			confidence = round(int(row.doc_count) / peer_count, 3)
			suggested_folders.append({
				"folder_id": str(row.folder_id),
				"folder_path": row.folder_title,
				"confidence": confidence,
				"document_count": int(row.doc_count),
			})

	# ------------------------------------------------------------------
	# 3. Suggested tags — top-5 tags among same-type peers
	# ------------------------------------------------------------------
	suggested_tags = []
	if peer_count > 0:
		tag_sql = text("""
			SELECT
				t.id        AS tag_id,
				t.name      AS tag_name,
				t.bg_color  AS tag_color,
				COUNT(*)    AS doc_count
			FROM documents d
			JOIN nodes n        ON n.id  = d.node_id
			JOIN nodes_tags nt  ON nt.node_id = n.id
			JOIN tags t         ON t.id  = nt.tag_id
			WHERE d.document_type_id = :dt_id
			  AND n.user_id          = :user_id
			  AND d.node_id          != :doc_id
			GROUP BY t.id, t.name, t.bg_color
			ORDER BY doc_count DESC
			LIMIT 5
		""")
		tag_rows = (
			await session.execute(
				tag_sql,
				{"dt_id": document_type_id, "user_id": user_id, "doc_id": document_id},
			)
		).fetchall()

		for row in tag_rows:
			confidence = round(int(row.doc_count) / peer_count, 3)
			suggested_tags.append({
				"tag_id": str(row.tag_id),
				"tag_name": row.tag_name,
				"tag_color": row.tag_color or "#c41fff",
				"confidence": confidence,
				"document_count": int(row.doc_count),
			})

	return {
		"suggested_folders": suggested_folders,
		"suggested_tags": suggested_tags,
		"suggested_document_type": document_type_name,
		"based_on_type": document_type_name,
		"peer_count": peer_count,
	}


def _empty_result() -> dict:
	return {
		"suggested_folders": [],
		"suggested_tags": [],
		"suggested_document_type": None,
		"based_on_type": None,
		"peer_count": 0,
	}

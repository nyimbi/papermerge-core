# (c) Copyright Datacraft, 2026
"""Anomaly detection for document metadata."""
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import numpy as np
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass
class AnomalyResult:
	"""Result of anomaly detection for a document."""
	document_id: UUID
	is_anomaly: bool
	score: float  # Anomaly score (lower is more anomalous)
	reasons: list[str]
	metadata: dict[str, Any]


class AnomalyDetectionService:
	"""
	Service for detecting anomalies in document metadata.
	
	Uses IsolationForest for unsupervised outlier detection.
	"""

	def __init__(self, session: AsyncSession):
		self.session = session

	async def detect_anomalies(
		self,
		document_id: UUID,
		tenant_id: UUID | None = None
	) -> AnomalyResult:
		"""
		Detect if a document's metadata is anomalous compared to its peers.
		
		Args:
			document_id: Document to check
			tenant_id: Optional tenant filter for peer group
			
		Returns:
			AnomalyResult with score and reasons
		"""
		# 1. Get document metadata
		# For now, we focus on financial metadata from custom fields or extracted NLP data
		# This is a simplified implementation
		
		# Get document's total_amount and vendor from custom fields or NLP results
		# In a real system, this would query a structured metadata table
		sql = text("""
			SELECT 
				n.id,
				(metadata->>'total_amount')::float as amount,
				metadata->>'vendor_name' as vendor
			FROM nodes n
			WHERE n.id = :doc_id
		""")
		result = await self.session.execute(sql, {"doc_id": document_id})
		row = result.fetchone()
		
		if not row or row.amount is None:
			return AnomalyResult(
				document_id=document_id,
				is_anomaly=False,
				score=0.0,
				reasons=["Insufficient metadata for analysis"],
				metadata={}
			)
		
		doc_amount = row.amount
		doc_vendor = row.vendor
		
		# 2. Get peer group metadata (e.g., other invoices from same vendor or tenant)
		peer_sql = text("""
			SELECT 
				(metadata->>'total_amount')::float as amount
			FROM nodes
			WHERE type = 'document'
			AND metadata->>'total_amount' IS NOT NULL
			{tenant_filter}
			LIMIT 1000
		""")
		
		tenant_filter = "AND tenant_id = :tenant_id" if tenant_id else ""
		peer_result = await self.session.execute(
			peer_sql.format(tenant_filter=tenant_filter),
			{"tenant_id": tenant_id} if tenant_id else {}
		)
		peer_amounts = [r.amount for r in peer_result.fetchall()]
		
		if len(peer_amounts) < 10:
			# Not enough data for statistical analysis
			return AnomalyResult(
				document_id=document_id,
				is_anomaly=False,
				score=0.0,
				reasons=["Insufficient peer data for statistical analysis"],
				metadata={"amount": doc_amount}
			)
		
		# 3. Run IsolationForest
		try:
			from sklearn.ensemble import IsolationForest
			
			X = np.array(peer_amounts).reshape(-1, 1)
			clf = IsolationForest(contamination=0.05, random_state=42)
			clf.fit(X)
			
			# Score the current document
			score = float(clf.decision_function([[doc_amount]])[0])
			is_anomaly = bool(clf.predict([[doc_amount]])[0] == -1)
			
			reasons = []
			if is_anomaly:
				avg = np.mean(peer_amounts)
				std = np.std(peer_amounts)
				if doc_amount > avg + 3 * std:
					reasons.append(f"Amount {doc_amount} is significantly higher than average ({avg:.2f})")
				elif doc_amount < avg - 3 * std:
					reasons.append(f"Amount {doc_amount} is significantly lower than average ({avg:.2f})")
				else:
					reasons.append("Statistical outlier detected in metadata distribution")
					
			return AnomalyResult(
				document_id=document_id,
				is_anomaly=is_anomaly,
				score=score,
				reasons=reasons,
				metadata={"amount": doc_amount, "peer_count": len(peer_amounts)}
			)
			
		except ImportError:
			logger.warning("scikit-learn not available, using simple Z-score fallback")
			avg = np.mean(peer_amounts)
			std = np.std(peer_amounts)
			z_score = (doc_amount - avg) / std if std > 0 else 0
			
			is_anomaly = abs(z_score) > 3
			reasons = []
			if is_anomaly:
				reasons.append(f"Z-score {z_score:.2f} exceeds threshold of 3.0")
				
			return AnomalyResult(
				document_id=document_id,
				is_anomaly=is_anomaly,
				score=-z_score if is_anomaly else 0.0,
				reasons=reasons,
				metadata={"amount": doc_amount, "z_score": z_score}
			)

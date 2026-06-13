"""
Document deduplication pipeline.

Layers (executed in order, stops at first match):
  1. SHA-256 exact hash  → EXACT_DUPLICATE
  2. pHash Hamming ≤ 10  → NEAR_DUPLICATE
  3. No match            → UNIQUE
"""
import hashlib
import logging
from dataclasses import dataclass
from enum import Enum
from io import BytesIO

from PIL import Image
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

try:
	import imagehash
	_IMAGEHASH_AVAILABLE = True
except ImportError:
	_IMAGEHASH_AVAILABLE = False

log = logging.getLogger(__name__)

PHASH_HAMMING_THRESHOLD = 10


class DedupVerdict(str, Enum):
	UNIQUE = "unique"
	EXACT_DUPLICATE = "exact_duplicate"
	NEAR_DUPLICATE = "near_duplicate"


@dataclass
class DedupResult:
	verdict: DedupVerdict
	sha256: str
	phash: str | None
	existing_document_id: str | None = None
	existing_batch_id: str | None = None
	hamming_distance: int | None = None


def compute_sha256(data: bytes) -> str:
	return hashlib.sha256(data).hexdigest()


def compute_phash(data: bytes) -> str | None:
	if not _IMAGEHASH_AVAILABLE:
		return None
	try:
		img = Image.open(BytesIO(data))
		return str(imagehash.phash(img, hash_size=8))
	except Exception:
		return None


def hamming_distance(a: str, b: str) -> int:
	"""Hamming distance between two hex pHash strings."""
	try:
		ai = int(a, 16)
		bi = int(b, 16)
		xor = ai ^ bi
		return bin(xor).count("1")
	except (ValueError, TypeError):
		return 999


async def check_duplicate(
	db: AsyncSession,
	data: bytes,
	tenant_id: str,
) -> DedupResult:
	"""Check if `data` is a duplicate of an already-ingested document."""
	sha = compute_sha256(data)
	ph = compute_phash(data)

	# Layer 1 — exact SHA-256 match
	row = await db.execute(
		text(
			"SELECT document_id, batch_id FROM document_fingerprints "
			"WHERE sha256 = :sha AND tenant_id = :tid LIMIT 1"
		),
		{"sha": sha, "tid": tenant_id},
	)
	match = row.fetchone()
	if match:
		return DedupResult(
			verdict=DedupVerdict.EXACT_DUPLICATE,
			sha256=sha,
			phash=ph,
			existing_document_id=str(match.document_id),
			existing_batch_id=str(match.batch_id) if match.batch_id else None,
		)

	# Layer 2 — perceptual hash (only for image payloads)
	if ph and _IMAGEHASH_AVAILABLE:
		rows = await db.execute(
			text(
				"SELECT document_id, batch_id, phash FROM document_fingerprints "
				"WHERE phash IS NOT NULL AND tenant_id = :tid"
			),
			{"tid": tenant_id},
		)
		for r in rows.fetchall():
			if r.phash:
				dist = hamming_distance(ph, r.phash)
				if dist <= PHASH_HAMMING_THRESHOLD:
					return DedupResult(
						verdict=DedupVerdict.NEAR_DUPLICATE,
						sha256=sha,
						phash=ph,
						existing_document_id=str(r.document_id),
						existing_batch_id=str(r.batch_id) if r.batch_id else None,
						hamming_distance=dist,
					)

	return DedupResult(verdict=DedupVerdict.UNIQUE, sha256=sha, phash=ph)


async def record_fingerprint(
	db: AsyncSession,
	document_id: str,
	tenant_id: str,
	sha256: str,
	phash: str | None,
	batch_id: str | None = None,
) -> None:
	"""Persist a fingerprint after successful ingestion."""
	from papermerge.core.utils.uuid_compat import uuid7str

	await db.execute(
		text(
			"INSERT INTO document_fingerprints "
			"(id, document_id, batch_id, sha256, phash, tenant_id, created_at) "
			"VALUES (:id, :doc, :batch, :sha, :ph, :tid, now()) "
			"ON CONFLICT (sha256, tenant_id) DO NOTHING"
		),
		{
			"id": uuid7str(),
			"doc": document_id,
			"batch": batch_id,
			"sha": sha256,
			"ph": phash,
			"tid": tenant_id,
		},
	)

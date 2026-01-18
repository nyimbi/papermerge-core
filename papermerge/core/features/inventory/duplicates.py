# (c) Copyright Datacraft, 2026
"""
Duplicate document detection using perceptual hashing.
"""
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import imagehash
from PIL import Image

from papermerge.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class DuplicateMatch:
	"""Represents a potential duplicate match."""
	document_id: str
	similarity_score: float  # 0.0 to 1.0
	hash_type: str
	original_hash: str
	match_hash: str


@dataclass
class HashResult:
	"""Result of hashing an image/document."""
	file_hash: str  # SHA-512 of file contents
	phash: str  # Perceptual hash
	dhash: str  # Difference hash
	ahash: str  # Average hash
	whash: str  # Wavelet hash


class DuplicateDetector:
	"""
	Detect duplicate documents using multiple hashing strategies.

	Supports:
	- Exact matching (SHA-512 file hash)
	- Near-duplicate matching (perceptual hashing)
	- Visual similarity scoring
	"""

	def __init__(
		self,
		hash_size: int = 16,
		similarity_threshold: float = 0.90,
	):
		"""
		Initialize detector.

		Args:
			hash_size: Size of perceptual hash (larger = more precise)
			similarity_threshold: Minimum similarity for duplicate detection (0-1)
		"""
		self.hash_size = hash_size
		self.similarity_threshold = similarity_threshold

	def hash_file(self, file_path: Path | str) -> HashResult:
		"""
		Generate all hashes for a file.

		Args:
			file_path: Path to image or PDF file

		Returns:
			HashResult with all hash types
		"""
		file_path = Path(file_path)

		# File content hash
		file_hash = self._compute_file_hash(file_path)

		# Load image
		if file_path.suffix.lower() == '.pdf':
			img = self._pdf_to_image(file_path)
		else:
			img = Image.open(file_path)

		# Compute perceptual hashes
		phash = str(imagehash.phash(img, hash_size=self.hash_size))
		dhash = str(imagehash.dhash(img, hash_size=self.hash_size))
		ahash = str(imagehash.average_hash(img, hash_size=self.hash_size))
		whash = str(imagehash.whash(img, hash_size=self.hash_size))

		return HashResult(
			file_hash=file_hash,
			phash=phash,
			dhash=dhash,
			ahash=ahash,
			whash=whash,
		)

	def hash_image(self, img: Image.Image) -> HashResult:
		"""
		Generate perceptual hashes for an image.

		Args:
			img: PIL Image

		Returns:
			HashResult (file_hash will be empty)
		"""
		phash = str(imagehash.phash(img, hash_size=self.hash_size))
		dhash = str(imagehash.dhash(img, hash_size=self.hash_size))
		ahash = str(imagehash.average_hash(img, hash_size=self.hash_size))
		whash = str(imagehash.whash(img, hash_size=self.hash_size))

		return HashResult(
			file_hash="",
			phash=phash,
			dhash=dhash,
			ahash=ahash,
			whash=whash,
		)

	def compare_hashes(
		self,
		hash1: str,
		hash2: str,
		hash_type: Literal['phash', 'dhash', 'ahash', 'whash'] = 'phash',
	) -> float:
		"""
		Compare two hash strings and return similarity score.

		Args:
			hash1: First hash string
			hash2: Second hash string
			hash_type: Type of perceptual hash

		Returns:
			Similarity score from 0.0 to 1.0
		"""
		h1 = imagehash.hex_to_hash(hash1)
		h2 = imagehash.hex_to_hash(hash2)

		# Hamming distance
		distance = h1 - h2
		max_distance = self.hash_size * self.hash_size

		# Convert to similarity
		similarity = 1.0 - (distance / max_distance)
		return similarity

	def is_duplicate(
		self,
		hash1: HashResult,
		hash2: HashResult,
		method: Literal['exact', 'perceptual', 'combined'] = 'combined',
	) -> tuple[bool, float]:
		"""
		Check if two documents are duplicates.

		Args:
			hash1: Hash of first document
			hash2: Hash of second document
			method: Detection method

		Returns:
			Tuple of (is_duplicate, similarity_score)
		"""
		if method == 'exact':
			if hash1.file_hash and hash2.file_hash:
				is_dup = hash1.file_hash == hash2.file_hash
				return is_dup, 1.0 if is_dup else 0.0
			return False, 0.0

		elif method == 'perceptual':
			# Use phash as primary
			similarity = self.compare_hashes(hash1.phash, hash2.phash, 'phash')
			return similarity >= self.similarity_threshold, similarity

		else:  # combined
			# Check exact first
			if hash1.file_hash and hash2.file_hash:
				if hash1.file_hash == hash2.file_hash:
					return True, 1.0

			# Check perceptual hashes
			phash_sim = self.compare_hashes(hash1.phash, hash2.phash, 'phash')
			dhash_sim = self.compare_hashes(hash1.dhash, hash2.dhash, 'dhash')

			# Average of multiple hash types for robustness
			avg_similarity = (phash_sim + dhash_sim) / 2

			return avg_similarity >= self.similarity_threshold, avg_similarity

	async def find_duplicates(
		self,
		document_hash: HashResult,
		existing_hashes: list[tuple[str, HashResult]],
		method: Literal['exact', 'perceptual', 'combined'] = 'combined',
	) -> list[DuplicateMatch]:
		"""
		Find duplicates of a document in existing collection.

		Args:
			document_hash: Hash of document to check
			existing_hashes: List of (document_id, hash) tuples
			method: Detection method

		Returns:
			List of DuplicateMatch objects sorted by similarity
		"""
		matches = []

		for doc_id, existing in existing_hashes:
			is_dup, similarity = self.is_duplicate(
				document_hash,
				existing,
				method,
			)

			if is_dup:
				matches.append(DuplicateMatch(
					document_id=doc_id,
					similarity_score=similarity,
					hash_type='combined' if method == 'combined' else 'phash',
					original_hash=document_hash.phash,
					match_hash=existing.phash,
				))

		# Sort by similarity descending
		matches.sort(key=lambda m: m.similarity_score, reverse=True)
		return matches

	def _compute_file_hash(self, file_path: Path) -> str:
		"""Compute SHA-512 hash of file contents."""
		sha512 = hashlib.sha512()
		with open(file_path, 'rb') as f:
			for chunk in iter(lambda: f.read(8192), b''):
				sha512.update(chunk)
		return sha512.hexdigest()

	def _pdf_to_image(self, pdf_path: Path, page: int = 0) -> Image.Image:
		"""Convert first page of PDF to image for hashing."""
		try:
			import pdf2image
			images = pdf2image.convert_from_path(
				pdf_path,
				first_page=page + 1,
				last_page=page + 1,
				dpi=72,  # Low res for hashing
			)
			return images[0] if images else Image.new('RGB', (100, 100), 'white')
		except ImportError:
			logger.warning("pdf2image not installed, returning placeholder")
			return Image.new('RGB', (100, 100), 'white')


class BatchDuplicateChecker:
	"""
	Check for duplicates within a batch and across existing documents.
	"""

	def __init__(
		self,
		detector: DuplicateDetector | None = None,
	):
		self.detector = detector or DuplicateDetector()

	async def check_batch(
		self,
		batch_files: list[tuple[str, Path]],
		existing_hashes: list[tuple[str, HashResult]] | None = None,
	) -> dict[str, list[DuplicateMatch]]:
		"""
		Check all files in a batch for duplicates.

		Args:
			batch_files: List of (document_id, file_path) tuples
			existing_hashes: Optional existing document hashes

		Returns:
			Dict mapping document_id to list of duplicate matches
		"""
		results: dict[str, list[DuplicateMatch]] = {}
		batch_hashes: list[tuple[str, HashResult]] = []

		# Hash all batch files
		for doc_id, file_path in batch_files:
			try:
				doc_hash = self.detector.hash_file(file_path)
				batch_hashes.append((doc_id, doc_hash))
			except Exception as e:
				logger.error(f"Failed to hash {file_path}: {e}")

		# Check each document
		all_hashes = (existing_hashes or []) + batch_hashes

		for idx, (doc_id, doc_hash) in enumerate(batch_hashes):
			# Exclude self from comparison
			comparison_hashes = [
				(other_id, other_hash)
				for other_id, other_hash in all_hashes
				if other_id != doc_id
			]

			matches = await self.detector.find_duplicates(
				doc_hash,
				comparison_hashes,
			)

			if matches:
				results[doc_id] = matches

		return results

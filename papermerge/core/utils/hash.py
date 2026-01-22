# (c) Copyright Datacraft, 2026
"""Utility for calculating BLAKE3 hashes."""
import blake3

def calculate_blake3(file_path: str) -> str:
    """
    Calculate the BLAKE3 hash of a file.
    
    Args:
        file_path: Path to the file.
        
    Returns:
        The hex-encoded BLAKE3 hash.
    """
    hasher = blake3.blake3()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()

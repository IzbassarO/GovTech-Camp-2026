"""Streaming SHA-256 hashing of raw source files."""

from __future__ import annotations

import hashlib
from pathlib import Path

_CHUNK_SIZE = 1024 * 1024


def sha256_file(path: Path) -> str:
    """Compute the SHA-256 of a file without loading it fully into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    """SHA-256 of a UTF-8 string (used for cache keys, not for files)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

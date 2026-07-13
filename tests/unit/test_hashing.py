import hashlib
from pathlib import Path

from dalel.ingestion.hashing import sha256_file, sha256_text


def test_sha256_file_matches_hashlib(tmp_path: Path) -> None:
    payload = b"dalel phase 0" * 1000
    target = tmp_path / "sample.bin"
    target.write_bytes(payload)
    assert sha256_file(target) == hashlib.sha256(payload).hexdigest()


def test_sha256_file_empty(tmp_path: Path) -> None:
    target = tmp_path / "empty.bin"
    target.write_bytes(b"")
    assert sha256_file(target) == hashlib.sha256(b"").hexdigest()


def test_sha256_text_stable() -> None:
    assert sha256_text("abc") == hashlib.sha256(b"abc").hexdigest()

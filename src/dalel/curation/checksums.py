"""Checksum inventory for curated dataset files."""

from __future__ import annotations

import json
from pathlib import Path

from dalel.ingestion.hashing import sha256_file

CHECKSUMS_FILENAME = "checksums.jsonl"


def build_checksums(dataset_dir: Path) -> list[dict[str, object]]:
    """Checksum every dataset file except the checksum inventory itself
    (a file cannot contain its own final hash)."""
    records: list[dict[str, object]] = []
    for path in sorted(dataset_dir.rglob("*")):
        if not path.is_file() or path.name == CHECKSUMS_FILENAME:
            continue
        relative = path.relative_to(dataset_dir).as_posix()
        record: dict[str, object] = {
            "file": relative,
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        if path.suffix == ".jsonl":
            record["records"] = sum(
                1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
            )
        records.append(record)
    return records


def write_checksums(dataset_dir: Path) -> None:
    records = build_checksums(dataset_dir)
    target = dataset_dir / CHECKSUMS_FILENAME
    with target.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False))
            handle.write("\n")


def verify_checksums(dataset_dir: Path) -> list[str]:
    """Compare the stored inventory against the actual files."""
    errors: list[str] = []
    inventory_path = dataset_dir / CHECKSUMS_FILENAME
    if not inventory_path.is_file():
        return [f"missing {CHECKSUMS_FILENAME}"]
    stored: dict[str, dict[str, object]] = {}
    for line_number, line in enumerate(
        inventory_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"{CHECKSUMS_FILENAME}:{line_number}: invalid JSON: {exc}")
            continue
        name = str(record.get("file"))
        if name in stored:
            errors.append(f"{CHECKSUMS_FILENAME}:{line_number}: duplicate checksum path: {name}")
        stored[name] = record

    actual = {str(record["file"]): record for record in build_checksums(dataset_dir)}
    for name in sorted(set(stored) - set(actual)):
        errors.append(f"checksums list a missing file: {name}")
    for name in sorted(set(actual) - set(stored)):
        errors.append(f"file not covered by checksums: {name}")
    for name in sorted(set(stored) & set(actual)):
        if stored[name].get("sha256") != actual[name]["sha256"]:
            errors.append(f"checksum mismatch: {name}")
        if stored[name].get("size_bytes") != actual[name]["size_bytes"]:
            errors.append(f"size mismatch: {name}")
    return errors

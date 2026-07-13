"""Atomic output storage and cache keys.

Layout (role-separated to protect the leakage boundary):

    data/processed/model_inputs/{project_id}/{document_id}/
    data/processed/label_sources/{project_id}/{document_id}/

Writes are atomic: everything lands in a temporary sibling directory first and
is renamed into place at the end. A partially written output can never be
mistaken for a successful one.
"""

from __future__ import annotations

import json
import logging
import shutil
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from dalel.config import INGESTION_SCHEMA_VERSION
from dalel.ingestion.hashing import sha256_text

logger = logging.getLogger(__name__)


def compute_cache_key(
    source_sha256: str,
    parser_names_and_versions: list[tuple[str, str | None]],
    ocr_mode: str,
    schema_version: str = INGESTION_SCHEMA_VERSION,
) -> str:
    """Cache key over source hash, parser identities, OCR mode and schema version."""
    parts = [source_sha256]
    for name, version in sorted(parser_names_and_versions):
        parts.append(f"{name}={version or 'unknown'}")
    parts.append(f"ocr={ocr_mode}")
    parts.append(f"schema={schema_version}")
    return sha256_text("|".join(parts))


def document_output_dir(output_root: Path, project_id: str, document_id: str) -> Path:
    return output_root / project_id / document_id


def load_existing_report(out_dir: Path) -> dict[str, Any] | None:
    report_path = out_dir / "ingestion_report.json"
    if not report_path.is_file():
        return None
    try:
        loaded = json.loads(report_path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


_CORE_OUTPUT_FILES = (
    "document.json",
    "pages.jsonl",
    "sections.jsonl",
    "tables.jsonl",
    "images.jsonl",
)


def is_cached(out_dir: Path, cache_key: str) -> bool:
    """True when a completed, structurally intact output with the same cache
    key already exists. A report alone is not enough: every core output file
    must be present, otherwise the document is reprocessed."""
    report = load_existing_report(out_dir)
    if report is None:
        return False
    if report.get("cache_key") != cache_key or report.get("extraction_status") not in {
        "success",
        "partial",
    }:
        return False
    return all((out_dir / name).is_file() for name in _CORE_OUTPUT_FILES)


def _dump_model(model: BaseModel) -> str:
    return model.model_dump_json(exclude_none=False)


def _write_jsonl(path: Path, records: Sequence[BaseModel]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(_dump_model(record))
            handle.write("\n")


def _write_json(path: Path, model: BaseModel) -> None:
    payload = json.dumps(model.model_dump(mode="json"), ensure_ascii=False, indent=2)
    path.write_text(payload + "\n", encoding="utf-8")


def write_document_output(
    out_dir: Path,
    document_record: BaseModel,
    pages: Sequence[BaseModel],
    sections: Sequence[BaseModel],
    tables: Sequence[BaseModel],
    images: Sequence[BaseModel],
    image_blobs: dict[str, bytes],
    report: BaseModel,
) -> None:
    """Atomically write the full per-document output directory.

    ``image_blobs`` maps relative paths (e.g. ``images/img_0001.png``) to bytes.
    """
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    _sweep_stale_workdirs(out_dir)
    tmp_dir = out_dir.parent / f".tmp__{out_dir.name}__{uuid.uuid4().hex[:8]}"
    trash_dir = out_dir.parent / f".old__{out_dir.name}__{uuid.uuid4().hex[:8]}"

    try:
        tmp_dir.mkdir(parents=True)
        _write_json(tmp_dir / "document.json", document_record)
        _write_jsonl(tmp_dir / "pages.jsonl", pages)
        _write_jsonl(tmp_dir / "sections.jsonl", sections)
        _write_jsonl(tmp_dir / "tables.jsonl", tables)
        _write_jsonl(tmp_dir / "images.jsonl", images)
        images_dir = tmp_dir / "images"
        images_dir.mkdir()
        for relative_path, blob in image_blobs.items():
            target = tmp_dir / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(blob)
        _write_json(tmp_dir / "ingestion_report.json", report)

        if out_dir.exists():
            out_dir.rename(trash_dir)
        tmp_dir.rename(out_dir)
    except Exception:
        # Roll back: never leave a half-written directory in the final location.
        if trash_dir.exists() and not out_dir.exists():
            trash_dir.rename(out_dir)
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
    if trash_dir.exists():
        # The new output is already committed; failing to delete the old copy
        # must not fail the document. Stale dirs are swept on the next run.
        shutil.rmtree(trash_dir, ignore_errors=True)


def _sweep_stale_workdirs(out_dir: Path) -> None:
    """Remove leftover ``.tmp__``/``.old__`` dirs from an earlier hard crash."""
    for pattern in (f".tmp__{out_dir.name}__*", f".old__{out_dir.name}__*"):
        for stale in out_dir.parent.glob(pattern):
            logger.warning("removing stale ingestion workdir: %s", stale)
            shutil.rmtree(stale, ignore_errors=True)


def write_project_summary(output_root: Path, project_id: str, summary: dict[str, Any]) -> None:
    """Write ``project.json`` atomically next to the project's document dirs."""
    project_dir = output_root / project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = project_dir / f".tmp__project__{uuid.uuid4().hex[:8]}.json"
    payload = json.dumps(summary, ensure_ascii=False, indent=2)
    tmp_path.write_text(payload + "\n", encoding="utf-8")
    tmp_path.replace(project_dir / "project.json")

"""Per-document ingestion reports and per-project summaries."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dalel.config import INGESTION_SCHEMA_VERSION, MODEL_INPUTS_DIRNAME, processed_root

logger = logging.getLogger(__name__)

_EXPECTED_SKIP_REASONS = {
    "auxiliary_archive_never_ingested",
    "excluded_by_leakage_boundary",
}


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class DocumentResult:
    """Outcome of one document within a batch run."""

    project_id: str
    document_id: str
    document_type: str
    role: str
    status: str  # success | partial | failed | skipped | skipped_cached
    reason: str | None = None
    parser_name: str | None = None
    fallback_used: bool = False
    pages: int = 0
    tables: int = 0
    images: int = 0
    sections: int = 0
    ocr_pages: int = 0
    warning_count: int = 0
    errors: list[str] = field(default_factory=list)
    output_dir: str | None = None
    elapsed_seconds: float | None = None


@dataclass
class BatchResult:
    started_at: str
    completed_at: str | None = None
    results: list[DocumentResult] = field(default_factory=list)

    def by_status(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for result in self.results:
            counts[result.status] = counts.get(result.status, 0) + 1
        return counts

    @property
    def ok(self) -> bool:
        """Whether the CLI may report a successful batch.

        An empty result set and an unexpected ``skipped`` result are failures:
        otherwise a selection/routing regression could silently exit zero without
        producing output. Cache hits and the explicit leakage/archive boundary are
        expected no-output outcomes.
        """
        if not self.results:
            return False
        for result in self.results:
            if result.status == "failed":
                return False
            if result.status == "skipped" and result.reason not in _EXPECTED_SKIP_REASONS:
                return False
        return True


def _read_document_json(path: Path) -> dict[str, Any] | None:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def build_project_summary(
    repo_root: Path,
    project_id: str,
    manifest_document_count: int,
    run_results: list[DocumentResult],
) -> dict[str, Any]:
    """Merge this run's results with model-input outputs already on disk.

    The summary lives under ``model_inputs`` and enumerates label-source or
    archive documents only as skip records (metadata, never content).
    """
    model_inputs_dir = processed_root(repo_root) / MODEL_INPUTS_DIRNAME / project_id

    on_disk: dict[str, dict[str, Any]] = {}
    if model_inputs_dir.is_dir():
        for document_json in sorted(model_inputs_dir.glob("*/document.json")):
            # pathlib glob matches dot-directories: never read .tmp__/.old__
            # leftovers of an interrupted atomic write as valid documents.
            if document_json.parent.name.startswith("."):
                continue
            record = _read_document_json(document_json)
            if record is None:
                continue
            on_disk[str(record.get("document_id"))] = {
                "document_id": record.get("document_id"),
                "document_type": record.get("document_type"),
                "role": record.get("role"),
                "status": record.get("extraction_status"),
                "parser_name": record.get("parser_name"),
                "page_count": record.get("page_count"),
                "output_dir": str(document_json.parent.relative_to(repo_root)),
                "source": "on_disk",
            }

    for result in run_results:
        if result.project_id != project_id:
            continue
        if result.role != "model_input":
            # Leakage boundary: the model_inputs summary records label sources
            # and archives only as skip entries — never a success status, a
            # parser, or an output_dir pointing into the label_sources tree.
            on_disk[result.document_id] = {
                "document_id": result.document_id,
                "document_type": result.document_type,
                "role": result.role,
                "status": "skipped",
                "reason": result.reason or "excluded_by_leakage_boundary",
                "source": "this_run",
            }
            continue
        if result.status == "skipped_cached" and result.document_id in on_disk:
            # The cached on-disk record is richer and still current.
            continue
        on_disk[result.document_id] = {
            "document_id": result.document_id,
            "document_type": result.document_type,
            "role": result.role,
            "status": result.status,
            "reason": result.reason,
            "parser_name": result.parser_name,
            "page_count": result.pages or None,
            "output_dir": result.output_dir,
            "source": "this_run",
        }

    documents = sorted(on_disk.values(), key=lambda item: str(item.get("document_id")))
    status_counts: dict[str, int] = {}
    for document in documents:
        status = str(document.get("status"))
        status_counts[status] = status_counts.get(status, 0) + 1

    return {
        "schema_version": INGESTION_SCHEMA_VERSION,
        "project_id": project_id,
        "generated_at": utc_now_iso(),
        "manifest_document_count": manifest_document_count,
        "status_counts": status_counts,
        "documents": documents,
    }


def format_batch_summary(batch: BatchResult) -> str:
    lines = ["", "=== Ingestion summary ==="]
    for result in batch.results:
        parts = [f"{result.status:<14}", f"{result.project_id}/{result.document_id}"]
        if result.reason:
            parts.append(f"reason={result.reason}")
        if result.parser_name:
            parts.append(f"parser={result.parser_name}")
        if result.fallback_used:
            parts.append("fallback=yes")
        if result.status in {"success", "partial"}:
            parts.append(
                f"pages={result.pages} tables={result.tables}"
                f" images={result.images} ocr_pages={result.ocr_pages}"
            )
        if result.errors:
            parts.append(f"errors={len(result.errors)}")
        lines.append("  ".join(parts))
    counts = ", ".join(f"{status}={count}" for status, count in sorted(batch.by_status().items()))
    lines.append(f"Totals: {counts or 'nothing selected'}")
    return "\n".join(lines)

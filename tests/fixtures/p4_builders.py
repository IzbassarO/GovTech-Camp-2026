"""Synthetic curated-dataset fixtures for P4 tests. Small, no real data."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from fixtures.p3_builders import document, provenance, section

SHA_P4 = "e" * 64

PROJECT = "proj_p4a"
DOC_NDV = f"{PROJECT}__ndv__001"
DOC_PEK = f"{PROJECT}__pek__001"

__all__ = [
    "DOC_NDV",
    "DOC_PEK",
    "PROJECT",
    "SHA_P4",
    "document",
    "provenance",
    "section",
    "write_dataset",
]


def write_dataset(
    root: Path,
    documents: list[dict[str, Any]],
    sections: list[dict[str, Any]],
    tables: list[dict[str, Any]] | None = None,
    projects_meta: dict[str, dict[str, Any]] | None = None,
    with_checksums: bool = True,
) -> Path:
    """Write a minimal curated dataset directory readable by run_p4.

    ``projects_meta`` maps project_id -> {"region": ..., "industry": ...}.
    """
    dataset = root / "data" / "curated" / "v1"
    dataset.mkdir(parents=True, exist_ok=True)
    tables = tables or []
    projects_meta = projects_meta or {}
    project_ids = sorted({str(d["project_id"]) for d in documents})
    projects = [
        {
            "project_id": project_id,
            "region": projects_meta.get(project_id, {}).get("region"),
            "industry": projects_meta.get(project_id, {}).get("industry"),
            "languages": ["ru"],
            "model_input_document_ids": sorted(
                str(d["document_id"]) for d in documents if d["project_id"] == project_id
            ),
            "label_source_document_ids": [],
        }
        for project_id in project_ids
    ]

    def _write(name: str, records: list[dict[str, Any]]) -> None:
        (dataset / name).write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
            encoding="utf-8",
        )

    _write("projects.jsonl", projects)
    _write("documents.jsonl", documents)
    _write("sections.jsonl", sections)
    _write("tables.jsonl", tables)
    if with_checksums:
        entries = []
        for name in ("projects.jsonl", "documents.jsonl", "sections.jsonl", "tables.jsonl"):
            payload = (dataset / name).read_bytes()
            entries.append(
                {
                    "file": name,
                    "size_bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            )
        _write("checksums.jsonl", entries)
    return dataset

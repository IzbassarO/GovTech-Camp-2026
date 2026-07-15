"""Synthetic curated-dataset fixtures for P3 tests. Small, no real data."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

SHA_P3 = "d" * 64

PROJECT_A = "proj_p3a"
DOC_NDV = f"{PROJECT_A}__ndv__001"
DOC_SUMMARY = f"{PROJECT_A}__nontechnical_summary__001"


def provenance(document_id: str, page: int | None, doc_type: str = "ndv") -> dict[str, Any]:
    return {
        "project_id": document_id.split("__")[0],
        "document_id": document_id,
        "document_type": doc_type,
        "role": "model_input",
        "source_path": f"data/raw/{document_id}.pdf",
        "source_sha256": SHA_P3,
        "page_number": page,
        "bbox": None,
        "extraction_method": "docling",
        "parser_name": "docling",
        "parser_version": "2.112.0",
        "ocr_used": False,
        "created_at": "2026-07-14T00:00:00+00:00",
    }


def section(
    document_id: str,
    index: int,
    text: str,
    title: str | None = None,
    page: int = 1,
    page_end: int | None = None,
    doc_type: str = "ndv",
) -> dict[str, Any]:
    return {
        "schema_version": "1.1.0",
        "section_id": f"{document_id}__sec_{index:04d}",
        "title": title,
        "level": 1,
        "page_start": page,
        "page_end": page_end if page_end is not None else page,
        "text": text,
        "char_count": len(text.strip()),
        "warnings": [],
        "provenance": provenance(document_id, page, doc_type),
        "record_ref": {"file": "fixture", "line": index},
    }


def table(
    document_id: str,
    index: int,
    cells: list[list[str]],
    page: int = 1,
    caption: str | None = None,
    doc_type: str = "ndv",
) -> dict[str, Any]:
    return {
        "schema_version": "1.1.0",
        "table_id": f"{document_id}__tab_{index:04d}",
        "page_number": page,
        "num_rows": len(cells),
        "num_cols": max(len(r) for r in cells),
        "cells": cells,
        "caption": caption,
        "confidence": None,
        "confidence_source": None,
        "warnings": [],
        "provenance": provenance(document_id, page, doc_type),
        "record_ref": {"file": "fixture", "line": index},
    }


def page_record(
    document_id: str,
    number: int,
    text: str = "страница фикстуры",
    ocr_applied: bool = False,
    doc_type: str = "ndv",
) -> dict[str, Any]:
    return {
        "schema_version": "1.1.0",
        "page_number": number,
        "width": 595.0,
        "height": 842.0,
        "rotation": 0,
        "text": text,
        "char_count": len(text.strip()),
        "ocr_applied": ocr_applied,
        "has_embedded_text": True,
        "warnings": [],
        "provenance": provenance(document_id, number, doc_type),
        "record_ref": {"file": "fixture", "line": number},
    }


def document(
    document_id: str,
    doc_type: str = "ndv",
    page_count: int = 3,
    ocr_pages: list[int] | None = None,
) -> dict[str, Any]:
    return {
        "project_id": document_id.split("__")[0],
        "document_id": document_id,
        "document_type": doc_type,
        "role": "model_input",
        "file_format": "pdf",
        "languages": ["ru"],
        "page_count": page_count,
        "document_mode": "digital",
        "extraction_status": "success",
        "parser_name": "docling",
        "parser_version": "2.112.0",
        "ocr": {"ocr_pages": ocr_pages or [], "ocr_page_count": len(ocr_pages or [])},
        "source_path": f"data/raw/{document_id}.pdf",
        "source_sha256": SHA_P3,
        "source_url": None,
        "ingestion_schema_version": "1.1.0",
        "normalization_version": "1.0.0",
        "record_ref": {"file": "fixture", "line": 1},
    }


def write_dataset(
    root: Path,
    documents: list[dict[str, Any]],
    sections: list[dict[str, Any]],
    tables: list[dict[str, Any]],
    pages: list[dict[str, Any]] | None = None,
    with_checksums: bool = True,
) -> Path:
    """Write a minimal curated dataset directory readable by run_p3."""
    dataset = root / "data" / "curated" / "v1"
    dataset.mkdir(parents=True, exist_ok=True)
    project_ids = sorted({str(d["project_id"]) for d in documents})
    projects = [
        {
            "project_id": project_id,
            "languages": ["ru"],
            "model_input_document_ids": sorted(
                str(d["document_id"]) for d in documents if d["project_id"] == project_id
            ),
            "label_source_document_ids": [],
        }
        for project_id in project_ids
    ]
    if pages is None:
        pages = []
        for doc in documents:
            for number in range(1, int(doc["page_count"]) + 1):
                pages.append(
                    page_record(str(doc["document_id"]), number, doc_type=doc["document_type"])
                )

    def _write(name: str, records: list[dict[str, Any]]) -> None:
        (dataset / name).write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
            encoding="utf-8",
        )

    _write("projects.jsonl", projects)
    _write("documents.jsonl", documents)
    _write("pages.jsonl", pages)
    _write("sections.jsonl", sections)
    _write("tables.jsonl", tables)
    if with_checksums:
        entries = []
        for name in (
            "projects.jsonl",
            "documents.jsonl",
            "pages.jsonl",
            "sections.jsonl",
            "tables.jsonl",
        ):
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


def emission_table(
    document_id: str,
    index: int,
    rows: list[tuple[str, str, str]],
    total: str | None = None,
    unit_header: str = "Выброс, т/год",
    page: int = 2,
    doc_type: str = "ndv",
) -> dict[str, Any]:
    """Substance table: (name, code, value) rows + optional «Итого» row."""
    cells = [["Вещество", "Код", unit_header]]
    for name, code, value in rows:
        cells.append([name, code, value])
    if total is not None:
        cells.append(["Итого:", "", total])
    return table(document_id, index, cells, page=page, doc_type=doc_type)

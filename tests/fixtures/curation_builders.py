"""Synthetic processed-corpus fixture for curation/P1 tests. No real PDFs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_L = "c" * 64

PROJECT_ID = "proj_c1"
DOC_LEGACY = "proj_c1__ndv__001"  # ingestion schema 1.0.0, no table counters
DOC_NATIVE = "proj_c1__action_plan__001"  # ingestion schema 1.1.0
DOC_LABEL = "proj_c1__hearing_protocol__001"


def _provenance(document_id: str, sha256: str, page: int | None, doc_type: str, role: str):
    return {
        "project_id": PROJECT_ID,
        "document_id": document_id,
        "document_type": doc_type,
        "role": role,
        "source_path": f"data/raw/{PROJECT_ID}/{document_id}.pdf",
        "source_sha256": sha256,
        "page_number": page,
        "bbox": None,
        "extraction_method": "docling",
        "parser_name": "docling",
        "parser_version": "2.112.0",
        "ocr_used": False,
        "created_at": "2026-07-14T00:00:00+00:00",
    }


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8"
    )


def _write_doc_dir(
    root: Path,
    document_id: str,
    doc_type: str,
    role: str,
    sha256: str,
    schema_version: str,
    with_native_counters: bool,
    page_text: str = "Насыщенная текстом страница синтетического документа для тестов.",
) -> Path:
    doc_dir = root / PROJECT_ID / document_id
    (doc_dir / "images").mkdir(parents=True)

    document = {
        "schema_version": schema_version,
        "project_id": PROJECT_ID,
        "document_id": document_id,
        "document_type": doc_type,
        "role": role,
        "use_as_model_feature": role == "model_input",
        "label_timing": "pre_review" if role == "model_input" else "post_review",
        "source_path": f"data/raw/{PROJECT_ID}/{document_id}.pdf",
        "source_url": "https://example.invalid/1",
        "source_sha256": sha256,
        "original_filename": f"{document_id}.pdf",
        "file_format": "pdf",
        "parser_name": "docling",
        "parser_version": "2.112.0",
        "page_count": 1,
        "languages": ["ru"],
        "document_mode": "digital",
        "ocr": {
            "mode": "auto",
            "engine": None,
            "engine_version": None,
            "engine_available": False,
            "engine_ran": False,
            "ocr_pages": [],
            "ocr_page_count": 0,
            "candidate_pages": [],
            "elapsed_seconds": None,
            "warnings": [],
        },
        "parser_confidence": None,
        "parser_confidence_source": None,
        "extraction_status": "success",
        "created_at": "2026-07-14T00:00:00+00:00",
        "warnings": [],
    }
    (doc_dir / "document.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    prov = _provenance(document_id, sha256, 1, doc_type, role)
    _write_jsonl(
        doc_dir / "pages.jsonl",
        [
            {
                "schema_version": schema_version,
                "page_number": 1,
                "width": 595.0,
                "height": 842.0,
                "rotation": 0,
                "text": page_text,
                "char_count": len(page_text.strip()),
                "ocr_applied": False,
                "has_embedded_text": True,
                "warnings": [],
                "provenance": prov,
            }
        ],
    )
    _write_jsonl(
        doc_dir / "sections.jsonl",
        [
            {
                "schema_version": schema_version,
                "section_id": f"{document_id}__sec_0001",
                "title": "Введение",
                "level": 1,
                "page_start": 1,
                "page_end": 1,
                "text": page_text,
                "char_count": len(page_text.strip()),
                "warnings": [],
                "provenance": prov,
            }
        ],
    )
    _write_jsonl(
        doc_dir / "tables.jsonl",
        [
            {
                "schema_version": schema_version,
                "table_id": f"{document_id}__tab_0001",
                "page_number": 1,
                "num_rows": 2,
                "num_cols": 2,
                "cells": [["вещество", "лимит"], ["пыль", "0.5"]],
                "caption": None,
                "confidence": None,
                "confidence_source": None,
                "warnings": [],
                "provenance": prov,
            }
        ],
    )
    (doc_dir / "images" / "img_0001.png").write_bytes(b"\x89PNG\r\n\x1a\nfixture")
    _write_jsonl(
        doc_dir / "images.jsonl",
        [
            {
                "schema_version": schema_version,
                "image_id": f"{document_id}__img_0001",
                "page_number": 1,
                "width_px": 10,
                "height_px": 10,
                "image_path": "images/img_0001.png",
                "classification": None,
                "classification_source": None,
                "warnings": [],
                "provenance": prov,
            }
        ],
    )

    report: dict[str, Any] = {
        "schema_version": schema_version,
        "project_id": PROJECT_ID,
        "document_id": document_id,
        "started_at": "2026-07-14T00:00:00+00:00",
        "completed_at": "2026-07-14T00:00:01+00:00",
        "elapsed_seconds": 1.0,
        "parser_attempts": [
            {
                "parser_name": "docling",
                "parser_version": "2.112.0",
                "status": "success",
                "error": None,
            }
        ],
        "fallback_used": False,
        "pages_processed": 1,
        "ocr_pages": 0,
        "table_count": 1,
        "image_count": 1,
        "section_count": 1,
        "warning_count": 0,
        "warnings": [],
        "errors": [],
        "raw_hash_before": sha256,
        "raw_hash_after": sha256,
        "hash_unchanged": True,
        "cache_key": "k" * 64,
        "ocr_mode": "auto",
        "extraction_status": "success",
    }
    if with_native_counters:
        report["detected_table_items"] = 2
        report["serialized_table_count"] = 1
        report["skipped_empty_table_items"] = 1
    (doc_dir / "ingestion_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return doc_dir


def make_processed_repo(root: Path) -> dict[str, Path]:
    """Create manifest + processed trees + annotations in ``root``."""
    processed = root / "data" / "processed"
    mi = processed / "model_inputs"
    ls = processed / "label_sources"
    legacy_dir = _write_doc_dir(mi, DOC_LEGACY, "ndv", "model_input", SHA_A, "1.0.0", False)
    native_dir = _write_doc_dir(mi, DOC_NATIVE, "action_plan", "model_input", SHA_B, "1.1.0", True)
    label_dir = _write_doc_dir(
        ls, DOC_LABEL, "hearing_protocol", "label_source", SHA_L, "1.1.0", True
    )

    raw = root / "data" / "raw" / PROJECT_ID
    raw.mkdir(parents=True)
    (raw / "source_metadata.json").write_text(
        json.dumps({"downloaded_at": "2026-07-13", "project_id": PROJECT_ID}),
        encoding="utf-8",
    )

    manifest_dir = root / "data" / "manifests"
    manifest_dir.mkdir(parents=True)
    project = {
        "schema_version": "1.0",
        "project_id": PROJECT_ID,
        "source_metadata_path": f"data/raw/{PROJECT_ID}/source_metadata.json",
        "source_url": "https://example.invalid/1",
        "region": "Test",
        "industry": "testing",
        "languages": ["ru"],
        "documents": [
            {
                "document_id": DOC_LEGACY,
                "local_path": f"data/raw/{PROJECT_ID}/{DOC_LEGACY}.pdf",
                "original_filename": f"{DOC_LEGACY}.pdf",
                "document_type": "ndv",
                "role": "model_input",
                "use_as_model_feature": True,
                "file_format": "pdf",
                "sha256": SHA_A,
                "label_timing": "pre_review",
                "notes": None,
            },
            {
                "document_id": DOC_NATIVE,
                "local_path": f"data/raw/{PROJECT_ID}/{DOC_NATIVE}.pdf",
                "original_filename": f"{DOC_NATIVE}.pdf",
                "document_type": "action_plan",
                "role": "model_input",
                "use_as_model_feature": True,
                "file_format": "pdf",
                "sha256": SHA_B,
                "label_timing": "pre_review",
                "notes": None,
            },
            {
                "document_id": DOC_LABEL,
                "local_path": f"data/raw/{PROJECT_ID}/{DOC_LABEL}.pdf",
                "original_filename": f"{DOC_LABEL}.pdf",
                "document_type": "hearing_protocol",
                "role": "label_source",
                "use_as_model_feature": False,
                "file_format": "pdf",
                "sha256": SHA_L,
                "label_timing": "post_review",
                "notes": None,
            },
        ],
    }
    (manifest_dir / "projects.jsonl").write_text(
        json.dumps(project, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    annotations = root / "data" / "annotations" / PROJECT_ID
    annotations.mkdir(parents=True)
    (annotations / "weak_findings.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "project_id": PROJECT_ID,
                "annotation_type": "weak_labels",
                "review_status": "not_expert_verified",
                "source_documents": [f"data/raw/{PROJECT_ID}/{DOC_LABEL}.pdf"],
                "findings": [
                    {
                        "finding_id": f"{PROJECT_ID}__weak__001",
                        "issue_type": "internal_metadata_inconsistency",
                        "title": "Тестовая слабая находка",
                        "description": "Описание для теста.",
                        "severity": "unknown",
                        "source_document": f"data/raw/{PROJECT_ID}/{DOC_LABEL}.pdf",
                        "source_page": 1,
                        "target_documents": [f"data/raw/{PROJECT_ID}/{DOC_LEGACY}.pdf"],
                        "evidence_text": "Цитата.",
                        "confidence": "weak",
                        "expert_verified": False,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return {
        "processed": processed,
        "manifest": manifest_dir / "projects.jsonl",
        "legacy_dir": legacy_dir,
        "native_dir": native_dir,
        "label_dir": label_dir,
        "annotations_root": root / "data" / "annotations",
    }

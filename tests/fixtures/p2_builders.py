"""Synthetic fixtures for P2 tests: corpus records and dataset helpers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from fixtures.p3_builders import document, section, write_dataset

PROJECT_B = "proj_p2a"
DOC_NDV_P2 = f"{PROJECT_B}__ndv__001"
DOC_PEK_P2 = f"{PROJECT_B}__pek__001"

__all__ = [
    "DOC_NDV_P2",
    "DOC_PEK_P2",
    "PROJECT_B",
    "corpus_record",
    "document",
    "section",
    "write_corpus",
    "write_dataset",
]


def corpus_record(
    requirement_id: str = "DEMO-REQ-901",
    obligation_type: str = "mandatory_section",
    requirement_text: str = "Документ должен содержать раздел о мониторинге атмосферного воздуха.",
    title: str = "Тестовое требование",
    required_document_type: str | None = "ndv",
    required_concepts: list[str] | None = None,
    applicability_tags: list[str] | None = None,
    demo_only: bool = True,
    is_authoritative: bool = False,
    corpus_version: str = "1.0.0",
    language: str = "ru",
    effective_from: str | None = None,
    effective_to: str | None = None,
    source_hash: str | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "requirement_id": requirement_id,
        "corpus_id": "test-corpus",
        "corpus_version": corpus_version,
        "jurisdiction": "DEMO",
        "authority": "Тестовый корпус (синтетический)",
        "document_title": "Тестовый свод требований",
        "document_number": None,
        "article": "T-1",
        "requirement_text": requirement_text,
        "title": title,
        "obligation_type": obligation_type,
        "applicability_tags": applicability_tags
        if applicability_tags is not None
        else (["document_type:ndv"] if required_document_type == "ndv" else ["package:any"]),
        "environmental_topics": ["monitoring"],
        "regulated_activities": ["operation"],
        "required_document_type": required_document_type,
        "required_concepts": required_concepts
        if required_concepts is not None
        else ["мониторинг атмосферного воздуха"],
        "effective_from": effective_from,
        "effective_to": effective_to,
        "source_url": None,
        "source_file": "tests/fixture",
        "source_hash": source_hash
        if source_hash is not None
        else hashlib.sha256(requirement_text.encode("utf-8")).hexdigest(),
        "is_authoritative": is_authoritative,
        "demo_only": demo_only,
        "language": language,
        "notes": "Синтетическое тестовое требование.",
        "limitations": "Только для тестов.",
    }
    record.update(overrides)
    return record


def write_corpus(path: Path, records: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False))
            handle.write("\n")
    return path

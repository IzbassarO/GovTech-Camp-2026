"""Strict Curated Dataset v1 input validation for P3.

The ACCEPTED dataset contract already exists as the curated Pydantic models
(``extra="forbid"``, full nested typing, ID/hash patterns); P3 validates
every input record against those models BEFORE extraction, plus an explicit
supported-schema-version gate. Expected data problems become a concise
``P3RunError`` carrying the file, the JSONL line, the field path and a
corrective suggestion — never a Python/Rich traceback and never a partial
output directory.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ValidationError

from dalel.curation.schemas import (
    CuratedDocument,
    CuratedPageRecord,
    CuratedProject,
    CuratedSectionRecord,
    CuratedTableRecord,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    pass

SUPPORTED_INGESTION_SCHEMAS = frozenset({"1.0.0", "1.1.0"})

_RECORD_MODELS: dict[str, type[BaseModel]] = {
    "projects.jsonl": CuratedProject,
    "documents.jsonl": CuratedDocument,
    "pages.jsonl": CuratedPageRecord,
    "sections.jsonl": CuratedSectionRecord,
    "tables.jsonl": CuratedTableRecord,
}

_VERSIONED_FILES = frozenset({"pages.jsonl", "sections.jsonl", "tables.jsonl"})

_SUGGESTION = (
    " — the file does not match the accepted Curated Dataset v1 contract;"
    " run `dalel validate-curated` and rebuild with `dalel curate --force`"
    " if needed"
)


def _field_path(error: Any) -> str:
    return ".".join(str(part) for part in error.get("loc", ())) or "(record)"


def validate_input_records(
    file_name: str, records: list[dict[str, Any]], error_type: type[Exception]
) -> None:
    """Validate every record of one curated file against the accepted
    contract. Raises ``error_type`` (P3RunError) on the first violation."""
    model = _RECORD_MODELS.get(file_name)
    if model is None:
        return
    versioned = file_name in _VERSIONED_FILES
    for line_number, record in enumerate(records, start=1):
        if versioned:
            version = record.get("schema_version")
            if version not in SUPPORTED_INGESTION_SCHEMAS:
                raise error_type(
                    f"{file_name}: line {line_number}: unsupported schema_version"
                    f" {version!r} (supported:"
                    f" {', '.join(sorted(SUPPORTED_INGESTION_SCHEMAS))})"
                    f"{_SUGGESTION}"
                )
        try:
            model.model_validate(record)
        except ValidationError as exc:
            first = exc.errors()[0]
            raise error_type(
                f"{file_name}: line {line_number}: field"
                f" '{_field_path(first)}': {first.get('msg', 'invalid value')}"
                f"{_SUGGESTION}"
            ) from exc

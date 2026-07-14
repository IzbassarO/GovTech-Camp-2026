"""Provenance passthrough checks for curated records.

Curated records embed the original processed record verbatim plus a
``record_ref``; this module verifies that the mandatory provenance fields are
actually present and consistent — nothing is ever back-filled or invented.
"""

from __future__ import annotations

from typing import Any

REQUIRED_PROVENANCE_FIELDS = (
    "project_id",
    "document_id",
    "document_type",
    "role",
    "source_path",
    "source_sha256",
    "extraction_method",
    "parser_name",
    "parser_version",
    "ocr_used",
    "created_at",
)

# page_number and bbox are honest-nullable and must merely be present as keys.
NULLABLE_PROVENANCE_FIELDS = ("page_number", "bbox")


def provenance_errors(
    record: dict[str, Any],
    expected_project: str,
    expected_document: str,
    expected_sha256: str,
    context: str,
) -> list[str]:
    """Validate one record's provenance object; returns error strings."""
    errors: list[str] = []
    provenance = record.get("provenance")
    if not isinstance(provenance, dict):
        return [f"{context}: provenance object is missing"]

    for field_name in REQUIRED_PROVENANCE_FIELDS:
        if field_name not in provenance:
            errors.append(f"{context}: provenance.{field_name} is absent")
    for field_name in NULLABLE_PROVENANCE_FIELDS:
        if field_name not in provenance:
            errors.append(f"{context}: provenance.{field_name} key is absent (null allowed)")

    if provenance.get("project_id") != expected_project:
        errors.append(f"{context}: provenance.project_id mismatch")
    if provenance.get("document_id") != expected_document:
        errors.append(f"{context}: provenance.document_id mismatch")
    if provenance.get("source_sha256") != expected_sha256:
        errors.append(f"{context}: provenance.source_sha256 mismatch")
    return errors

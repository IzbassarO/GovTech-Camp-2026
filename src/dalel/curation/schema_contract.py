"""Standalone JSON Schema contract for the curated dataset.

``model_json_schema()`` cannot express arbitrary Pydantic model validators, so
this module adds a DETERMINISTIC augmentation layer on top of the generated
schemas: categorical enums, SHA-256/path patterns, traversal bans, table
content rules and image materialization coupling. The resulting ``schema.json``
must reject semantically invalid records under a standard JSON Schema
Draft 2020-12 validator WITHOUT any Pydantic runtime code.

``validate_records_with_jsonschema`` enforces exactly the distributed
``schema.json`` file against every production record, so the shipped contract
and the validation contract are the same artifact.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"

DOCUMENT_TYPES = [
    "ndv",
    "pek",
    "puo",
    "ovvos",
    "roos",
    "action_plan",
    "nontechnical_summary",
    "explanatory_note",
    "working_project_note",
    "hearing_protocol",
    "motivated_refusal",
    "map",
    "photo",
    "appendix",
    "archive",
    "unknown",
]
PARSER_NAMES = ["docling", "pymupdf", "python-docx"]
EXTRACTION_METHODS = [
    "docling",
    "docling_ocr",
    "pymupdf",
    "pymupdf_ocr",
    "python-docx",
    "python-docx_ocr",
]
SHA256_JS_PATTERN = "^[0-9a-f]{64}$"


def _no_traversal() -> dict[str, Any]:
    """Reject ``..`` PATH SEGMENTS (null values are unaffected).

    Consecutive dots inside a filename (``…гг..pdf``) are legitimate; only a
    whole ``..`` segment — ``../x``, ``x/../y``, ``x/..`` or exactly ``..`` —
    is traversal.
    """
    return {"not": {"type": "string", "pattern": "(^|/)\\.\\.(/|$)"}}


def _no_absolute() -> dict[str, Any]:
    return {"not": {"type": "string", "pattern": "^[/\\\\]"}}


def _safe_path(property_schema: dict[str, Any]) -> dict[str, Any]:
    return {"allOf": [property_schema, _no_traversal(), _no_absolute()]}


def _augment_provenance(defs: dict[str, Any]) -> None:
    provenance = defs.get("Provenance")
    if not provenance:
        return
    props = provenance["properties"]
    props["role"] = {"enum": ["model_input"]}
    props["document_type"] = {"enum": DOCUMENT_TYPES}
    props["source_sha256"] = {"type": "string", "pattern": SHA256_JS_PATTERN}
    props["parser_name"] = {"enum": PARSER_NAMES}
    props["extraction_method"] = {"enum": EXTRACTION_METHODS}
    props["source_path"] = _safe_path({"type": "string", "minLength": 1})
    props["page_number"] = {"anyOf": [{"type": "integer", "minimum": 1}, {"type": "null"}]}
    props["created_at"] = {"type": "string", "minLength": 10}
    props["project_id"] = {"type": "string", "minLength": 1}
    props["document_id"] = {"type": "string", "minLength": 1}


def _augment_record_ref(defs: dict[str, Any]) -> None:
    record_ref = defs.get("RecordRef")
    if not record_ref:
        return
    record_ref["properties"]["file"] = _safe_path({"type": "string", "minLength": 1})


def _ocr_metadata_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "mode": {"enum": ["auto", "always", "never"]},
            "engine": {"anyOf": [{"enum": ["easyocr", "tesseract"]}, {"type": "null"}]},
            "engine_version": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "engine_available": {"type": "boolean"},
            "engine_ran": {"type": "boolean"},
            "ocr_pages": {
                "type": "array",
                "items": {"type": "integer", "minimum": 1},
                "uniqueItems": True,
            },
            "ocr_page_count": {"type": "integer", "minimum": 0},
            "candidate_pages": {
                "type": "array",
                "items": {"type": "integer", "minimum": 1},
                "uniqueItems": True,
            },
            "elapsed_seconds": {"anyOf": [{"type": "number", "minimum": 0}, {"type": "null"}]},
            "warnings": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "mode",
            "engine",
            "engine_ran",
            "ocr_pages",
            "ocr_page_count",
            "candidate_pages",
            "warnings",
        ],
    }


def _unique_string_array() -> dict[str, Any]:
    return {"type": "array", "items": {"type": "string", "minLength": 1}, "uniqueItems": True}


def _int_counts_object() -> dict[str, Any]:
    return {"type": "object", "additionalProperties": {"type": "integer", "minimum": 0}}


def augment_schema(name: str, schema: dict[str, Any]) -> dict[str, Any]:
    """Deterministically inject standalone semantic constraints."""
    schema = json.loads(json.dumps(schema))  # deep copy, stable ordering
    schema["$schema"] = SCHEMA_DIALECT
    defs = schema.get("$defs", {})
    _augment_provenance(defs)
    _augment_record_ref(defs)
    props = schema.get("properties", {})

    if name in {"projects.jsonl", "document_groups.jsonl"}:
        for key in (
            "languages",
            "model_input_document_ids",
            "label_source_document_ids",
            "document_ids",
            "document_types",
            "ingestion_schema_versions",
        ):
            if key in props:
                props[key] = _unique_string_array()

    if name == "documents.jsonl":
        props["ocr"] = _ocr_metadata_schema()
        props["source_path"] = _safe_path(props["source_path"])
        props["languages"] = _unique_string_array()

    if name == "tables.jsonl":
        props["cells"] = {
            "type": "array",
            "minItems": 1,
            "items": {"type": "array", "items": {"type": "string"}},
            # Table validity contract, standalone: at least one row containing
            # at least one cell with non-whitespace content.
            "contains": {
                "type": "array",
                "contains": {"type": "string", "pattern": "\\S"},
            },
        }

    if name == "images.jsonl":
        for key in ("source_image_path", "curated_image_path", "image_path"):
            if key in props:
                props[key] = {"allOf": [props[key], _no_traversal(), _no_absolute()]}
        # Materialization coupling: records that carry bytes must pin the
        # physical curated copy (path + SHA-256 + positive size).
        schema.setdefault("allOf", []).append(
            {
                "if": {
                    "properties": {"image_path": {"type": "string"}},
                    "required": ["image_path"],
                },
                "then": {
                    "required": [
                        "curated_image_path",
                        "image_sha256",
                        "image_size_bytes",
                    ],
                    "properties": {
                        "curated_image_path": {"type": "string", "minLength": 8},
                        "image_sha256": {"type": "string", "pattern": SHA256_JS_PATTERN},
                        "image_size_bytes": {"type": "integer", "minimum": 1},
                        "source_image_path": {"type": "string", "minLength": 1},
                    },
                },
            }
        )

    if name == "weak_findings.jsonl":
        props["source_document_path"] = _safe_path(props["source_document_path"])
        props["target_document_ids"] = _unique_string_array()
        props["target_document_paths"] = {
            "type": "array",
            "items": _safe_path({"type": "string", "minLength": 1}),
            "uniqueItems": True,
        }

    if name == "input_manifest.jsonl":
        props["relative_path"] = _safe_path(props["relative_path"])

    if name == "build_report.json":
        props["counts"] = _int_counts_object()
        props["input_roles"] = _int_counts_object()

    if name == "dataset_statistics.json":
        for key in (
            "counts",
            "by_document_type",
            "by_extraction_status",
            "by_ingestion_schema",
            "by_document_mode",
            "table_validation",
        ):
            props[key] = _int_counts_object()
        props["per_project"] = {
            "type": "object",
            "additionalProperties": _int_counts_object(),
        }
        for key in ("languages", "regions", "industries"):
            props[key] = _unique_string_array()

    return schema


def build_schema_contract() -> dict[str, dict[str, Any]]:
    """The distributed contract: generated model schemas + augmentations."""
    from dalel.curation.reports import RECORD_MODELS

    return {
        name: augment_schema(name, model.model_json_schema())
        for name, model in RECORD_MODELS.items()
    }


def validate_records_with_jsonschema(dataset_dir: Path) -> list[str]:
    """Validate every production record against the DISTRIBUTED schema.json
    using a standard Draft 2020-12 validator (no Pydantic involved)."""
    import jsonschema

    errors: list[str] = []
    schema_path = dataset_dir / "schema.json"
    try:
        distributed = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"schema.json unreadable for standalone validation: {exc}"]
    files = distributed.get("files")
    if not isinstance(files, dict):
        return ["schema.json: 'files' object is missing"]

    def _validator(name: str) -> Any | None:
        schema = files.get(name)
        if not isinstance(schema, dict) or "properties" not in schema:
            errors.append(f"schema.json: no standalone schema for {name}")
            return None
        try:
            jsonschema.Draft202012Validator.check_schema(schema)
        except jsonschema.SchemaError as exc:
            errors.append(f"schema.json: {name} is not a valid Draft 2020-12 schema: {exc}")
            return None
        return jsonschema.Draft202012Validator(schema)

    jsonl_names = [
        "projects.jsonl",
        "documents.jsonl",
        "pages.jsonl",
        "sections.jsonl",
        "tables.jsonl",
        "images.jsonl",
        "weak_findings.jsonl",
        "document_groups.jsonl",
        "input_manifest.jsonl",
    ]
    for name in jsonl_names:
        validator = _validator(name)
        if validator is None:
            continue
        path = dataset_dir / name
        if not path.is_file():
            errors.append(f"standalone schema validation: {name} is missing")
            continue
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            record = json.loads(line)
            for error in validator.iter_errors(record):
                errors.append(
                    f"{name}:{line_number}: standalone schema violation at"
                    f" {'/'.join(str(p) for p in error.absolute_path) or '<root>'}:"
                    f" {error.message[:160]}"
                )

    for name in ("build_report.json", "dataset_statistics.json"):
        validator = _validator(name)
        if validator is None:
            continue
        payload = json.loads((dataset_dir / name).read_text(encoding="utf-8"))
        for error in validator.iter_errors(payload):
            errors.append(
                f"{name}: standalone schema violation at"
                f" {'/'.join(str(p) for p in error.absolute_path) or '<root>'}:"
                f" {error.message[:160]}"
            )
    return errors

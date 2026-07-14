"""validate-curated: independent validation of a built curated dataset.

Validates every record against the production Pydantic models (the same
models that generate ``schema.json``), verifies the physical image layer
(existence, uniqueness, containment, SHA-256), checksum coverage, foreign
keys, leakage isolation, path safety and schema completeness.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import ValidationError

from dalel.curation.checksums import verify_checksums
from dalel.curation.provenance import provenance_errors
from dalel.ingestion.hashing import sha256_file
from dalel.schemas.table import table_content_is_valid

REQUIRED_FILES = (
    "projects.jsonl",
    "documents.jsonl",
    "pages.jsonl",
    "sections.jsonl",
    "tables.jsonl",
    "images.jsonl",
    "weak_findings.jsonl",
    "document_groups.jsonl",
    "input_manifest.jsonl",
    "dataset_statistics.json",
    "schema.json",
    "label_schema.json",
    "checksums.jsonl",
    "dataset_card.md",
    "build_report.json",
)

# Downstream artifacts that must never appear in the input inventory.
FORBIDDEN_INPUT_PREFIXES = ("data/curated/", "data/results/")
FORBIDDEN_INPUT_FILES = ("data/annotations/p1_review_template.jsonl",)


@dataclass
class CuratedValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors


def _load_jsonl(path: Path, result: CuratedValidationResult, context: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not path.is_file():
        result.errors.append(f"{context}: file is missing")
        return records
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            result.errors.append(f"{context}:{line_number}: blank JSONL line")
            continue
        try:
            loaded = json.loads(line)
        except json.JSONDecodeError as exc:
            result.errors.append(f"{context}:{line_number}: invalid JSON: {exc}")
            continue
        if not isinstance(loaded, dict):
            result.errors.append(f"{context}:{line_number}: value must be an object")
            continue
        records.append(loaded)
    return records


def _relative_path_is_safe(value: str) -> bool:
    path = PurePosixPath(value)
    return not path.is_absolute() and ".." not in path.parts and not value.startswith("/")


def _validate_against_models(
    file_records: dict[str, list[dict[str, Any]]],
    payloads: dict[str, dict[str, Any]],
    result: CuratedValidationResult,
) -> None:
    """Every record must satisfy its production model — the same contract that
    ``schema.json`` distributes."""
    from dalel.curation.reports import RECORD_MODELS

    for name, records in file_records.items():
        model = RECORD_MODELS[name]
        for index, record in enumerate(records, start=1):
            try:
                model.model_validate(record)
            except ValidationError as exc:
                result.errors.append(
                    f"{name}:{index}: fails {model.__name__} schema validation:"
                    f" {str(exc).splitlines()[0]}"
                )
    for name, payload in payloads.items():
        model = RECORD_MODELS[name]
        try:
            model.model_validate(payload)
        except ValidationError as exc:
            result.errors.append(
                f"{name}: fails {model.__name__} schema validation: {str(exc).splitlines()[0]}"
            )


def _validate_schema_completeness(dataset_dir: Path, result: CuratedValidationResult) -> None:
    from dalel.curation.reports import RECORD_MODELS

    try:
        schema = json.loads((dataset_dir / "schema.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        result.errors.append(f"schema.json unreadable: {exc}")
        return
    files = schema.get("files")
    if not isinstance(files, dict):
        result.errors.append("schema.json: 'files' object is missing")
        return
    for name in RECORD_MODELS:
        entry = files.get(name)
        if not isinstance(entry, dict) or "properties" not in entry:
            result.errors.append(
                f"schema.json: no machine-readable JSON Schema (properties) for {name}"
            )
            continue
        for key in ("type", "properties"):
            if key not in entry:
                result.errors.append(f"schema.json: {name} schema lacks '{key}'")
        if "required" not in entry:
            result.warnings.append(f"schema.json: {name} schema has no 'required' list")


def _validate_input_manifest(
    input_manifest: list[dict[str, Any]],
    build_report: dict[str, Any],
    result: CuratedValidationResult,
) -> None:
    """Fingerprint semantics: upstream-only inventory, reproducible hash."""
    from dalel.curation.builder import fingerprint_from_inventory
    from dalel.curation.schemas import InputManifestEntry

    entries: list[InputManifestEntry] = []
    paths_seen: set[str] = set()
    for index, record in enumerate(input_manifest, start=1):
        context = f"input_manifest.jsonl:{index}"
        relative_path = str(record.get("relative_path") or "")
        if relative_path in paths_seen:
            result.errors.append(f"{context}: duplicate input path {relative_path}")
        paths_seen.add(relative_path)
        if relative_path in FORBIDDEN_INPUT_FILES or any(
            relative_path.startswith(prefix) for prefix in FORBIDDEN_INPUT_PREFIXES
        ):
            result.errors.append(
                f"{context}: downstream artifact in input inventory: {relative_path}"
            )
        try:
            entries.append(InputManifestEntry.model_validate(record))
        except Exception:  # already reported by model validation pass
            return

    if [e.relative_path for e in entries] != sorted(e.relative_path for e in entries):
        result.errors.append("input_manifest.jsonl: entries are not sorted by path")

    recomputed = fingerprint_from_inventory(entries)
    if recomputed != build_report.get("input_fingerprint"):
        result.errors.append(
            "input fingerprint is not reproducible from input_manifest.jsonl:"
            f" recomputed {recomputed[:12]}…,"
            f" build_report {str(build_report.get('input_fingerprint'))[:12]}…"
        )
    if build_report.get("input_files_hashed") != len(entries):
        result.errors.append(
            f"build_report.input_files_hashed={build_report.get('input_files_hashed')!r}"
            f" != inventory entries {len(entries)}"
        )
    roles: dict[str, int] = {}
    for entry in entries:
        roles[entry.input_role] = roles.get(entry.input_role, 0) + 1
    if build_report.get("input_roles") != dict(sorted(roles.items())):
        result.errors.append("build_report.input_roles disagrees with input_manifest.jsonl")


def validate_curated_dataset(dataset_dir: Path, repo_root: Path) -> CuratedValidationResult:
    result = CuratedValidationResult()

    for name in REQUIRED_FILES:
        if not (dataset_dir / name).is_file():
            result.errors.append(f"missing required file: {name}")
    for stale in dataset_dir.parent.glob(".tmp__*"):
        # A dataset being validated inside its own temporary build directory
        # must not flag itself; only OTHER leftover temp dirs are violations.
        if stale.resolve() != dataset_dir.resolve():
            result.errors.append(f"temporary directory present: {stale.name}")
    for stale in dataset_dir.rglob(".tmp__*"):
        result.errors.append(f"temporary artifact inside dataset: {stale}")

    try:
        build_report = json.loads((dataset_dir / "build_report.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        result.errors.append(f"build_report.json unreadable: {exc}")
        return result
    if build_report.get("status") != "success":
        result.errors.append(f"build_report status is {build_report.get('status')!r}")
        return result

    try:
        statistics = json.loads(
            (dataset_dir / "dataset_statistics.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        result.errors.append(f"dataset_statistics.json unreadable: {exc}")
        return result

    projects = _load_jsonl(dataset_dir / "projects.jsonl", result, "projects.jsonl")
    documents = _load_jsonl(dataset_dir / "documents.jsonl", result, "documents.jsonl")
    pages = _load_jsonl(dataset_dir / "pages.jsonl", result, "pages.jsonl")
    sections = _load_jsonl(dataset_dir / "sections.jsonl", result, "sections.jsonl")
    tables = _load_jsonl(dataset_dir / "tables.jsonl", result, "tables.jsonl")
    images = _load_jsonl(dataset_dir / "images.jsonl", result, "images.jsonl")
    weak_findings = _load_jsonl(dataset_dir / "weak_findings.jsonl", result, "weak_findings.jsonl")
    groups = _load_jsonl(dataset_dir / "document_groups.jsonl", result, "document_groups.jsonl")
    input_manifest = _load_jsonl(
        dataset_dir / "input_manifest.jsonl", result, "input_manifest.jsonl"
    )

    _validate_against_models(
        {
            "projects.jsonl": projects,
            "documents.jsonl": documents,
            "pages.jsonl": pages,
            "sections.jsonl": sections,
            "tables.jsonl": tables,
            "images.jsonl": images,
            "weak_findings.jsonl": weak_findings,
            "document_groups.jsonl": groups,
            "input_manifest.jsonl": input_manifest,
        },
        {"build_report.json": build_report, "dataset_statistics.json": statistics},
        result,
    )
    _validate_schema_completeness(dataset_dir, result)

    # Standalone contract enforcement: the DISTRIBUTED schema.json must reject
    # invalid records under a standard Draft 2020-12 validator (no Pydantic).
    from dalel.curation.schema_contract import validate_records_with_jsonschema

    result.errors.extend(validate_records_with_jsonschema(dataset_dir))

    _validate_input_manifest(input_manifest, build_report, result)

    project_ids = {str(p.get("project_id")) for p in projects}
    doc_by_id: dict[str, dict[str, Any]] = {}
    for document in documents:
        document_id = str(document.get("document_id"))
        if document_id in doc_by_id:
            result.errors.append(f"duplicate document_id: {document_id}")
        doc_by_id[document_id] = document
        if str(document.get("project_id")) not in project_ids:
            result.errors.append(f"{document_id}: unknown project_id (broken FK)")
        if document.get("role") != "model_input":
            result.errors.append(
                f"leakage: {document_id} has role {document.get('role')!r} in feature layer"
            )
        source_path = str(document.get("source_path") or "")
        if source_path and not _relative_path_is_safe(source_path):
            result.errors.append(f"{document_id}: unsafe source_path {source_path!r}")

    unique_ids: dict[str, set[str]] = {"sections": set(), "tables": set(), "images": set()}
    page_keys: set[tuple[str, int]] = set()

    def _check_records(records: list[dict[str, Any]], kind: str, id_field: str | None) -> None:
        for index, record in enumerate(records, start=1):
            context = f"{kind}:{index}"
            provenance = record.get("provenance")
            document_id = str(provenance.get("document_id")) if isinstance(provenance, dict) else ""
            document = doc_by_id.get(document_id)
            if document is None:
                result.errors.append(f"{context}: orphan record for unknown {document_id!r}")
                continue
            if isinstance(provenance, dict) and provenance.get("role") != "model_input":
                result.errors.append(f"{context}: leakage — non-model_input role in feature layer")
            result.errors.extend(
                provenance_errors(
                    record,
                    str(document.get("project_id")),
                    document_id,
                    str(document.get("source_sha256")),
                    context,
                )
            )
            record_ref = record.get("record_ref")
            if not isinstance(record_ref, dict):
                result.errors.append(f"{context}: missing record_ref")
            elif not _relative_path_is_safe(str(record_ref.get("file") or "/")):
                result.errors.append(f"{context}: unsafe record_ref.file")
            if id_field is not None:
                value = str(record.get(id_field))
                if value in unique_ids[kind]:
                    result.errors.append(f"{context}: duplicate {id_field}: {value}")
                unique_ids[kind].add(value)
            if kind == "pages":
                key = (document_id, int(record.get("page_number") or 0))
                if key in page_keys:
                    result.errors.append(f"{context}: duplicate page id {key}")
                page_keys.add(key)

    _check_records(pages, "pages", None)
    _check_records(sections, "sections", "section_id")
    _check_records(tables, "tables", "table_id")
    _check_records(images, "images", "image_id")

    for index, table in enumerate(tables, start=1):
        rows = table.get("num_rows")
        cols = table.get("num_cols")
        cells = table.get("cells")
        if (
            not isinstance(rows, int)
            or not isinstance(cols, int)
            or not isinstance(cells, list)
            or not table_content_is_valid(rows, cols, cells)
        ):
            result.errors.append(f"tables:{index}: violates table validity contract")
        elif len(cells) != rows or any(
            not isinstance(row, list) or len(row) != cols for row in cells
        ):
            result.errors.append(f"tables:{index}: dimensions inconsistent with cells grid")

    # Physical image layer: existence, uniqueness, containment, checksums,
    # exact record<->file correspondence.
    curated_paths: set[str] = set()
    physical_expected = 0
    for index, image in enumerate(images, start=1):
        context = f"images:{index}"
        curated_path = image.get("curated_image_path")
        if image.get("image_path") is None:
            if curated_path is not None:
                result.errors.append(f"{context}: curated path present for byte-less record")
            continue
        physical_expected += 1
        if not curated_path:
            result.errors.append(f"{context}: missing curated_image_path")
            continue
        curated_path = str(curated_path)
        if not _relative_path_is_safe(curated_path) or not curated_path.startswith("images/"):
            result.errors.append(f"{context}: unsafe curated_image_path {curated_path!r}")
            continue
        if curated_path in curated_paths:
            result.errors.append(f"{context}: duplicate curated_image_path {curated_path}")
        curated_paths.add(curated_path)

        physical = dataset_dir / curated_path
        try:
            physical.resolve().relative_to(dataset_dir.resolve())
        except ValueError:
            result.errors.append(f"{context}: curated image escapes dataset: {curated_path}")
            continue
        if not physical.is_file():
            result.errors.append(f"{context}: physical curated image missing: {curated_path}")
            continue
        size = physical.stat().st_size
        if size <= 0:
            result.errors.append(f"{context}: physical curated image is empty: {curated_path}")
        if image.get("image_size_bytes") != size:
            result.errors.append(f"{context}: image_size_bytes mismatch for {curated_path}")
        expected_hash = image.get("image_sha256")
        if not isinstance(expected_hash, str) or len(expected_hash) != 64:
            result.errors.append(f"{context}: image_sha256 is missing/malformed")
        elif sha256_file(physical) != expected_hash:
            result.errors.append(f"{context}: image checksum mismatch for {curated_path}")
        source_image_path = image.get("source_image_path")
        if source_image_path is not None and not _relative_path_is_safe(str(source_image_path)):
            result.errors.append(f"{context}: unsafe source_image_path")

    images_root = dataset_dir / "images"
    physical_files = (
        {p.relative_to(dataset_dir).as_posix() for p in images_root.rglob("*") if p.is_file()}
        if images_root.is_dir()
        else set()
    )
    for orphan in sorted(physical_files - curated_paths):
        result.errors.append(f"unreferenced physical image inside dataset: {orphan}")
    for missing in sorted(curated_paths - physical_files):
        result.errors.append(f"image record without physical file: {missing}")

    for index, finding in enumerate(weak_findings, start=1):
        context = f"weak_findings:{index}"
        if finding.get("expert_verified") is not False:
            result.errors.append(f"{context}: expert_verified must be false (weak labels)")
        if str(finding.get("confidence")) == "gold":
            result.errors.append(f"{context}: weak finding must not claim gold confidence")
        source_id = finding.get("source_document_id")
        if source_id is not None and str(source_id) in doc_by_id:
            result.errors.append(
                f"{context}: label source {source_id} is present in the feature layer (leakage)"
            )
        for target in finding.get("target_document_ids", []):
            if str(target) not in doc_by_id:
                result.errors.append(f"{context}: target document {target} not in feature layer")

    for index, group in enumerate(groups, start=1):
        if str(group.get("project_id")) not in project_ids:
            result.errors.append(f"document_groups:{index}: unknown project_id")
        for document_id in group.get("document_ids", []):
            if str(document_id) not in doc_by_id:
                result.errors.append(f"document_groups:{index}: unknown document_id {document_id}")

    documented = {key[0] for key in page_keys}
    for document_id in doc_by_id:
        if document_id not in documented:
            result.errors.append(f"{document_id}: document has no page records (orphan document)")

    expected = statistics.get("counts", {})
    actual_counts = {
        "projects": len(projects),
        "documents": len(documents),
        "pages": len(pages),
        "sections": len(sections),
        "tables": len(tables),
        "images": len(images),
        "physical_images": len(curated_paths),
        "weak_findings": len(weak_findings),
        "document_groups": len(groups),
    }
    for key, actual in actual_counts.items():
        if expected.get(key) != actual:
            result.errors.append(
                f"count mismatch for {key}: statistics={expected.get(key)!r}, actual={actual}"
            )
    if physical_expected != len(curated_paths):
        result.errors.append(
            f"image records with bytes ({physical_expected}) != unique curated paths"
            f" ({len(curated_paths)})"
        )

    result.errors.extend(verify_checksums(dataset_dir))
    result.counts = actual_counts
    return result

"""Curated Dataset v1 builder.

Reads ``data/processed`` strictly read-only and writes an atomic, checksummed,
self-contained, byte-deterministic dataset to ``data/curated/v1``:

- feature layer (pages/sections/tables/images) comes ONLY from model_inputs;
- all 460 image byte payloads are copied INSIDE the dataset under
  ``images/<project>/<document>/`` and pinned by SHA-256 in their records;
- the table validity contract is re-applied to EVERY serialized table in both
  processed trees; any invalid table aborts the build (exit 1) BEFORE anything
  is written — an existing dataset stays byte-for-byte untouched on failure;
- every record is validated against the production curated Pydantic models
  (the same models that generate ``schema.json``);
- the finished dataset is built in a sibling temporary directory, fully
  re-validated there (validate-curated + checksum verification) and only then
  atomically swapped into place;
- outputs are byte-idempotent: no wall-clock timestamps enter versioned
  artifacts; identity comes from ``input_fingerprint`` over all input bytes.
"""

from __future__ import annotations

import json
import logging
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from dalel.curation import CURATION_VERSION, DATASET_VERSION
from dalel.curation.checksums import verify_checksums, write_checksums
from dalel.curation.normalization import normalize_table_counters
from dalel.curation.provenance import provenance_errors
from dalel.curation.reports import (
    render_dataset_card,
    write_json,
    write_jsonl_dicts,
    write_label_schema,
    write_schema_description,
)
from dalel.curation.schemas import (
    FINGERPRINT_ALGORITHM,
    BuildReportModel,
    CuratedDocument,
    CuratedImageRecord,
    CuratedPageRecord,
    CuratedProject,
    CuratedSectionRecord,
    CuratedTableRecord,
    DatasetStatisticsModel,
    InputManifestEntry,
    WeakFindingRecord,
)
from dalel.curation.splits import build_document_groups, build_split_proposal
from dalel.ingestion.hashing import sha256_file
from dalel.ingestion.validation import load_manifest
from dalel.schemas.manifest import ManifestDocument, ManifestProject
from dalel.schemas.table import table_content_is_valid

logger = logging.getLogger(__name__)


class CuratedBuildError(Exception):
    """Blocking build failure (invalid table, broken provenance, missing input)."""


@dataclass
class BuildResult:
    status: str
    output_dir: Path
    errors: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    report_path: Path | None = None
    input_fingerprint: str | None = None


@dataclass
class _FeatureRecords:
    pages: list[dict[str, Any]] = field(default_factory=list)
    sections: list[dict[str, Any]] = field(default_factory=list)
    tables: list[dict[str, Any]] = field(default_factory=list)
    images: list[dict[str, Any]] = field(default_factory=list)
    # dataset-relative image path -> absolute source path in processed tree
    image_sources: dict[str, Path] = field(default_factory=dict)


def _read_json(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise CuratedBuildError(f"{path}: top-level JSON value must be an object")
    return loaded


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise CuratedBuildError(f"missing processed file: {path}")
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            raise CuratedBuildError(f"{path}:{line_number}: blank JSONL line")
        loaded = json.loads(line)
        if not isinstance(loaded, dict):
            raise CuratedBuildError(f"{path}:{line_number}: JSONL value must be an object")
        records.append(loaded)
    return records


def _relative(path: Path, repo_root: Path) -> str:
    return path.resolve().relative_to(repo_root.resolve()).as_posix()


def _table_contract_errors(record: dict[str, Any], context: str) -> list[str]:
    errors: list[str] = []
    num_rows = record.get("num_rows")
    num_cols = record.get("num_cols")
    cells = record.get("cells")
    if (
        not isinstance(num_rows, int)
        or not isinstance(num_cols, int)
        or not isinstance(cells, list)
    ):
        return [f"{context}: malformed table dimensions/cells"]
    if not table_content_is_valid(num_rows, num_cols, cells):
        errors.append(
            f"{context}: violates table validity contract"
            f" (rows={num_rows}, cols={num_cols}, cells={len(cells)})"
        )
    if len(cells) != num_rows:
        errors.append(f"{context}: num_rows={num_rows} but cells has {len(cells)} rows")
    for row_index, row in enumerate(cells, start=1):
        if not isinstance(row, list) or len(row) != num_cols:
            errors.append(f"{context}: row {row_index} width does not match num_cols")
            break
    return errors


@dataclass
class CurateOptions:
    input_root: Path
    output_dir: Path
    repo_root: Path
    manifest_path: Path
    annotations_root: Path
    force: bool = False


def collect_input_inventory(options: CurateOptions) -> list[InputManifestEntry]:
    """Explicit inventory of the upstream files the builder actually reads.

    Enumerated from the canonical manifest — never by directory-wide globs —
    so downstream artifacts (data/curated/**, data/results/**, the generated
    ``data/annotations/p1_review_template.jsonl``) can never leak into the
    fingerprint. Roles:

    - canonical_manifest: ``projects.jsonl`` itself;
    - source_metadata: per-project ``source_metadata.json``;
    - processed_document: the six core processed files per model input;
    - processed_image: physical image bytes per model input;
    - label_source_table_gate: label-source ``tables.jsonl`` (validity gate
      only; content never enters the dataset);
    - weak_findings: original ``*/weak_findings.json`` annotations.
    """
    entries: list[InputManifestEntry] = []

    def _add(path: Path, role: str) -> None:
        if path.is_file():
            entries.append(
                InputManifestEntry(
                    relative_path=_relative(path, options.repo_root),
                    sha256=sha256_file(path),
                    input_role=role,  # type: ignore[arg-type]
                )
            )

    _add(options.manifest_path, "canonical_manifest")
    for project in load_manifest(options.manifest_path):
        _add(options.repo_root / project.source_metadata_path, "source_metadata")
        for document in project.documents:
            if document.role == "model_input":
                document_dir = (
                    options.input_root / "model_inputs" / project.project_id / document.document_id
                )
                for name in (
                    "document.json",
                    "ingestion_report.json",
                    "pages.jsonl",
                    "sections.jsonl",
                    "tables.jsonl",
                    "images.jsonl",
                ):
                    _add(document_dir / name, "processed_document")
                images_dir = document_dir / "images"
                if images_dir.is_dir():
                    for image_file in sorted(images_dir.iterdir()):
                        if image_file.is_file():
                            _add(image_file, "processed_image")
            elif document.role == "label_source":
                _add(
                    options.input_root
                    / "label_sources"
                    / project.project_id
                    / document.document_id
                    / "tables.jsonl",
                    "label_source_table_gate",
                )
    for annotation_path in sorted(options.annotations_root.glob("*/weak_findings.json")):
        _add(annotation_path, "weak_findings")

    entries.sort(key=lambda entry: entry.relative_path)
    return entries


def fingerprint_from_inventory(entries: list[InputManifestEntry]) -> str:
    """Canonical fingerprint over the sorted inventory + build configuration
    identity (algorithm, dataset and curation versions)."""
    import hashlib

    digest = hashlib.sha256()
    digest.update(
        f"{FINGERPRINT_ALGORITHM}|dataset={DATASET_VERSION}|curation={CURATION_VERSION}\n".encode()
    )
    for entry in entries:
        digest.update(entry.relative_path.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(entry.sha256.encode("ascii"))
        digest.update(b"\x00")
        digest.update(entry.input_role.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def compute_input_fingerprint(options: CurateOptions) -> tuple[str, list[InputManifestEntry]]:
    entries = collect_input_inventory(options)
    return fingerprint_from_inventory(entries), entries


def _validate_model(
    model_cls: type[BaseModel], record: dict[str, Any], context: str, errors: list[str]
) -> dict[str, Any] | None:
    """Validate a curated record against its production model; return the
    canonical (model-ordered) dump or record the error."""
    try:
        model = model_cls.model_validate(record)
    except ValidationError as exc:
        errors.append(f"{context}: record fails {model_cls.__name__} validation: {exc}")
        return None
    return model.model_dump(mode="json")


def build_curated_dataset(options: CurateOptions) -> BuildResult:
    errors: list[str] = []

    model_inputs_root = options.input_root / "model_inputs"
    label_sources_root = options.input_root / "label_sources"
    if not model_inputs_root.is_dir():
        raise CuratedBuildError(f"missing model_inputs root: {model_inputs_root}")
    if options.output_dir.exists() and not options.force:
        raise CuratedBuildError(
            f"output already exists: {options.output_dir}; pass --force to rebuild atomically"
        )

    input_fingerprint, input_inventory = compute_input_fingerprint(options)
    input_roles: dict[str, int] = {}
    for entry in input_inventory:
        input_roles[entry.input_role] = input_roles.get(entry.input_role, 0) + 1

    manifest_projects = load_manifest(options.manifest_path)
    manifest_docs: dict[str, ManifestDocument] = {
        document.document_id: document
        for project in manifest_projects
        for document in project.documents
    }

    projects: list[CuratedProject] = []
    documents: list[CuratedDocument] = []
    features = _FeatureRecords()
    normalization_log: list[dict[str, Any]] = []
    table_validation: dict[str, Any] = {
        "checked_records": 0,
        "valid_records": 0,
        "invalid_records": [],
        "scopes": {"model_inputs": 0, "label_sources": 0},
    }

    for project in manifest_projects:
        projects.append(_build_project(project, options))
        for manifest_doc in project.documents:
            if manifest_doc.role == "label_source":
                _gate_label_source_tables(
                    label_sources_root, project, manifest_doc, table_validation
                )
                continue
            if manifest_doc.role != "model_input":
                continue
            document_dir = model_inputs_root / project.project_id / manifest_doc.document_id
            if not (document_dir / "document.json").is_file():
                errors.append(
                    f"{manifest_doc.document_id}: manifest model input has no processed output"
                )
                continue
            documents.append(
                _curate_one_document(
                    document_dir,
                    project,
                    manifest_doc,
                    features,
                    table_validation,
                    normalization_log,
                    errors,
                    options,
                )
            )

    weak_findings = _build_weak_findings(options, manifest_docs, errors)
    groups = build_document_groups(projects, documents)
    split_proposal = build_split_proposal(groups)

    invalid_tables = list(table_validation["invalid_records"])
    if invalid_tables:
        errors.append(
            f"table validity contract violated by {len(invalid_tables)} record(s); build aborted"
        )

    statistics = _build_statistics(
        projects, documents, features, weak_findings, split_proposal, table_validation
    )
    build_report = BuildReportModel(
        dataset_version=DATASET_VERSION,
        curation_version=CURATION_VERSION,
        fingerprint_algorithm=FINGERPRINT_ALGORITHM,
        input_fingerprint=input_fingerprint,
        input_files_hashed=len(input_inventory),
        input_roles=dict(sorted(input_roles.items())),
        input_root=_relative(options.input_root, options.repo_root),
        manifest=_relative(options.manifest_path, options.repo_root),
        table_validation=dict(table_validation),
        normalizations=normalization_log,
        counts=dict(statistics.counts),
        images_materialized=len(features.image_sources),
        errors=errors,
        status="failed" if errors else "success",
    )

    if errors:
        # Atomicity contract: a failed build never touches the output
        # directory (including any existing build_report.json). Errors are
        # surfaced to the caller/stderr only.
        for message in errors:
            logger.error("curate: %s", message)
        return BuildResult(
            status="failed",
            output_dir=options.output_dir,
            errors=errors,
            counts=dict(statistics.counts),
            input_fingerprint=input_fingerprint,
        )

    _write_dataset(
        options,
        projects,
        documents,
        features,
        weak_findings,
        groups,
        statistics,
        build_report,
        input_inventory,
    )
    return BuildResult(
        status="success",
        output_dir=options.output_dir,
        counts=dict(statistics.counts),
        report_path=options.output_dir / "build_report.json",
        input_fingerprint=input_fingerprint,
    )


def _build_project(project: ManifestProject, options: CurateOptions) -> CuratedProject:
    download_year: int | None = None
    metadata_path = options.repo_root / project.source_metadata_path
    if metadata_path.is_file():
        try:
            metadata = _read_json(metadata_path)
            downloaded_at = str(metadata.get("downloaded_at") or "")
            if len(downloaded_at) >= 4 and downloaded_at[:4].isdigit():
                download_year = int(downloaded_at[:4])
        except (json.JSONDecodeError, CuratedBuildError):
            download_year = None
    return CuratedProject(
        project_id=project.project_id,
        source_url=project.source_url,
        region=project.region,
        industry=project.industry,
        languages=list(project.languages),
        download_year=download_year,
        company_id=project.company_id,
        developer_id=project.developer_id,
        model_input_document_ids=sorted(
            d.document_id for d in project.documents if d.role == "model_input"
        ),
        label_source_document_ids=sorted(
            d.document_id for d in project.documents if d.role == "label_source"
        ),
    )


def _gate_label_source_tables(
    label_sources_root: Path,
    project: ManifestProject,
    manifest_doc: ManifestDocument,
    table_validation: dict[str, Any],
) -> None:
    tables_path = (
        label_sources_root / project.project_id / manifest_doc.document_id / "tables.jsonl"
    )
    if not tables_path.is_file():
        return
    for line_number, record in enumerate(_read_jsonl(tables_path), start=1):
        context = f"label_sources/{manifest_doc.document_id} tables.jsonl:{line_number}"
        table_validation["checked_records"] += 1
        table_validation["scopes"]["label_sources"] += 1
        contract_errors = _table_contract_errors(record, context)
        if contract_errors:
            table_validation["invalid_records"].extend(contract_errors)
        else:
            table_validation["valid_records"] += 1


def _safe_image_component(value: str) -> bool:
    return bool(value) and "/" not in value and "\\" not in value and ".." not in value


def _curate_one_document(
    document_dir: Path,
    project: ManifestProject,
    manifest_doc: ManifestDocument,
    features: _FeatureRecords,
    table_validation: dict[str, Any],
    normalization_log: list[dict[str, Any]],
    errors: list[str],
    options: CurateOptions,
) -> CuratedDocument:
    document_json = _read_json(document_dir / "document.json")
    report = _read_json(document_dir / "ingestion_report.json")
    repo_root = options.repo_root

    pages = _read_jsonl(document_dir / "pages.jsonl")
    sections = _read_jsonl(document_dir / "sections.jsonl")
    tables = _read_jsonl(document_dir / "tables.jsonl")
    images = _read_jsonl(document_dir / "images.jsonl")

    schema_version = str(document_json.get("schema_version") or "unknown")
    counters = normalize_table_counters(report, len(tables), schema_version)
    normalization_log.append(
        {
            "document_id": manifest_doc.document_id,
            "ingestion_schema_version": schema_version,
            "applied_normalizations": counters.applied_normalizations,
            "normalization_warnings": counters.normalization_warnings,
        }
    )

    def _base_checks(record: dict[str, Any], context: str) -> None:
        errors.extend(
            provenance_errors(
                record,
                project.project_id,
                manifest_doc.document_id,
                manifest_doc.sha256,
                context,
            )
        )

    def _ref(filename: str, line_number: int) -> dict[str, Any]:
        return {
            "file": _relative(document_dir / filename, repo_root),
            "line": line_number,
        }

    for line_number, record in enumerate(pages, start=1):
        context = f"{manifest_doc.document_id} pages.jsonl:{line_number}"
        _base_checks(record, context)
        curated = {**record, "record_ref": _ref("pages.jsonl", line_number)}
        dumped = _validate_model(CuratedPageRecord, curated, context, errors)
        if dumped is not None:
            features.pages.append(dumped)

    for line_number, record in enumerate(sections, start=1):
        context = f"{manifest_doc.document_id} sections.jsonl:{line_number}"
        _base_checks(record, context)
        curated = {**record, "record_ref": _ref("sections.jsonl", line_number)}
        dumped = _validate_model(CuratedSectionRecord, curated, context, errors)
        if dumped is not None:
            features.sections.append(dumped)

    for line_number, record in enumerate(tables, start=1):
        context = f"{manifest_doc.document_id} tables.jsonl:{line_number}"
        _base_checks(record, context)
        table_validation["checked_records"] += 1
        table_validation["scopes"]["model_inputs"] += 1
        contract_errors = _table_contract_errors(record, context)
        if contract_errors:
            table_validation["invalid_records"].extend(contract_errors)
            continue
        table_validation["valid_records"] += 1
        curated = {**record, "record_ref": _ref("tables.jsonl", line_number)}
        dumped = _validate_model(CuratedTableRecord, curated, context, errors)
        if dumped is not None:
            features.tables.append(dumped)

    for line_number, record in enumerate(images, start=1):
        context = f"{manifest_doc.document_id} images.jsonl:{line_number}"
        _base_checks(record, context)
        curated = {**record, "record_ref": _ref("images.jsonl", line_number)}

        image_path = record.get("image_path")
        if image_path is not None:
            source = document_dir / str(image_path)
            file_name = Path(str(image_path)).name
            if not source.is_file():
                errors.append(f"{context}: physical image missing: {image_path}")
            elif source.stat().st_size <= 0:
                errors.append(f"{context}: physical image is empty: {image_path}")
            elif not (
                _safe_image_component(project.project_id)
                and _safe_image_component(manifest_doc.document_id)
                and _safe_image_component(file_name)
            ):
                errors.append(f"{context}: unsafe path component for curated image copy")
            else:
                curated_rel = f"images/{project.project_id}/{manifest_doc.document_id}/{file_name}"
                curated["source_image_path"] = _relative(source, repo_root)
                curated["curated_image_path"] = curated_rel
                curated["image_sha256"] = sha256_file(source)
                curated["image_size_bytes"] = source.stat().st_size
                features.image_sources[curated_rel] = source
        else:
            curated["source_image_path"] = None
            curated["curated_image_path"] = None
            curated["image_sha256"] = None
            curated["image_size_bytes"] = None

        dumped = _validate_model(CuratedImageRecord, curated, context, errors)
        if dumped is not None:
            features.images.append(dumped)

    ocr = document_json.get("ocr")
    try:
        return CuratedDocument.model_validate(
            {
                "project_id": project.project_id,
                "document_id": manifest_doc.document_id,
                "document_type": manifest_doc.document_type,
                "role": manifest_doc.role,
                "file_format": manifest_doc.file_format,
                "languages": list(project.languages),
                "page_count": document_json.get("page_count"),
                "document_mode": document_json.get("document_mode"),
                "extraction_status": document_json.get("extraction_status"),
                "parser_name": document_json.get("parser_name"),
                "parser_version": document_json.get("parser_version"),
                "ocr": dict(ocr) if isinstance(ocr, dict) else {},
                "source_path": manifest_doc.local_path,
                "source_sha256": manifest_doc.sha256,
                "source_url": project.source_url,
                "ingestion_schema_version": schema_version,
                "normalization_version": CURATION_VERSION,
                "applied_normalizations": counters.applied_normalizations,
                "normalization_warnings": counters.normalization_warnings,
                "detected_table_items": counters.detected_table_items,
                "serialized_table_count": counters.serialized_table_count,
                "skipped_empty_table_items": counters.skipped_empty_table_items,
                "page_records": len(pages),
                "section_records": len(sections),
                "table_records": len(tables),
                "image_records": len(images),
                "ingestion_warnings": [str(w) for w in document_json.get("warnings", [])],
                "record_ref": {
                    "file": _relative(document_dir / "document.json", repo_root),
                    "line": 1,
                },
            }
        )
    except ValidationError as exc:
        detail = " | ".join(str(exc).splitlines()[:4])
        raise CuratedBuildError(
            f"{manifest_doc.document_id}: document fails the curated feature-layer"
            f" contract: {detail}"
        ) from exc


def _build_weak_findings(
    options: CurateOptions,
    manifest_docs: dict[str, ManifestDocument],
    errors: list[str],
) -> list[WeakFindingRecord]:
    path_to_doc = {doc.local_path: doc.document_id for doc in manifest_docs.values()}
    findings: list[WeakFindingRecord] = []
    for annotation_path in sorted(options.annotations_root.glob("*/weak_findings.json")):
        payload = _read_json(annotation_path)
        project_id = str(payload.get("project_id"))
        source_file = _relative(annotation_path, options.repo_root)
        for index, raw in enumerate(payload.get("findings", []), start=1):
            if not isinstance(raw, dict):
                errors.append(f"{source_file}: finding {index} is not an object")
                continue
            source_path = str(raw.get("source_document") or "")
            target_paths = [str(t) for t in raw.get("target_documents", [])]
            try:
                findings.append(
                    WeakFindingRecord.model_validate(
                        {
                            "finding_id": raw.get("finding_id"),
                            "project_id": project_id,
                            "issue_type": raw.get("issue_type"),
                            "title": raw.get("title"),
                            "description": str(raw.get("description")),
                            "severity": raw.get("severity"),
                            "source_document_id": path_to_doc.get(source_path),
                            "source_document_path": source_path,
                            "source_page": raw.get("source_page"),
                            "target_document_ids": [
                                path_to_doc[p] for p in target_paths if p in path_to_doc
                            ],
                            "target_document_paths": target_paths,
                            "evidence_text": raw.get("evidence_text"),
                            "confidence": raw.get("confidence") or "weak",
                            "expert_verified": bool(raw.get("expert_verified", False)),
                            "review_status": payload.get("review_status") or "not_expert_verified",
                            "record_ref": {"file": source_file, "line": index},
                        }
                    )
                )
            except ValidationError as exc:
                errors.append(
                    f"{source_file}: finding {index} fails the weak-finding contract:"
                    f" {str(exc).splitlines()[0]}"
                )
    return findings


def _build_statistics(
    projects: list[CuratedProject],
    documents: list[CuratedDocument],
    features: _FeatureRecords,
    weak_findings: list[WeakFindingRecord],
    split_proposal: dict[str, Any],
    table_validation: dict[str, Any],
) -> DatasetStatisticsModel:
    def _count_by(key: str) -> dict[str, int]:
        result: dict[str, int] = {}
        for document in documents:
            value = str(getattr(document, key))
            result[value] = result.get(value, 0) + 1
        return dict(sorted(result.items()))

    per_project: dict[str, dict[str, int]] = {}
    for project in projects:
        per_project[project.project_id] = {
            "documents": 0,
            "pages": 0,
            "sections": 0,
            "tables": 0,
            "images": 0,
        }
    for document in documents:
        stats = per_project[document.project_id]
        stats["documents"] += 1
        stats["pages"] += document.page_records
        stats["sections"] += document.section_records
        stats["tables"] += document.table_records
        stats["images"] += document.image_records

    def _ocr_pages(document: CuratedDocument) -> int:
        value = document.ocr.get("ocr_page_count")
        return value if isinstance(value, int) else 0

    counts = {
        "projects": len(projects),
        "documents": len(documents),
        "pages": len(features.pages),
        "sections": len(features.sections),
        "tables": len(features.tables),
        "images": len(features.images),
        "physical_images": len(features.image_sources),
        "weak_findings": len(weak_findings),
        "document_groups": len(projects),
        "ocr_pages": sum(_ocr_pages(d) for d in documents),
        "skipped_empty_table_items": sum(d.skipped_empty_table_items for d in documents),
    }
    return DatasetStatisticsModel(
        dataset_version=DATASET_VERSION,
        curation_version=CURATION_VERSION,
        counts=counts,
        by_document_type=_count_by("document_type"),
        by_extraction_status=_count_by("extraction_status"),
        by_ingestion_schema=_count_by("ingestion_schema_version"),
        by_document_mode=_count_by("document_mode"),
        per_project=dict(sorted(per_project.items())),
        languages=sorted({lang for p in projects for lang in p.languages}),
        regions=sorted({str(p.region) for p in projects}),
        industries=sorted({str(p.industry) for p in projects}),
        table_validation={
            "checked_records": int(table_validation["checked_records"]),
            "valid_records": int(table_validation["valid_records"]),
            "invalid_records": len(table_validation["invalid_records"]),
        },
        split_proposal=split_proposal,
    )


def _write_dataset(
    options: CurateOptions,
    projects: list[CuratedProject],
    documents: list[CuratedDocument],
    features: _FeatureRecords,
    weak_findings: list[WeakFindingRecord],
    groups: list[Any],
    statistics: DatasetStatisticsModel,
    build_report: BuildReportModel,
    input_inventory: list[InputManifestEntry],
) -> None:
    from dalel.curation.validation import validate_curated_dataset

    output_dir = options.output_dir
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = output_dir.parent / f".tmp__{output_dir.name}__{uuid.uuid4().hex[:8]}"
    trash_dir = output_dir.parent / f".old__{output_dir.name}__{uuid.uuid4().hex[:8]}"
    for stale in output_dir.parent.glob(f".tmp__{output_dir.name}__*"):
        shutil.rmtree(stale, ignore_errors=True)

    try:
        tmp_dir.mkdir(parents=True)
        write_jsonl_dicts(tmp_dir / "projects.jsonl", [p.model_dump(mode="json") for p in projects])
        write_jsonl_dicts(
            tmp_dir / "documents.jsonl", [d.model_dump(mode="json") for d in documents]
        )
        write_jsonl_dicts(tmp_dir / "pages.jsonl", features.pages)
        write_jsonl_dicts(tmp_dir / "sections.jsonl", features.sections)
        write_jsonl_dicts(tmp_dir / "tables.jsonl", features.tables)
        write_jsonl_dicts(tmp_dir / "images.jsonl", features.images)
        write_jsonl_dicts(
            tmp_dir / "weak_findings.jsonl", [w.model_dump(mode="json") for w in weak_findings]
        )
        write_jsonl_dicts(
            tmp_dir / "document_groups.jsonl", [g.model_dump(mode="json") for g in groups]
        )
        write_json(tmp_dir / "dataset_statistics.json", statistics.model_dump(mode="json"))
        write_schema_description(tmp_dir / "schema.json")
        write_label_schema(tmp_dir / "label_schema.json")
        (tmp_dir / "dataset_card.md").write_text(
            render_dataset_card(
                statistics.model_dump(mode="json"), build_report.model_dump(mode="json")
            ),
            encoding="utf-8",
        )
        write_json(tmp_dir / "build_report.json", build_report.model_dump(mode="json"))
        write_jsonl_dicts(
            tmp_dir / "input_manifest.jsonl",
            [entry.model_dump(mode="json") for entry in input_inventory],
        )

        # Deterministic image materialization: sorted by curated relative path.
        for curated_rel in sorted(features.image_sources):
            source = features.image_sources[curated_rel]
            target = tmp_dir / curated_rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)

        write_checksums(tmp_dir)

        # Full re-validation of the finished temporary dataset BEFORE swap:
        # record models, counts, FKs, leakage, images, checksums.
        validation = validate_curated_dataset(tmp_dir, options.repo_root)
        if not validation.ok:
            raise CuratedBuildError(
                "temporary dataset failed validation before swap: "
                + "; ".join(validation.errors[:10])
            )
        checksum_errors = verify_checksums(tmp_dir)
        if checksum_errors:
            raise CuratedBuildError(
                "temporary dataset failed checksum re-verification: "
                + "; ".join(checksum_errors[:10])
            )

        if output_dir.exists():
            output_dir.rename(trash_dir)
        tmp_dir.rename(output_dir)
    except Exception:
        if trash_dir.exists() and not output_dir.exists():
            trash_dir.rename(output_dir)
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
    if trash_dir.exists():
        shutil.rmtree(trash_dir, ignore_errors=True)

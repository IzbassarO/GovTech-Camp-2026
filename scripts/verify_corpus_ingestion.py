#!/usr/bin/env python3
"""Independently verify Phase 0 corpus ingestion outputs without modifying them."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "manifests" / "projects.jsonl"
PROCESSED = ROOT / "data" / "processed"

SCOPES = {
    "model_inputs": PROCESSED / "model_inputs",
    "label_sources": PROCESSED / "label_sources",
}
MANDATORY_FILES = {
    "document.json",
    "pages.jsonl",
    "sections.jsonl",
    "tables.jsonl",
    "images.jsonl",
    "ingestion_report.json",
}
JSONL_FILES = {
    "pages": "pages.jsonl",
    "sections": "sections.jsonl",
    "tables": "tables.jsonl",
    "images": "images.jsonl",
}
EXPECTED_MODEL_INPUTS = {
    "project_001_bereke": 5,
    "project_002_azm": 5,
    "project_003_bayterek": 2,
    "project_004_sintez_ural": 7,
}
EXPECTED_COUNTS = {
    "model_inputs": 19,
    "label_sources": 4,
    "auxiliary_archives": 1,
    "reports": 23,
    "pages": 1075,
    "tables": 686,
    "images": 481,
    "physical_images": 481,
    "ocr_pages": 98,
}
EXPECTED_PARSER = ("docling", "2.112.0")
EXPECTED_STATUSES = {
    "success": 18,
    "partial": 5,
    "failed": 0,
    "skipped_cached": 0,
    "skipped": 0,
}
PARTIAL_PAGE_PATTERN = re.compile(r"pages without text after OCR policy: \[([0-9, ]+)\]")


@dataclass(frozen=True)
class ManifestDocument:
    """One document record from the canonical project manifest."""

    project_id: str
    source_url: str | None
    data: dict[str, Any]

    @property
    def document_id(self) -> str:
        return str(self.data.get("document_id", ""))

    @property
    def expected_scope(self) -> str | None:
        role = self.data.get("role")
        if (
            role == "model_input"
            and self.data.get("use_as_model_feature") is True
            and self.data.get("label_timing") == "pre_review"
        ):
            return "model_inputs"
        if (
            role == "label_source"
            and self.data.get("use_as_model_feature") is False
            and self.data.get("label_timing") == "post_review"
        ):
            return "label_sources"
        if role == "auxiliary_archive":
            return None
        return "invalid"


class CorpusVerifier:
    """Read-only verifier for the manifest-to-processed evidence chain."""

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.json_errors: list[str] = []
        self.missing_files: list[str] = []
        self.empty_files: list[str] = []
        self.orphan_outputs: list[str] = []
        self.temp_directories: list[str] = []
        self.unexpected_files: list[str] = []
        self.leakage_violations: list[str] = []
        self.hash_violations: list[str] = []
        self.provenance_violations: list[str] = []
        self.invalid_tables: list[str] = []
        self.partial_details: list[dict[str, Any]] = []
        self.short_ocr_pages: list[str] = []
        self.pages_without_embedded_text: list[str] = []
        self.ocr_documents: list[str] = []
        self.parser_distribution: Counter[str] = Counter()
        self.statuses: Counter[str] = Counter()
        self.totals: Counter[str] = Counter()
        self.artifact_counts: Counter[str] = Counter()
        self.per_project: dict[str, Counter[str]] = defaultdict(Counter)
        self.manifest_documents: dict[str, ManifestDocument] = {}
        self.output_locations: dict[str, list[tuple[str, Path]]] = defaultdict(list)
        self.raw_hashes: dict[Path, str] = {}
        self.logical_ids: dict[str, set[str]] = {
            "sections": set(),
            "tables": set(),
            "images": set(),
        }

    @staticmethod
    def relative(path: Path) -> str:
        try:
            return path.relative_to(ROOT).as_posix()
        except ValueError:
            return str(path)

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warning(self, message: str) -> None:
        self.warnings.append(message)

    def load_json(self, path: Path, context: str) -> dict[str, Any] | None:
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            self.missing_files.append(self.relative(path))
            self.error(f"{context}: missing file: {self.relative(path)}")
            return None
        except UnicodeDecodeError as exc:
            message = f"{context}: invalid UTF-8: {exc}"
            self.json_errors.append(message)
            self.error(message)
            return None

        if not text:
            self.empty_files.append(self.relative(path))
            self.error(f"{context}: empty JSON file")
            return None
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            message = f"{context}: invalid JSON: {exc}"
            self.json_errors.append(message)
            self.error(message)
            return None
        if not isinstance(value, dict):
            message = f"{context}: top-level JSON value must be an object"
            self.json_errors.append(message)
            self.error(message)
            return None
        return value

    def load_jsonl(self, path: Path, context: str) -> list[dict[str, Any]]:
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            self.missing_files.append(self.relative(path))
            self.error(f"{context}: missing file: {self.relative(path)}")
            return []
        except UnicodeDecodeError as exc:
            message = f"{context}: invalid UTF-8: {exc}"
            self.json_errors.append(message)
            self.error(message)
            return []

        if not text:
            self.empty_files.append(self.relative(path))
            return []

        records: list[dict[str, Any]] = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                message = f"{context}:{line_number}: blank JSONL line"
                self.json_errors.append(message)
                self.error(message)
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                message = f"{context}:{line_number}: invalid JSON: {exc}"
                self.json_errors.append(message)
                self.error(message)
                continue
            if not isinstance(value, dict):
                message = f"{context}:{line_number}: JSONL value must be an object"
                self.json_errors.append(message)
                self.error(message)
                continue
            records.append(value)
        return records

    def sha256(self, path: Path) -> str:
        cached = self.raw_hashes.get(path)
        if cached is not None:
            return cached
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        value = digest.hexdigest()
        self.raw_hashes[path] = value
        return value

    def resolve_repo_path(self, value: Any, context: str) -> Path | None:
        if not isinstance(value, str) or not value:
            self.error(f"{context}: expected a non-empty relative path")
            return None
        candidate = Path(value)
        if candidate.is_absolute():
            self.error(f"{context}: absolute path is forbidden: {value}")
            return None
        resolved = (ROOT / candidate).resolve()
        try:
            resolved.relative_to(ROOT)
        except ValueError:
            self.error(f"{context}: path escapes repository: {value}")
            return None
        return resolved

    def read_manifest(self) -> None:
        projects = self.load_jsonl(MANIFEST, "canonical manifest")
        for project_index, project in enumerate(projects, start=1):
            project_id = project.get("project_id")
            if not isinstance(project_id, str) or not project_id:
                self.error(f"manifest project {project_index}: invalid project_id")
                continue
            source_url = project.get("source_url")
            documents = project.get("documents")
            if not isinstance(documents, list):
                self.error(f"manifest project {project_id}: documents is not a list")
                continue
            for document_index, data in enumerate(documents, start=1):
                if not isinstance(data, dict):
                    self.error(f"manifest {project_id} document {document_index}: not an object")
                    continue
                document = ManifestDocument(project_id, source_url, data)
                if not document.document_id:
                    self.error(
                        f"manifest {project_id} document {document_index}: missing document_id"
                    )
                    continue
                if document.document_id in self.manifest_documents:
                    self.error(f"manifest: duplicate document_id {document.document_id}")
                    continue
                self.manifest_documents[document.document_id] = document
                if document.expected_scope == "invalid":
                    self.error(
                        f"manifest {document.document_id}: invalid role/feature/timing routing"
                    )

        scope_counts = Counter(
            document.expected_scope for document in self.manifest_documents.values()
        )
        archive_count = sum(
            document.data.get("role") == "auxiliary_archive"
            for document in self.manifest_documents.values()
        )
        if scope_counts["model_inputs"] != EXPECTED_COUNTS["model_inputs"]:
            self.error(
                "manifest model-input count: "
                f"expected {EXPECTED_COUNTS['model_inputs']}, "
                f"found {scope_counts['model_inputs']}"
            )
        if scope_counts["label_sources"] != EXPECTED_COUNTS["label_sources"]:
            self.error(
                "manifest label-source count: "
                f"expected {EXPECTED_COUNTS['label_sources']}, "
                f"found {scope_counts['label_sources']}"
            )
        if archive_count != EXPECTED_COUNTS["auxiliary_archives"]:
            self.error(
                "manifest auxiliary-archive count: "
                f"expected {EXPECTED_COUNTS['auxiliary_archives']}, found {archive_count}"
            )

    def find_outputs(self) -> None:
        for path in sorted(PROCESSED.rglob("*")):
            if path.is_dir() and (
                path.name.startswith(".tmp__")
                or path.name.startswith(".old__")
                or ".tmp__" in path.name
                or ".old__" in path.name
            ):
                self.temp_directories.append(self.relative(path))
                self.error(f"temporary/atomic-write residue: {self.relative(path)}")

        for scope, scope_root in SCOPES.items():
            if not scope_root.is_dir():
                self.error(f"missing processed scope: {self.relative(scope_root)}")
                continue
            for project_entry in sorted(scope_root.iterdir()):
                if not project_entry.is_dir():
                    self.unexpected_files.append(self.relative(project_entry))
                    self.error(f"unexpected file at scope root: {self.relative(project_entry)}")
                    continue
                for entry in sorted(project_entry.iterdir()):
                    if entry.name == "project.json" and entry.is_file():
                        continue
                    if not entry.is_dir():
                        self.unexpected_files.append(self.relative(entry))
                        self.error(f"unexpected project-level file: {self.relative(entry)}")
                        continue
                    self.output_locations[entry.name].append((scope, entry))

        for document_id, locations in sorted(self.output_locations.items()):
            if len(locations) > 1:
                values = ", ".join(self.relative(path) for _, path in locations)
                self.error(f"duplicate document directories for {document_id}: {values}")
            manifest_document = self.manifest_documents.get(document_id)
            if manifest_document is None:
                for _, path in locations:
                    value = self.relative(path)
                    self.orphan_outputs.append(value)
                    self.error(f"orphan output absent from manifest: {value}")
                continue
            for scope, _path in locations:
                if manifest_document.expected_scope != scope:
                    message = (
                        f"{document_id}: output in {scope}, expected "
                        f"{manifest_document.expected_scope}"
                    )
                    self.leakage_violations.append(message)
                    self.error(message)

        for document in self.manifest_documents.values():
            locations = self.output_locations.get(document.document_id, [])
            if document.expected_scope in SCOPES and not locations:
                expected = (
                    SCOPES[str(document.expected_scope)]
                    / document.project_id
                    / document.document_id
                )
                value = self.relative(expected)
                self.missing_files.append(value)
                self.error(f"manifest document has no output: {value}")
            if document.expected_scope is None and locations:
                message = f"auxiliary archive was parsed: {document.document_id}"
                self.leakage_violations.append(message)
                self.error(message)

    def validate_provenance(
        self,
        record: dict[str, Any],
        document: ManifestDocument,
        document_json: dict[str, Any],
        context: str,
        expected_page: int | None,
        expected_ocr: bool | None = None,
    ) -> None:
        provenance = record.get("provenance")
        if not isinstance(provenance, dict):
            message = f"{context}: missing provenance object"
            self.provenance_violations.append(message)
            self.error(message)
            return

        expected = {
            "project_id": document.project_id,
            "document_id": document.document_id,
            "document_type": document.data.get("document_type"),
            "role": document.data.get("role"),
            "source_path": document.data.get("local_path"),
            "source_sha256": document.data.get("sha256"),
            "parser_name": document_json.get("parser_name"),
            "parser_version": document_json.get("parser_version"),
        }
        for field, value in expected.items():
            if provenance.get(field) != value:
                message = (
                    f"{context}: provenance.{field}={provenance.get(field)!r}, expected {value!r}"
                )
                self.provenance_violations.append(message)
                self.error(message)
        ocr_used = provenance.get("ocr_used")
        if not isinstance(ocr_used, bool):
            message = f"{context}: provenance.ocr_used must be boolean"
            self.provenance_violations.append(message)
            self.error(message)
        elif expected_ocr is not None and ocr_used is not expected_ocr:
            message = f"{context}: provenance.ocr_used={ocr_used!r}, expected {expected_ocr!r}"
            self.provenance_violations.append(message)
            self.error(message)

        parser_name = document_json.get("parser_name")
        expected_method = f"{parser_name}_ocr" if ocr_used is True else parser_name
        if provenance.get("extraction_method") != expected_method:
            message = (
                f"{context}: extraction_method={provenance.get('extraction_method')!r} "
                f"does not match expected method {expected_method!r}"
            )
            self.provenance_violations.append(message)
            self.error(message)

        actual_page = provenance.get("page_number")
        is_docx_flow = document_json.get("document_mode") == "docx_flow"
        if expected_page is None:
            if actual_page is not None:
                message = f"{context}: page_number must be null when unavailable"
                self.provenance_violations.append(message)
                self.error(message)
        elif is_docx_flow:
            if actual_page is not None:
                message = f"{context}: DOCX provenance page_number must be null"
                self.provenance_violations.append(message)
                self.error(message)
        elif actual_page != expected_page:
            message = f"{context}: provenance.page_number={actual_page!r}, expected {expected_page}"
            self.provenance_violations.append(message)
            self.error(message)

    def validate_pages(
        self,
        pages: list[dict[str, Any]],
        document: ManifestDocument,
        document_json: dict[str, Any],
        report: dict[str, Any],
    ) -> None:
        document_id = document.document_id
        page_numbers: list[int] = []
        ocr_record_pages: list[int] = []
        page_by_number: dict[int, dict[str, Any]] = {}
        for index, page in enumerate(pages, start=1):
            context = f"{document_id} pages.jsonl record {index}"
            number = page.get("page_number")
            if not isinstance(number, int) or isinstance(number, bool) or number < 1:
                self.error(f"{context}: invalid page_number {number!r}")
                expected_page = None
            else:
                expected_page = number
                page_numbers.append(number)
                page_by_number[number] = page
            expected_ocr = page.get("ocr_applied")
            self.validate_provenance(
                page,
                document,
                document_json,
                context,
                expected_page,
                expected_ocr if isinstance(expected_ocr, bool) else None,
            )
            text = page.get("text")
            char_count = page.get("char_count")
            if not isinstance(text, str):
                self.error(f"{context}: text must be a string")
            elif char_count != len(text.strip()):
                self.error(
                    f"{context}: char_count={char_count!r}, "
                    f"actual stripped length={len(text.strip())}"
                )
            if not isinstance(page.get("has_embedded_text"), bool):
                self.error(f"{context}: has_embedded_text must be boolean")
            if not isinstance(page.get("ocr_applied"), bool):
                self.error(f"{context}: ocr_applied must be boolean")
            elif page["ocr_applied"] and isinstance(number, int):
                ocr_record_pages.append(number)
            if page.get("has_embedded_text") is False and isinstance(number, int):
                self.pages_without_embedded_text.append(f"{document_id} page {number}")
            if document_json.get("document_mode") == "docx_flow":
                if page.get("width") is not None or page.get("height") is not None:
                    self.error(f"{context}: DOCX pseudo-page geometry must be null")
            elif page.get("width") is None or page.get("height") is None:
                self.error(f"{context}: PDF page geometry is missing")

        expected_sequence = list(range(1, len(pages) + 1))
        if page_numbers != expected_sequence:
            self.error(
                f"{document_id}: page sequence is {page_numbers}, expected {expected_sequence}"
            )

        ocr = document_json.get("ocr")
        if not isinstance(ocr, dict):
            self.error(f"{document_id}: document.ocr must be an object")
            return
        ocr_pages = ocr.get("ocr_pages")
        candidate_pages = ocr.get("candidate_pages")
        if not isinstance(ocr_pages, list) or not all(
            isinstance(value, int) and not isinstance(value, bool) for value in ocr_pages
        ):
            self.error(f"{document_id}: ocr.ocr_pages must be a list of integers")
            ocr_pages = []
        if not isinstance(candidate_pages, list) or not all(
            isinstance(value, int) and not isinstance(value, bool) for value in candidate_pages
        ):
            self.error(f"{document_id}: ocr.candidate_pages must be a list of integers")
            candidate_pages = []
        if sorted(ocr_pages) != sorted(ocr_record_pages):
            self.error(
                f"{document_id}: OCR metadata pages {ocr_pages} do not match "
                f"page records {ocr_record_pages}"
            )
        if ocr.get("ocr_page_count") != len(ocr_pages):
            self.error(f"{document_id}: ocr_page_count does not match ocr_pages")
        if report.get("ocr_pages") != len(ocr_pages):
            self.error(f"{document_id}: report ocr_pages does not match document OCR")
        if not set(ocr_pages).issubset(set(candidate_pages)):
            self.error(f"{document_id}: OCR pages are not a subset of candidate pages")
        if any(number not in page_by_number for number in candidate_pages):
            self.error(f"{document_id}: candidate OCR page does not exist")
        for number in candidate_pages:
            page = page_by_number.get(number)
            if page is None:
                continue
            char_count = page.get("char_count")
            if isinstance(char_count, int) and char_count < 32:
                self.short_ocr_pages.append(f"{document_id} page {number}: {char_count} characters")

        engine_ran = ocr.get("engine_ran")
        if not isinstance(engine_ran, bool):
            self.error(f"{document_id}: ocr.engine_ran must be boolean")
        elif engine_ran:
            self.ocr_documents.append(document_id)
            if ocr.get("engine") != "easyocr" or ocr.get("engine_version") != "1.7.2":
                self.error(
                    f"{document_id}: unexpected OCR engine/version: "
                    f"{ocr.get('engine')} {ocr.get('engine_version')}"
                )
            if ocr.get("engine_available") is not True:
                self.error(f"{document_id}: engine_ran=true but engine_available!=true")
        else:
            if ocr_pages:
                self.error(f"{document_id}: OCR pages claimed while engine_ran=false")
            if ocr.get("engine") is not None or ocr.get("engine_version") is not None:
                self.error(f"{document_id}: OCR engine/version claimed while engine_ran=false")

        if document_json.get("extraction_status") == "partial":
            missing_pages: list[int] = []
            for warning in document_json.get("warnings", []):
                if not isinstance(warning, str):
                    continue
                match = PARTIAL_PAGE_PATTERN.fullmatch(warning)
                if match:
                    missing_pages.extend(int(value.strip()) for value in match.group(1).split(","))
            if not missing_pages:
                self.error(f"{document_id}: partial status has no explained page list")
            for number in missing_pages:
                page = page_by_number.get(number)
                if page is None:
                    self.error(f"{document_id}: partial warning names missing page {number}")
                    continue
                char_count = page.get("char_count")
                if not isinstance(char_count, int) or char_count >= 32:
                    self.error(
                        f"{document_id}: partial page {number} has "
                        f"unexpected char_count={char_count!r}"
                    )
                if number not in candidate_pages:
                    self.error(f"{document_id}: partial page {number} was not an OCR candidate")
            self.partial_details.append(
                {
                    "document_id": document_id,
                    "pages": missing_pages,
                    "warnings": document_json.get("warnings", []),
                    "ocr_engine": ocr.get("engine"),
                    "engine_ran": engine_ran,
                    "candidate_pages": candidate_pages,
                    "ocr_pages": ocr_pages,
                    "page_char_counts": {
                        number: page_by_number[number].get("char_count")
                        for number in missing_pages
                        if number in page_by_number
                    },
                }
            )

    def validate_sections(
        self,
        sections: list[dict[str, Any]],
        document: ManifestDocument,
        document_json: dict[str, Any],
    ) -> None:
        for index, section in enumerate(sections, start=1):
            context = f"{document.document_id} sections.jsonl record {index}"
            section_id = section.get("section_id")
            if not isinstance(section_id, str) or not section_id:
                self.error(f"{context}: missing section_id")
            elif section_id in self.logical_ids["sections"]:
                self.error(f"duplicate section_id: {section_id}")
            else:
                self.logical_ids["sections"].add(section_id)
            text = section.get("text")
            if not isinstance(text, str):
                self.error(f"{context}: text must be a string")
            elif section.get("char_count") != len(text):
                self.error(f"{context}: char_count does not match text")
            page_start = section.get("page_start")
            page_end = section.get("page_end")
            if document_json.get("document_mode") == "docx_flow":
                if page_start is not None or page_end is not None:
                    self.error(f"{context}: DOCX section page range must be null")
                expected_page = None
            else:
                if not isinstance(page_start, int) or not isinstance(page_end, int):
                    self.error(f"{context}: PDF section page range must be integers")
                    expected_page = None
                else:
                    expected_page = page_start
                    if page_start < 1 or page_end < page_start:
                        self.error(f"{context}: invalid page range")
            self.validate_provenance(section, document, document_json, context, expected_page)

    def validate_tables(
        self,
        tables: list[dict[str, Any]],
        document: ManifestDocument,
        document_json: dict[str, Any],
    ) -> None:
        for index, table in enumerate(tables, start=1):
            context = f"{document.document_id} tables.jsonl record {index}"
            table_id = table.get("table_id")
            if not isinstance(table_id, str) or not table_id:
                self.error(f"{context}: missing table_id")
            elif table_id in self.logical_ids["tables"]:
                self.error(f"duplicate table_id: {table_id}")
            else:
                self.logical_ids["tables"].add(table_id)

            page_number = table.get("page_number")
            if document_json.get("document_mode") == "docx_flow":
                if page_number is not None:
                    self.error(f"{context}: DOCX table page_number must be null")
                expected_page = None
            elif not isinstance(page_number, int) or page_number < 1:
                self.error(f"{context}: invalid page_number {page_number!r}")
                expected_page = None
            else:
                expected_page = page_number
            self.validate_provenance(table, document, document_json, context, expected_page)

            rows = table.get("num_rows")
            columns = table.get("num_cols")
            cells = table.get("cells")
            warnings = table.get("warnings")
            if not isinstance(rows, int) or isinstance(rows, bool) or rows < 0:
                self.error(f"{context}: invalid num_rows {rows!r}")
                continue
            if not isinstance(columns, int) or isinstance(columns, bool) or columns < 0:
                self.error(f"{context}: invalid num_cols {columns!r}")
                continue
            if not isinstance(cells, list):
                self.error(f"{context}: cells must be a list")
                continue
            if len(cells) != rows:
                self.error(f"{context}: num_rows={rows}, but cells has {len(cells)} rows")
            cell_values: list[str] = []
            for row_index, row in enumerate(cells, start=1):
                if not isinstance(row, list):
                    self.error(f"{context}: row {row_index} is not a list")
                    continue
                if len(row) != columns:
                    self.error(
                        f"{context}: row {row_index} has {len(row)} cells, expected {columns}"
                    )
                cell_values.extend(str(value) for value in row if value is not None)
            content = "".join(cell_values).strip()
            has_warning = isinstance(warnings, list) and bool(warnings)
            if (rows == 0 or columns == 0 or not content) and not has_warning:
                message = (
                    f"{table_id or context}: empty table record has no explicit warning "
                    f"(page={page_number}, rows={rows}, cols={columns})"
                )
                self.invalid_tables.append(message)
                self.error(message)
            provenance = table.get("provenance")
            if not isinstance(provenance, dict) or (
                provenance.get("bbox") is not None and not isinstance(provenance.get("bbox"), dict)
            ):
                self.error(f"{context}: bbox must be an object or null")

    def safe_image_path(self, value: Any) -> bool:
        if not isinstance(value, str) or not value:
            return False
        path = PurePosixPath(value)
        return (
            not path.is_absolute()
            and ".." not in path.parts
            and len(path.parts) == 2
            and path.parts[0] == "images"
        )

    def validate_images(
        self,
        images: list[dict[str, Any]],
        document: ManifestDocument,
        document_json: dict[str, Any],
        directory: Path,
    ) -> None:
        referenced: set[Path] = set()
        for index, record in enumerate(images, start=1):
            context = f"{document.document_id} images.jsonl record {index}"
            image_id = record.get("image_id")
            if not isinstance(image_id, str) or not image_id:
                self.error(f"{context}: missing image_id")
            elif image_id in self.logical_ids["images"]:
                self.error(f"duplicate image_id: {image_id}")
            else:
                self.logical_ids["images"].add(image_id)

            page_number = record.get("page_number")
            if document_json.get("document_mode") == "docx_flow":
                if page_number is not None:
                    self.error(f"{context}: DOCX image page_number must be null")
                expected_page = None
            elif not isinstance(page_number, int) or page_number < 1:
                self.error(f"{context}: invalid page_number {page_number!r}")
                expected_page = None
            else:
                expected_page = page_number
            self.validate_provenance(record, document, document_json, context, expected_page)

            image_path = record.get("image_path")
            if not self.safe_image_path(image_path):
                self.error(f"{context}: unsafe image_path {image_path!r}")
                continue
            physical = directory / str(image_path)
            try:
                physical.resolve().relative_to(directory.resolve())
            except ValueError:
                self.error(f"{context}: image path traversal: {image_path}")
                continue
            referenced.add(physical)
            if not physical.is_file():
                self.error(f"{context}: physical image is missing: {self.relative(physical)}")
            elif physical.stat().st_size <= 0:
                self.error(f"{context}: physical image is empty: {self.relative(physical)}")
            provenance = record.get("provenance")
            bbox = provenance.get("bbox") if isinstance(provenance, dict) else None
            if bbox is not None and not isinstance(bbox, dict):
                self.error(f"{context}: bbox must be an object or null")
            if bbox is None and not record.get("warnings"):
                self.error(f"{context}: null bbox is not explained by a warning")

        images_directory = directory / "images"
        if not images_directory.is_dir():
            self.error(f"{document.document_id}: missing images directory")
            physical_images: set[Path] = set()
        else:
            physical_images = {path for path in images_directory.iterdir() if path.is_file()}
            unexpected_directories = [path for path in images_directory.iterdir() if path.is_dir()]
            for path in unexpected_directories:
                self.error(
                    f"{document.document_id}: unexpected directory under images: "
                    f"{self.relative(path)}"
                )
        for path in sorted(physical_images - referenced):
            self.unexpected_files.append(self.relative(path))
            self.error(f"unreferenced physical image: {self.relative(path)}")
        for path in sorted(referenced - physical_images):
            self.error(f"image record has no physical file: {self.relative(path)}")
        self.totals["physical_images"] += len(physical_images)

    def validate_document_directory(
        self, document: ManifestDocument, scope: str, directory: Path
    ) -> None:
        expected_directory = SCOPES[scope] / document.project_id / document.document_id
        if directory.resolve() != expected_directory.resolve():
            self.error(
                f"{document.document_id}: directory project mismatch: {self.relative(directory)}"
            )

        entries = {entry.name: entry for entry in directory.iterdir()}
        for name in sorted(MANDATORY_FILES):
            path = entries.get(name)
            if path is None or not path.is_file():
                expected = directory / name
                self.missing_files.append(self.relative(expected))
                self.error(f"{document.document_id}: missing mandatory file {name}")
            else:
                self.artifact_counts[name] += 1
        allowed_entries = MANDATORY_FILES | {"images"}
        for name, path in sorted(entries.items()):
            if name not in allowed_entries:
                self.unexpected_files.append(self.relative(path))
                self.error(f"{document.document_id}: unexpected output {name}")

        document_json = self.load_json(
            directory / "document.json", f"{document.document_id} document.json"
        )
        report = self.load_json(
            directory / "ingestion_report.json",
            f"{document.document_id} ingestion_report.json",
        )
        records = {
            kind: self.load_jsonl(
                directory / filename,
                f"{document.document_id} {filename}",
            )
            for kind, filename in JSONL_FILES.items()
        }
        if document_json is None or report is None:
            return

        expected_document_fields = {
            "project_id": document.project_id,
            "document_id": document.document_id,
            "document_type": document.data.get("document_type"),
            "role": document.data.get("role"),
            "use_as_model_feature": document.data.get("use_as_model_feature"),
            "label_timing": document.data.get("label_timing"),
            "source_path": document.data.get("local_path"),
            "source_sha256": document.data.get("sha256"),
            "original_filename": document.data.get("original_filename"),
            "file_format": document.data.get("file_format"),
            "source_url": document.source_url,
        }
        for field, expected in expected_document_fields.items():
            if document_json.get(field) != expected:
                self.error(
                    f"{document.document_id}: document.{field}="
                    f"{document_json.get(field)!r}, expected {expected!r}"
                )
        for field in ("project_id", "document_id"):
            expected = expected_document_fields[field]
            if report.get(field) != expected:
                self.error(
                    f"{document.document_id}: report.{field}={report.get(field)!r}, "
                    f"expected {expected!r}"
                )

        source_path = self.resolve_repo_path(
            document.data.get("local_path"), f"{document.document_id} source_path"
        )
        expected_hash = document.data.get("sha256")
        if source_path is None or not source_path.is_file():
            self.error(f"{document.document_id}: source file does not exist")
        elif not isinstance(expected_hash, str):
            self.error(f"{document.document_id}: manifest SHA-256 is invalid")
        else:
            actual_hash = self.sha256(source_path)
            hash_values = {
                "actual raw": actual_hash,
                "document source_sha256": document_json.get("source_sha256"),
                "report raw_hash_before": report.get("raw_hash_before"),
                "report raw_hash_after": report.get("raw_hash_after"),
            }
            for label, value in hash_values.items():
                if value != expected_hash:
                    message = (
                        f"{document.document_id}: {label}={value!r}, manifest={expected_hash!r}"
                    )
                    self.hash_violations.append(message)
                    self.error(message)
            if report.get("hash_unchanged") is not True:
                message = f"{document.document_id}: hash_unchanged is not true"
                self.hash_violations.append(message)
                self.error(message)

        parser = (document_json.get("parser_name"), document_json.get("parser_version"))
        self.parser_distribution[f"{parser[0]} {parser[1]}"] += 1
        if parser != EXPECTED_PARSER:
            self.error(f"{document.document_id}: parser {parser}, expected {EXPECTED_PARSER}")
        attempts = report.get("parser_attempts")
        if not isinstance(attempts, list) or not attempts:
            self.error(f"{document.document_id}: parser_attempts is empty")
        else:
            final_attempt = attempts[-1]
            if not isinstance(final_attempt, dict):
                self.error(f"{document.document_id}: invalid final parser attempt")
            else:
                attempt_parser = (
                    final_attempt.get("parser_name"),
                    final_attempt.get("parser_version"),
                )
                if attempt_parser != parser:
                    self.error(
                        f"{document.document_id}: parser attempt {attempt_parser} "
                        f"does not match document parser {parser}"
                    )
                if final_attempt.get("error") is not None:
                    self.error(f"{document.document_id}: parser attempt contains error")
        if report.get("fallback_used") is not False:
            self.error(f"{document.document_id}: fallback_used is not false")
        if report.get("errors") != []:
            self.error(f"{document.document_id}: ingestion report contains errors")

        status = document_json.get("extraction_status")
        if report.get("extraction_status") != status:
            self.error(f"{document.document_id}: report/document status mismatch")
        if status not in {"success", "partial", "failed", "skipped", "skipped_cached"}:
            self.error(f"{document.document_id}: invalid extraction status {status!r}")
        else:
            self.statuses[str(status)] += 1
            self.per_project[document.project_id][str(status)] += 1
        if status == "failed":
            self.error(f"{document.document_id}: failed ingestion output")

        count_fields = {
            "pages": (len(records["pages"]), document_json.get("page_count"), "pages_processed"),
            "sections": (len(records["sections"]), None, "section_count"),
            "tables": (len(records["tables"]), None, "table_count"),
            "images": (len(records["images"]), None, "image_count"),
        }
        for kind, (actual, document_count, report_field) in count_fields.items():
            if document_count is not None and document_count != actual:
                self.error(
                    f"{document.document_id}: document {kind} count "
                    f"{document_count!r}, actual {actual}"
                )
            if report.get(report_field) != actual:
                self.error(
                    f"{document.document_id}: report {report_field}="
                    f"{report.get(report_field)!r}, actual {actual}"
                )
            self.totals[kind] += actual
            self.per_project[document.project_id][kind] += actual

        if not records["pages"]:
            self.error(f"{document.document_id}: pages.jsonl has no records")
        if not records["sections"]:
            self.error(f"{document.document_id}: sections.jsonl has no records")
        expected_empty = {
            "tables": report.get("table_count") == 0,
            "images": report.get("image_count") == 0,
        }
        for kind in ("tables", "images"):
            path = directory / JSONL_FILES[kind]
            if path in [ROOT / value for value in self.empty_files] and not expected_empty[kind]:
                self.error(f"{document.document_id}: empty {kind} JSONL contradicts report count")

        warnings = document_json.get("warnings")
        report_warnings = report.get("warnings")
        if warnings != report_warnings:
            self.error(f"{document.document_id}: report/document warnings mismatch")
        if not isinstance(warnings, list):
            self.error(f"{document.document_id}: warnings must be a list")
        elif report.get("warning_count") != len(warnings):
            self.error(f"{document.document_id}: warning_count mismatch")

        self.totals["reports"] += 1
        self.totals[scope] += 1
        self.per_project[document.project_id]["documents"] += 1
        self.per_project[document.project_id][f"{scope}_documents"] += 1
        if status in EXPECTED_STATUSES:
            self.per_project[document.project_id][f"{scope}_{status}"] += 1
        for kind, (actual, _, _) in count_fields.items():
            self.per_project[document.project_id][f"{scope}_{kind}"] += actual
        ocr = document_json.get("ocr")
        if isinstance(ocr, dict) and isinstance(ocr.get("ocr_page_count"), int):
            self.totals["ocr_pages"] += ocr["ocr_page_count"]
            self.per_project[document.project_id]["ocr_pages"] += ocr["ocr_page_count"]
            self.per_project[document.project_id][f"{scope}_ocr_pages"] += ocr["ocr_page_count"]

        self.validate_pages(records["pages"], document, document_json, report)
        self.validate_sections(records["sections"], document, document_json)
        self.validate_tables(records["tables"], document, document_json)
        self.validate_images(records["images"], document, document_json, directory)

    def validate_project_summaries(self) -> None:
        for project_id in EXPECTED_MODEL_INPUTS:
            path = SCOPES["model_inputs"] / project_id / "project.json"
            summary = self.load_json(path, f"{project_id} project.json")
            if summary is None:
                continue
            if summary.get("project_id") != project_id:
                self.error(f"{project_id} project.json: project_id mismatch")
            expected_documents = {
                document.document_id: document
                for document in self.manifest_documents.values()
                if document.project_id == project_id
            }
            if summary.get("manifest_document_count") != len(expected_documents):
                self.error(
                    f"{project_id} project.json: manifest_document_count="
                    f"{summary.get('manifest_document_count')!r}, "
                    f"expected {len(expected_documents)}"
                )
            records = summary.get("documents")
            if not isinstance(records, list):
                self.error(f"{project_id} project.json: documents must be a list")
                continue
            seen: set[str] = set()
            actual_statuses: Counter[str] = Counter()
            for record in records:
                if not isinstance(record, dict):
                    self.error(f"{project_id} project.json: invalid document record")
                    continue
                document_id = record.get("document_id")
                manifest_document = self.manifest_documents.get(str(document_id))
                if manifest_document is None:
                    self.error(f"{project_id} project.json: unknown document {document_id!r}")
                    continue
                if manifest_document.project_id != project_id:
                    self.error(f"{project_id} project.json: cross-project document {document_id}")
                if str(document_id) in seen:
                    self.error(f"{project_id} project.json: duplicate document {document_id}")
                seen.add(str(document_id))
                status = record.get("status")
                if isinstance(status, str):
                    actual_statuses[status] += 1
                if manifest_document.data.get("label_timing") == "post_review":
                    forbidden = {
                        "output_dir",
                        "parser_name",
                        "page_count",
                        "parsed_content",
                        "text",
                        "tables",
                        "images",
                    }
                    present = sorted(forbidden & record.keys())
                    if present or record.get("status") != "skipped":
                        message = (
                            f"{project_id} project.json mixes post-review parsed content for "
                            f"{document_id}: fields={present}, status={record.get('status')!r}"
                        )
                        self.leakage_violations.append(message)
                        self.error(message)
                elif manifest_document.expected_scope == "model_inputs":
                    expected_output = self.relative(
                        SCOPES["model_inputs"] / project_id / str(document_id)
                    )
                    if record.get("output_dir") != expected_output:
                        self.error(
                            f"{project_id} project.json: model input {document_id} "
                            "has wrong output_dir"
                        )
                    if record.get("role") != "model_input":
                        self.error(
                            f"{project_id} project.json: model input {document_id} has wrong role"
                        )
            missing = sorted(set(expected_documents) - seen)
            extra = sorted(seen - set(expected_documents))
            if missing:
                self.error(f"{project_id} project.json: missing manifest documents {missing}")
            if extra:
                self.error(f"{project_id} project.json: extra documents {extra}")
            if summary.get("status_counts") != dict(actual_statuses):
                self.error(
                    f"{project_id} project.json: status_counts="
                    f"{summary.get('status_counts')!r}, actual={dict(actual_statuses)!r}"
                )

    def validate_leakage(self) -> None:
        model_root = SCOPES["model_inputs"]
        label_root = SCOPES["label_sources"]
        for document in self.manifest_documents.values():
            model_output = model_root / document.project_id / document.document_id
            label_output = label_root / document.project_id / document.document_id
            if document.expected_scope == "label_sources" and model_output.exists():
                message = f"label source present in model_inputs: {document.document_id}"
                self.leakage_violations.append(message)
                self.error(message)
            if document.expected_scope == "model_inputs" and label_output.exists():
                message = f"model input present in label_sources: {document.document_id}"
                self.leakage_violations.append(message)
                self.error(message)
            if document.data.get("label_timing") == "post_review" and model_output.exists():
                message = f"post-review output present in model_inputs: {document.document_id}"
                self.leakage_violations.append(message)
                self.error(message)
            if document.data.get("role") == "auxiliary_archive" and (
                model_output.exists() or label_output.exists()
            ):
                message = f"archive has parsed output: {document.document_id}"
                self.leakage_violations.append(message)
                self.error(message)

        for path in PROCESSED.rglob("*"):
            if "weak_findings" in path.name.lower():
                message = f"weak findings artifact ingested: {self.relative(path)}"
                self.leakage_violations.append(message)
                self.error(message)
            if path.is_file() and path.suffix in {".json", ".jsonl"}:
                try:
                    text = path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    continue
                if "data/annotations/" in text or '"annotation_type":"weak_labels"' in text:
                    message = (
                        f"weak findings content referenced by ingestion: {self.relative(path)}"
                    )
                    self.leakage_violations.append(message)
                    self.error(message)

    def validate_expected_counts(self) -> None:
        for key, expected in EXPECTED_COUNTS.items():
            if key == "auxiliary_archives":
                continue
            actual = self.totals[key]
            if actual != expected:
                self.error(f"aggregate {key}: expected {expected}, found {actual}")
        for project_id, expected in EXPECTED_MODEL_INPUTS.items():
            actual = sum(
                1
                for document in self.manifest_documents.values()
                if document.project_id == project_id
                and document.expected_scope == "model_inputs"
                and self.output_locations.get(document.document_id)
            )
            if actual != expected:
                self.error(f"{project_id} model inputs: expected {expected}, found {actual}")
        for status, expected in EXPECTED_STATUSES.items():
            actual = self.statuses[status]
            if actual != expected:
                self.error(f"persisted output status {status}: expected {expected}, found {actual}")

    def validate_all_documents(self) -> None:
        for document_id, document in sorted(self.manifest_documents.items()):
            if document.expected_scope not in SCOPES:
                continue
            locations = self.output_locations.get(document_id, [])
            if len(locations) != 1:
                continue
            scope, directory = locations[0]
            self.validate_document_directory(document, scope, directory)

    @staticmethod
    def print_items(title: str, values: list[str]) -> None:
        print(f"\n{title}: {len(values)}")
        if values:
            for value in values:
                print(f"  - {value}")
        else:
            print("  none")

    def print_summary(self) -> None:
        print("Independent Phase 0 corpus ingestion verification")
        print("=" * 49)
        print("\nExpected vs actual")
        for key, expected in EXPECTED_COUNTS.items():
            if key == "auxiliary_archives":
                actual = sum(
                    document.data.get("role") == "auxiliary_archive"
                    for document in self.manifest_documents.values()
                )
            else:
                actual = self.totals[key]
            print(f"  {key}: expected={expected}, actual={actual}")
        print(
            "  usable_nonempty_tables: "
            f"{self.totals['tables'] - len(self.invalid_tables)} "
            f"(invalid_empty={len(self.invalid_tables)})"
        )
        print("\nFilesystem artifact counts")
        for name in sorted(MANDATORY_FILES):
            print(f"  {name}: {self.artifact_counts[name]}")
        print(f"  physical image files: {self.totals['physical_images']}")

        print("\nPer-project counts")
        for project_id in sorted(EXPECTED_MODEL_INPUTS):
            values = self.per_project[project_id]
            print(
                f"  {project_id} model_inputs: "
                f"documents={values['model_inputs_documents']}, "
                f"success={values['model_inputs_success']}, "
                f"partial={values['model_inputs_partial']}, "
                f"pages={values['model_inputs_pages']}, "
                f"tables={values['model_inputs_tables']}, "
                f"images={values['model_inputs_images']}, "
                f"ocr_pages={values['model_inputs_ocr_pages']}"
            )
            if values["label_sources_documents"]:
                print(
                    f"  {project_id} label_sources: "
                    f"documents={values['label_sources_documents']}, "
                    f"success={values['label_sources_success']}, "
                    f"partial={values['label_sources_partial']}, "
                    f"pages={values['label_sources_pages']}, "
                    f"tables={values['label_sources_tables']}, "
                    f"images={values['label_sources_images']}, "
                    f"ocr_pages={values['label_sources_ocr_pages']}"
                )

        print("\nPersisted output statuses")
        for status in EXPECTED_STATUSES:
            print(f"  {status}: {self.statuses[status]}")
        print("  auxiliary archive routing skip: 1")

        print("\nParser distribution")
        for parser, count in sorted(self.parser_distribution.items()):
            print(f"  {parser}: {count}")
        print(
            "\nHash integrity: "
            f"checked={self.totals['reports']}, violations={len(self.hash_violations)}"
        )
        provenance_records = (
            sum(len(values) for values in self.logical_ids.values()) + self.totals["pages"]
        )
        print(
            f"Provenance: records={provenance_records}, "
            f"violations={len(self.provenance_violations)}"
        )
        print(
            "OCR: "
            f"documents_engine_ran={len(self.ocr_documents)}, "
            f"ocr_pages={self.totals['ocr_pages']}, "
            f"short_ocr_pages={len(self.short_ocr_pages)}, "
            f"pages_without_embedded_text={len(self.pages_without_embedded_text)}"
        )

        self.print_items("Leakage violations", self.leakage_violations)
        self.print_items("Missing files/directories", sorted(set(self.missing_files)))
        self.print_items("JSON/JSONL errors", self.json_errors)
        self.print_items("Orphan outputs", self.orphan_outputs)
        self.print_items("Temporary directories", self.temp_directories)
        self.print_items("Unexpected files", self.unexpected_files)
        self.print_items("Empty output files", self.empty_files)
        self.print_items("Invalid table records", self.invalid_tables)
        self.print_items("Blocking errors", self.errors)
        self.print_items("Non-blocking warnings", self.warnings)

        verdict = "PASS" if not self.errors else "FAIL"
        print(f"\nFINAL VERIFICATION STATUS: {verdict}")

    def run(self) -> int:
        self.read_manifest()
        self.find_outputs()
        self.validate_all_documents()
        self.validate_project_summaries()
        self.validate_leakage()
        self.validate_expected_counts()
        self.print_summary()
        return 0 if not self.errors else 1


if __name__ == "__main__":
    sys.exit(CorpusVerifier().run())

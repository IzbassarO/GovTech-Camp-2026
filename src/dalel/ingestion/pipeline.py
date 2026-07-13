"""Phase 0 ingestion pipeline orchestration.

Per document: manifest entry → role check → file existence → SHA-256 before →
route → parse (Docling, PyMuPDF/python-docx fallback) → records with
provenance → SHA-256 after → atomic write. One document's failure never stops
the batch. ``data/raw`` is opened read-only and never modified.
"""

from __future__ import annotations

import logging
import time
import traceback
from dataclasses import dataclass
from pathlib import Path

from dalel.config import (
    INGESTION_SCHEMA_VERSION,
    ExtractionStatus,
    OcrMode,
    output_root_for_role,
)
from dalel.ingestion import docling_parser, docx_fallback, pymupdf_fallback
from dalel.ingestion.hashing import sha256_file
from dalel.ingestion.parsed import ParsedDocument
from dalel.ingestion.pdf_mode import PdfAnalysis, analyze_pdf
from dalel.ingestion.reports import (
    BatchResult,
    DocumentResult,
    build_project_summary,
    utc_now_iso,
)
from dalel.ingestion.routing import ParserRoute, Selection, route_for, select_documents
from dalel.ingestion.storage import (
    compute_cache_key,
    document_output_dir,
    is_cached,
    write_document_output,
    write_project_summary,
)
from dalel.ingestion.validation import load_manifest
from dalel.schemas.document import (
    DocumentRecord,
    IngestionReport,
    OcrMetadata,
    ParserAttempt,
    SectionRecord,
)
from dalel.schemas.evidence import Provenance
from dalel.schemas.image import ImageRecord
from dalel.schemas.manifest import ManifestDocument, ManifestProject
from dalel.schemas.page import PageRecord
from dalel.schemas.table import TableRecord

logger = logging.getLogger(__name__)


@dataclass
class IngestOptions:
    manifest_path: Path
    repo_root: Path
    project_id: str | None = None
    document_id: str | None = None
    ocr_mode: OcrMode = OcrMode.AUTO
    include_label_sources: bool = False
    force: bool = False


def _pipeline_parser_identities() -> list[tuple[str, str | None]]:
    """Everything that can influence output, for the cache key: parsers AND
    OCR engine availability/versions — installing or upgrading an OCR engine
    must invalidate previously produced (possibly partial) output."""
    import importlib.metadata
    import shutil as _shutil

    def _dist_version(name: str) -> str:
        try:
            return importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            return "absent"

    return [
        (docling_parser.PARSER_NAME, docling_parser.parser_version()),
        (pymupdf_fallback.PARSER_NAME, pymupdf_fallback.parser_version()),
        (docx_fallback.PARSER_NAME, docx_fallback.parser_version()),
        ("ocr:easyocr", _dist_version("easyocr")),
        ("ocr:tesseract", "present" if _shutil.which("tesseract") else "absent"),
    ]


_UNSAFE_ID_MARKERS = ("/", "\\", "..")


def _identifier_is_safe(identifier: str) -> bool:
    """Manifest ids become output path components; refuse traversal-capable ones."""
    return (
        bool(identifier)
        and not identifier.startswith(".")
        and not any(marker in identifier for marker in _UNSAFE_ID_MARKERS)
    )


def ingest_documents(options: IngestOptions) -> BatchResult:
    """Run ingestion for the selected manifest slice."""
    batch = BatchResult(started_at=utc_now_iso())
    projects = load_manifest(options.manifest_path)

    selection = select_documents(
        projects,
        project_id=options.project_id,
        document_id=options.document_id,
        include_label_sources=options.include_label_sources,
    )
    _warn_on_empty_filters(options, selection, projects)
    logger.info(
        "selection complete: selected=%d skipped=%d project_id=%s document_id=%s"
        " include_label_sources=%s",
        len(selection.selected),
        len(selection.skipped),
        options.project_id or "*",
        options.document_id or "*",
        options.include_label_sources,
    )

    for skipped in selection.skipped:
        logger.info(
            "skip %s/%s: %s%s",
            skipped.project.project_id,
            skipped.document.document_id,
            skipped.reason,
            f" ({'; '.join(skipped.warnings)})" if skipped.warnings else "",
        )
        batch.results.append(
            DocumentResult(
                project_id=skipped.project.project_id,
                document_id=skipped.document.document_id,
                document_type=skipped.document.document_type,
                role=skipped.document.role,
                status=ExtractionStatus.SKIPPED.value,
                reason=skipped.reason,
            )
        )

    for selected in selection.selected:
        project, document = selected.project, selected.document
        logger.info("ingest start %s/%s", project.project_id, document.document_id)
        try:
            result = _ingest_one(project, document, options)
        except Exception as exc:  # one document must never stop the batch
            logger.error(
                "unexpected failure for %s/%s: %s",
                project.project_id,
                document.document_id,
                exc,
            )
            logger.debug("%s", traceback.format_exc())
            result = DocumentResult(
                project_id=project.project_id,
                document_id=document.document_id,
                document_type=document.document_type,
                role=document.role,
                status=ExtractionStatus.FAILED.value,
                reason="unexpected_error",
                errors=[f"{type(exc).__name__}: {exc}"],
            )
        batch.results.append(result)
        if result.status == ExtractionStatus.FAILED.value:
            logger.error(
                "ingest failed %s/%s: reason=%s errors=%s",
                project.project_id,
                document.document_id,
                result.reason or "unknown",
                "; ".join(result.errors) or "none reported",
            )
        else:
            logger.info(
                "ingest complete %s/%s: status=%s reason=%s",
                project.project_id,
                document.document_id,
                result.status,
                result.reason or "none",
            )

    _write_project_summaries(options.repo_root, projects, batch)
    batch.completed_at = utc_now_iso()
    return batch


def _warn_on_empty_filters(
    options: IngestOptions, selection: Selection, projects: list[ManifestProject]
) -> None:
    if options.document_id is not None and not selection.selected and not selection.skipped:
        known = {d.document_id for p in projects for d in p.documents}
        detail = (
            "document_id not present in manifest"
            if options.document_id not in known
            else "document filtered out"
        )
        raise ValueError(f"--document-id {options.document_id!r}: {detail}")
    if options.project_id is not None and not selection.selected and not selection.skipped:
        known_projects = {p.project_id for p in projects}
        if options.project_id not in known_projects:
            raise ValueError(f"--project-id {options.project_id!r} not present in manifest")


def _write_project_summaries(
    repo_root: Path, projects: list[ManifestProject], batch: BatchResult
) -> None:
    touched = {result.project_id for result in batch.results}
    for project in projects:
        if project.project_id not in touched:
            continue
        summary = build_project_summary(
            repo_root,
            project.project_id,
            manifest_document_count=len(project.documents),
            run_results=batch.results,
        )
        model_inputs_root = output_root_for_role(repo_root, "model_input")
        write_project_summary(model_inputs_root, project.project_id, summary)


def _ingest_one(
    project: ManifestProject, document: ManifestDocument, options: IngestOptions
) -> DocumentResult:
    started_monotonic = time.monotonic()
    started_at = utc_now_iso()
    result = DocumentResult(
        project_id=project.project_id,
        document_id=document.document_id,
        document_type=document.document_type,
        role=document.role,
        status=ExtractionStatus.FAILED.value,
    )

    if not _identifier_is_safe(project.project_id) or not _identifier_is_safe(document.document_id):
        result.reason = "unsafe_identifier"
        result.errors.append(
            "project_id/document_id contain path separators or traversal segments;"
            " refusing to build an output path from them"
        )
        return result

    local_path = options.repo_root / document.local_path
    if not local_path.is_file():
        result.reason = "file_missing"
        result.errors.append(f"file does not exist: {document.local_path}")
        return result

    raw_hash_before = sha256_file(local_path)
    if raw_hash_before != document.sha256:
        result.reason = "sha256_mismatch"
        result.errors.append(
            f"SHA-256 mismatch before parsing: manifest {document.sha256[:12]}…,"
            f" actual {raw_hash_before[:12]}…"
        )
        return result

    route = route_for(document)
    if route not in {ParserRoute.PDF, ParserRoute.DOCX}:
        result.status = ExtractionStatus.SKIPPED.value
        result.reason = f"route_{route.value}"
        return result

    output_root = output_root_for_role(options.repo_root, document.role)
    out_dir = document_output_dir(output_root, project.project_id, document.document_id)
    cache_key = compute_cache_key(
        source_sha256=document.sha256,
        parser_names_and_versions=_pipeline_parser_identities(),
        ocr_mode=options.ocr_mode.value,
    )
    if not options.force and is_cached(out_dir, cache_key):
        result.status = ExtractionStatus.SKIPPED_CACHED.value
        result.reason = "cache_key_match"
        result.output_dir = _relative_to_root(out_dir, options.repo_root)
        return result

    attempts: list[ParserAttempt] = []
    fallback_used = False
    analysis: PdfAnalysis | None = None
    parsed: ParsedDocument | None = None

    if route is ParserRoute.PDF:
        analysis = analyze_pdf(local_path)
        parsed, attempts, fallback_used = _parse_pdf_with_fallback(
            local_path, analysis, options.ocr_mode, project.languages
        )
    else:
        parsed, attempts, fallback_used = _parse_docx_with_fallback(local_path)

    if parsed is None:
        result.reason = "all_parsers_failed"
        result.errors.extend(
            f"{attempt.parser_name}: {attempt.error}" for attempt in attempts if attempt.error
        )
        if sha256_file(local_path) != raw_hash_before:
            result.errors.append(
                "raw file hash changed during parsing; data/raw immutability violated"
            )
        return result

    raw_hash_after = sha256_file(local_path)
    hash_unchanged = raw_hash_after == raw_hash_before
    if not hash_unchanged:
        # The parsed content came from bytes that no longer match the manifest
        # hash: its provenance would be false. Never persist it.
        result.reason = "sha256_changed_during_parsing"
        result.errors.append(
            "raw file hash changed during parsing; data/raw immutability violated;"
            f" extracted content discarded (before {raw_hash_before[:12]}…,"
            f" after {raw_hash_after[:12]}…)"
        )
        return result

    records = _build_records(project, document, parsed, analysis, options, route)
    report = IngestionReport(
        schema_version=INGESTION_SCHEMA_VERSION,
        project_id=project.project_id,
        document_id=document.document_id,
        started_at=started_at,
        completed_at=utc_now_iso(),
        elapsed_seconds=round(time.monotonic() - started_monotonic, 3),
        parser_attempts=attempts,
        fallback_used=fallback_used,
        pages_processed=len(records.pages),
        ocr_pages=len(parsed.ocr.ocr_pages),
        table_count=len(records.tables),
        image_count=len(records.images),
        section_count=len(records.sections),
        warning_count=len(records.document.warnings),
        warnings=records.document.warnings,
        errors=parsed.errors,
        raw_hash_before=raw_hash_before,
        raw_hash_after=raw_hash_after,
        hash_unchanged=hash_unchanged,
        cache_key=cache_key,
        ocr_mode=options.ocr_mode.value,
        extraction_status=records.document.extraction_status,
    )

    write_document_output(
        out_dir,
        records.document,
        records.pages,
        records.sections,
        records.tables,
        records.images,
        records.image_blobs,
        report,
    )

    result.status = records.document.extraction_status
    result.reason = "parser_reported_failure" if result.status == "failed" else None
    result.parser_name = parsed.parser_name
    result.fallback_used = fallback_used
    result.pages = len(records.pages)
    result.tables = len(records.tables)
    result.images = len(records.images)
    result.sections = len(records.sections)
    result.ocr_pages = len(parsed.ocr.ocr_pages)
    result.warning_count = len(records.document.warnings)
    result.errors = list(parsed.errors)
    result.output_dir = _relative_to_root(out_dir, options.repo_root)
    result.elapsed_seconds = round(time.monotonic() - started_monotonic, 3)
    return result


_IMAGE_MAGIC: list[tuple[bytes, str]] = [
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpg"),
    (b"GIF8", "gif"),
    (b"II*\x00", "tiff"),
    (b"MM\x00*", "tiff"),
    (b"BM", "bmp"),
]


def _sniff_image_extension(blob: bytes) -> str | None:
    """Detect the actual image format; DOCX fallback blobs are raw part bytes."""
    for magic, extension in _IMAGE_MAGIC:
        if blob.startswith(magic):
            return extension
    if blob[:4] == b"RIFF" and blob[8:12] == b"WEBP":
        return "webp"
    return None


def _sanitize_confidence(confidence: dict[str, object] | None) -> dict[str, object] | None:
    """Replace non-finite floats with null so document.json stays strict JSON;
    drop the report entirely if it carries no finite value."""
    import math

    if confidence is None:
        return None

    has_finite = False

    def _clean(value: object) -> object:
        nonlocal has_finite
        if isinstance(value, float):
            if math.isfinite(value):
                has_finite = True
                return value
            return None
        if isinstance(value, dict):
            return {str(k): _clean(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_clean(v) for v in value]
        return value

    cleaned = {str(k): _clean(v) for k, v in confidence.items()}
    return cleaned if has_finite else None


def _relative_to_root(path: Path, repo_root: Path) -> str:
    try:
        return str(path.relative_to(repo_root))
    except ValueError:
        return str(path)


def _parse_pdf_with_fallback(
    local_path: Path,
    analysis: PdfAnalysis,
    ocr_mode: OcrMode,
    languages: list[str],
) -> tuple[ParsedDocument | None, list[ParserAttempt], bool]:
    attempts: list[ParserAttempt] = []
    try:
        parsed = docling_parser.parse_pdf_docling(local_path, analysis, ocr_mode, languages)
        attempts.append(
            ParserAttempt(
                parser_name=docling_parser.PARSER_NAME,
                parser_version=parsed.parser_version,
                status=parsed.status,
            )
        )
        return parsed, attempts, False
    except Exception as exc:
        logger.warning("docling failed for %s, falling back to pymupdf: %s", local_path.name, exc)
        attempts.append(
            ParserAttempt(
                parser_name=docling_parser.PARSER_NAME,
                parser_version=docling_parser.parser_version(),
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
            )
        )

    try:
        parsed = pymupdf_fallback.parse_pdf_fallback(local_path, analysis, ocr_mode)
        attempts.append(
            ParserAttempt(
                parser_name=pymupdf_fallback.PARSER_NAME,
                parser_version=parsed.parser_version,
                status=parsed.status,
            )
        )
        return parsed, attempts, True
    except Exception as exc:
        attempts.append(
            ParserAttempt(
                parser_name=pymupdf_fallback.PARSER_NAME,
                parser_version=pymupdf_fallback.parser_version(),
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
            )
        )
        return None, attempts, True


def _parse_docx_with_fallback(
    local_path: Path,
) -> tuple[ParsedDocument | None, list[ParserAttempt], bool]:
    attempts: list[ParserAttempt] = []
    try:
        parsed = docling_parser.parse_docx_docling(local_path)
        attempts.append(
            ParserAttempt(
                parser_name=docling_parser.PARSER_NAME,
                parser_version=parsed.parser_version,
                status=parsed.status,
            )
        )
        return parsed, attempts, False
    except Exception as exc:
        logger.warning(
            "docling failed for %s, falling back to python-docx: %s", local_path.name, exc
        )
        attempts.append(
            ParserAttempt(
                parser_name=docling_parser.PARSER_NAME,
                parser_version=docling_parser.parser_version(),
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
            )
        )

    try:
        parsed = docx_fallback.parse_docx_fallback(local_path)
        attempts.append(
            ParserAttempt(
                parser_name=docx_fallback.PARSER_NAME,
                parser_version=parsed.parser_version,
                status=parsed.status,
            )
        )
        return parsed, attempts, True
    except Exception as exc:
        attempts.append(
            ParserAttempt(
                parser_name=docx_fallback.PARSER_NAME,
                parser_version=docx_fallback.parser_version(),
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
            )
        )
        return None, attempts, True


@dataclass
class _DocumentRecords:
    document: DocumentRecord
    pages: list[PageRecord]
    sections: list[SectionRecord]
    tables: list[TableRecord]
    images: list[ImageRecord]
    image_blobs: dict[str, bytes]


def _build_records(
    project: ManifestProject,
    document: ManifestDocument,
    parsed: ParsedDocument,
    analysis: PdfAnalysis | None,
    options: IngestOptions,
    route: ParserRoute,
) -> _DocumentRecords:
    created_at = utc_now_iso()

    def provenance(
        page_number: int | None,
        bbox: object,
        extraction_method: str,
        ocr_used: bool = False,
    ) -> Provenance:
        return Provenance(
            project_id=project.project_id,
            document_id=document.document_id,
            document_type=document.document_type,
            role=document.role,
            source_path=document.local_path,
            source_sha256=document.sha256,
            page_number=page_number,
            bbox=bbox,  # type: ignore[arg-type]
            extraction_method=extraction_method,
            parser_name=parsed.parser_name,
            parser_version=parsed.parser_version,
            ocr_used=ocr_used,
            created_at=created_at,
        )

    base_method = parsed.parser_name

    pages: list[PageRecord] = []
    for parsed_page in parsed.pages:
        page_warnings = list(parsed_page.warnings)
        if parsed_page.width is None or parsed_page.height is None:
            page_warnings.append("page dimensions unavailable")
        method = f"{base_method}_ocr" if parsed_page.ocr_applied else base_method
        # A pseudo-page (flow DOCX) has a positional page_number for record
        # ordering, but its provenance must not claim a physical page.
        is_pseudo_page = any(w.startswith("pseudo-page") for w in parsed_page.warnings)
        provenance_page = None if is_pseudo_page else parsed_page.page_number
        pages.append(
            PageRecord(
                schema_version=INGESTION_SCHEMA_VERSION,
                page_number=parsed_page.page_number,
                width=parsed_page.width,
                height=parsed_page.height,
                rotation=parsed_page.rotation,
                text=parsed_page.text,
                char_count=len(parsed_page.text.strip()),
                ocr_applied=parsed_page.ocr_applied,
                has_embedded_text=parsed_page.has_embedded_text,
                warnings=page_warnings,
                provenance=provenance(provenance_page, None, method, parsed_page.ocr_applied),
            )
        )

    sections: list[SectionRecord] = []
    for index, parsed_section in enumerate(parsed.sections, start=1):
        section_warnings = list(parsed_section.warnings)
        if parsed_section.page_start is None:
            section_warnings.append("page range unavailable; page_start/page_end are null")
        sections.append(
            SectionRecord(
                schema_version=INGESTION_SCHEMA_VERSION,
                section_id=f"{document.document_id}__sec_{index:04d}",
                title=parsed_section.title,
                level=parsed_section.level,
                page_start=parsed_section.page_start,
                page_end=parsed_section.page_end,
                text=parsed_section.text,
                char_count=len(parsed_section.text.strip()),
                warnings=section_warnings,
                provenance=provenance(parsed_section.page_start, None, base_method),
            )
        )

    tables: list[TableRecord] = []
    for index, parsed_table in enumerate(parsed.tables, start=1):
        table_warnings = list(parsed_table.warnings)
        if parsed_table.page_number is None:
            table_warnings.append("page number unavailable; not invented")
        if parsed_table.bbox is None:
            table_warnings.append("bbox unavailable; not invented")
        tables.append(
            TableRecord(
                schema_version=INGESTION_SCHEMA_VERSION,
                table_id=f"{document.document_id}__tab_{index:04d}",
                page_number=parsed_table.page_number,
                num_rows=parsed_table.num_rows,
                num_cols=parsed_table.num_cols,
                cells=parsed_table.cells,
                caption=parsed_table.caption,
                confidence=parsed_table.confidence,
                confidence_source=parsed_table.confidence_source,
                warnings=table_warnings,
                provenance=provenance(parsed_table.page_number, parsed_table.bbox, base_method),
            )
        )

    images: list[ImageRecord] = []
    image_blobs: dict[str, bytes] = {}
    for index, parsed_image in enumerate(parsed.images, start=1):
        image_id = f"{document.document_id}__img_{index:04d}"
        image_warnings = list(parsed_image.warnings)
        image_path: str | None = None
        if parsed_image.png_bytes is not None:
            extension = _sniff_image_extension(parsed_image.png_bytes)
            if extension is None:
                extension = "bin"
                image_warnings.append("unrecognized image format; stored with .bin extension")
            image_path = f"images/img_{index:04d}.{extension}"
            image_blobs[image_path] = parsed_image.png_bytes
        else:
            image_warnings.append("image bytes unavailable; metadata-only record")
        if parsed_image.page_number is None:
            image_warnings.append("page number unavailable; not invented")
        images.append(
            ImageRecord(
                schema_version=INGESTION_SCHEMA_VERSION,
                image_id=image_id,
                page_number=parsed_image.page_number,
                width_px=parsed_image.width_px,
                height_px=parsed_image.height_px,
                image_path=image_path,
                classification=parsed_image.classification,
                classification_source=parsed_image.classification_source,
                warnings=image_warnings,
                provenance=provenance(parsed_image.page_number, parsed_image.bbox, base_method),
            )
        )

    if analysis is not None:
        document_mode = analysis.mode
        page_count: int | None = analysis.page_count
    else:
        document_mode = "docx_flow"
        page_count = None

    document_warnings = list(parsed.warnings)
    # OCR warnings (e.g. ocr_engine_unavailable) must be visible at the
    # document level too, where warning_count is derived.
    for ocr_warning in parsed.ocr.warnings:
        if ocr_warning not in document_warnings:
            document_warnings.append(ocr_warning)
    ocr_metadata = OcrMetadata(
        mode=options.ocr_mode.value,
        engine=parsed.ocr.engine,
        engine_version=parsed.ocr.engine_version,
        engine_available=parsed.ocr.engine_available,
        engine_ran=parsed.ocr.engine_ran,
        ocr_pages=sorted(parsed.ocr.ocr_pages),
        ocr_page_count=len(parsed.ocr.ocr_pages),
        candidate_pages=analysis.ocr_candidate_pages if analysis is not None else [],
        elapsed_seconds=parsed.ocr.elapsed_seconds,
        warnings=parsed.ocr.warnings,
    )

    status = parsed.status
    if parsed.errors and status != "failed":
        status = "partial"

    document_record = DocumentRecord(
        schema_version=INGESTION_SCHEMA_VERSION,
        project_id=project.project_id,
        document_id=document.document_id,
        document_type=document.document_type,
        role=document.role,
        use_as_model_feature=document.use_as_model_feature,
        label_timing=document.label_timing,
        source_path=document.local_path,
        source_url=project.source_url,
        source_sha256=document.sha256,
        original_filename=document.original_filename,
        file_format=document.file_format,
        parser_name=parsed.parser_name,
        parser_version=parsed.parser_version,
        page_count=page_count if page_count is not None else (len(pages) or None),
        languages=list(project.languages),
        document_mode=document_mode,
        ocr=ocr_metadata,
        parser_confidence=_sanitize_confidence(parsed.confidence),
        parser_confidence_source=parsed.confidence_source if parsed.confidence else None,
        extraction_status=status,
        created_at=created_at,
        warnings=document_warnings,
    )

    return _DocumentRecords(
        document=document_record,
        pages=pages,
        sections=sections,
        tables=tables,
        images=images,
        image_blobs=image_blobs,
    )

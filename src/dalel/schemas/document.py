"""Document-level records: ``document.json``, sections and OCR metadata."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from dalel.schemas.evidence import Provenance


class OcrMetadata(BaseModel):
    """What OCR actually did for a document. Honest by construction:
    ``engine_ran`` stays ``False`` unless an OCR engine really executed."""

    model_config = ConfigDict(extra="forbid")

    mode: str  # auto | always | never
    engine: str | None = None
    engine_version: str | None = None
    engine_available: bool = False
    engine_ran: bool = False
    ocr_pages: list[int] = Field(default_factory=list)
    ocr_page_count: int = 0
    candidate_pages: list[int] = Field(default_factory=list)
    elapsed_seconds: float | None = None
    warnings: list[str] = Field(default_factory=list)


class SectionRecord(BaseModel):
    """One line of ``sections.jsonl``: a heading-delimited span of the document."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str
    section_id: str
    title: str | None = None
    level: int | None = None
    page_start: int | None = None
    page_end: int | None = None
    text: str = ""
    char_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    provenance: Provenance


class DocumentRecord(BaseModel):
    """``document.json`` — the document-level extraction summary."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str
    project_id: str
    document_id: str
    document_type: str
    role: str
    use_as_model_feature: bool
    label_timing: str | None = None
    source_path: str
    source_url: str | None = None
    source_sha256: str
    original_filename: str | None = None
    file_format: str
    parser_name: str
    parser_version: str | None = None
    page_count: int | None = None
    languages: list[str] = Field(default_factory=list)
    # ``digital`` / ``scanned`` / ``mixed`` for PDF; ``docx_flow`` for DOCX.
    document_mode: str | None = None
    ocr: OcrMetadata
    # Parser-provided confidence only (e.g. Docling confidence report); never invented.
    parser_confidence: dict[str, object] | None = None
    parser_confidence_source: str | None = None
    extraction_status: str
    created_at: str
    warnings: list[str] = Field(default_factory=list)


class ParserAttempt(BaseModel):
    """One parser attempt inside ``ingestion_report.json``."""

    model_config = ConfigDict(extra="forbid")

    parser_name: str
    parser_version: str | None = None
    status: str  # success | partial | failed
    error: str | None = None


class IngestionReport(BaseModel):
    """``ingestion_report.json`` — the per-document run report."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str
    project_id: str
    document_id: str
    started_at: str
    completed_at: str
    elapsed_seconds: float
    parser_attempts: list[ParserAttempt] = Field(default_factory=list)
    fallback_used: bool = False
    pages_processed: int = 0
    ocr_pages: int = 0
    table_count: int = 0
    image_count: int = 0
    section_count: int = 0
    warning_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    raw_hash_before: str | None = None
    raw_hash_after: str | None = None
    hash_unchanged: bool | None = None
    cache_key: str | None = None
    ocr_mode: str | None = None
    extraction_status: str

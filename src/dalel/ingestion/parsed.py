"""Parser-neutral intermediate representation.

Docling, the PyMuPDF fallback and the DOCX fallback all return a
``ParsedDocument``; storage converts it into the output records. Keeping this
parser-neutral is what makes fallback transparent to the rest of the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from dalel.schemas.evidence import BBox


@dataclass
class ParsedPage:
    page_number: int  # 1-based
    width: float | None = None
    height: float | None = None
    rotation: int | None = None
    text: str = ""
    ocr_applied: bool = False
    has_embedded_text: bool | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class ParsedSection:
    title: str | None = None
    level: int | None = None
    page_start: int | None = None
    page_end: int | None = None
    text: str = ""
    warnings: list[str] = field(default_factory=list)


@dataclass
class ParsedTable:
    page_number: int | None = None
    bbox: BBox | None = None
    cells: list[list[str]] = field(default_factory=list)
    num_rows: int = 0
    num_cols: int = 0
    caption: str | None = None
    confidence: float | None = None
    confidence_source: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class ParsedImage:
    page_number: int | None = None
    bbox: BBox | None = None
    width_px: int | None = None
    height_px: int | None = None
    png_bytes: bytes | None = None
    classification: str | None = None
    classification_source: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class SkippedTableItem:
    """A parser-detected table item that failed the table validity contract.

    It is never serialized into ``tables.jsonl``; the pipeline converts it into
    an ``empty_table_item_skipped`` document warning and report counters. No
    field is invented: unknown page/reference stay ``None``.
    """

    page_number: int | None = None
    reference: str | None = None  # parser-native item reference (e.g. docling self_ref)
    extraction_method: str = ""
    message: str = ""


@dataclass
class OcrOutcome:
    """What OCR actually did during one parser run."""

    engine: str | None = None
    engine_version: str | None = None
    engine_available: bool = False
    engine_ran: bool = False
    ocr_pages: list[int] = field(default_factory=list)
    elapsed_seconds: float | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class ParsedDocument:
    parser_name: str
    parser_version: str | None
    status: str  # success | partial | failed
    pages: list[ParsedPage] = field(default_factory=list)
    sections: list[ParsedSection] = field(default_factory=list)
    tables: list[ParsedTable] = field(default_factory=list)
    # Table items the parser detected but pre-filtered as empty (layer 1 of
    # the table validity contract); reported, never serialized.
    skipped_empty_tables: list[SkippedTableItem] = field(default_factory=list)
    images: list[ParsedImage] = field(default_factory=list)
    ocr: OcrOutcome = field(default_factory=OcrOutcome)
    # Parser-provided confidence report; None when the parser has none.
    confidence: dict[str, object] | None = None
    confidence_source: str | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

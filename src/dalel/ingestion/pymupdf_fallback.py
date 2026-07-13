"""PyMuPDF fallback parser for PDF documents.

Used when Docling fails or is unavailable. Extracts page text, basic tables
(``page.find_tables``), embedded images and TOC-based sections. OCR here
requires a system Tesseract; when it is missing the parser degrades honestly:
pages that needed OCR stay empty, the document is ``partial`` and the report
carries ``ocr_engine_unavailable``.
"""

from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path
from typing import Any

from dalel.config import MIN_USABLE_CHARS_PER_PAGE, OcrMode
from dalel.ingestion.image_extractor import extract_page_images
from dalel.ingestion.parsed import (
    OcrOutcome,
    ParsedDocument,
    ParsedPage,
    ParsedSection,
    ParsedTable,
)
from dalel.ingestion.pdf_mode import PdfAnalysis
from dalel.schemas.evidence import BBox

logger = logging.getLogger(__name__)

PARSER_NAME = "pymupdf"


def parser_version() -> str | None:
    try:
        import fitz

        return str(fitz.pymupdf_version)
    except Exception:
        return None


def _tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


def _ocr_page_text(page: Any) -> str:
    """Run Tesseract OCR on one page via PyMuPDF. Raises on failure."""
    textpage = page.get_textpage_ocr(flags=0, full=True)
    return page.get_text("text", textpage=textpage) or ""


def _extract_tables(page: Any, page_number: int) -> list[ParsedTable]:
    tables: list[ParsedTable] = []
    try:
        found = page.find_tables()
    except Exception as exc:
        logger.warning("page %d: find_tables failed: %s", page_number, exc)
        return tables
    for table in getattr(found, "tables", []):
        try:
            cells = [
                [(cell if cell is not None else "") for cell in row] for row in table.extract()
            ]
            rect = table.bbox
            bbox = BBox(l=float(rect[0]), t=float(rect[1]), r=float(rect[2]), b=float(rect[3]))
            tables.append(
                ParsedTable(
                    page_number=page_number,
                    bbox=bbox,
                    cells=cells,
                    num_rows=len(cells),
                    num_cols=max((len(row) for row in cells), default=0),
                )
            )
        except Exception as exc:
            tables.append(
                ParsedTable(
                    page_number=page_number,
                    warnings=[f"table extraction failed: {exc}"],
                )
            )
    return tables


def _extract_sections(doc: Any, page_texts: dict[int, str], page_count: int) -> list[ParsedSection]:
    """Build sections from the PDF table of contents when one exists."""
    try:
        toc = doc.get_toc(simple=True)
    except Exception:
        toc = []
    if not toc:
        return []

    sections: list[ParsedSection] = []
    for index, (level, title, page_start) in enumerate(toc):
        page_end = page_count
        for next_level, _next_title, next_start in toc[index + 1 :]:
            if next_level <= level:
                page_end = max(page_start, next_start - 1)
                break
        start = max(1, int(page_start))
        end = max(start, int(page_end))
        text = "\n".join(page_texts.get(number, "") for number in range(start, end + 1))
        sections.append(
            ParsedSection(
                title=str(title).strip() or None,
                level=int(level),
                page_start=start,
                page_end=end,
                text=text,
                warnings=["section text approximated from TOC page ranges"],
            )
        )
    return sections


def parse_pdf_fallback(path: Path, analysis: PdfAnalysis, ocr_mode: OcrMode) -> ParsedDocument:
    """Parse a PDF with PyMuPDF only."""
    import fitz  # lazy: PyMuPDF

    version = parser_version()
    result = ParsedDocument(parser_name=PARSER_NAME, parser_version=version, status="success")
    result.warnings.append(
        "pymupdf fallback: no layout model; sections come from the PDF TOC when present"
    )

    candidates = set(analysis.ocr_candidate_pages)
    if ocr_mode is OcrMode.ALWAYS:
        pages_to_ocr = {info.page_number for info in analysis.pages}
    elif ocr_mode is OcrMode.AUTO:
        pages_to_ocr = set(candidates)
    else:
        pages_to_ocr = set()

    ocr = OcrOutcome()
    tesseract_ok = _tesseract_available() if pages_to_ocr else False
    ocr_engine_missing = bool(pages_to_ocr) and not tesseract_ok
    if ocr_engine_missing:
        ocr.warnings.append("ocr_engine_unavailable")
        result.warnings.append(
            "ocr_engine_unavailable: tesseract binary not found; pages without embedded"
            " text were not OCRed"
        )
    if tesseract_ok:
        ocr.engine = "tesseract"
        ocr.engine_available = True
        try:
            import subprocess

            proc = subprocess.run(
                ["tesseract", "--version"], capture_output=True, text=True, timeout=10
            )
            first_line = (proc.stdout or proc.stderr).splitlines()
            ocr.engine_version = first_line[0].strip() if first_line else None
        except Exception:
            ocr.engine_version = None

    page_texts: dict[int, str] = {}
    unresolved_ocr_pages: list[int] = []
    ocr_started = time.monotonic()

    with fitz.open(path) as doc:
        for info in analysis.pages:
            page_warnings: list[str] = []
            text = info.embedded_text
            ocr_applied = False

            if info.page_number in pages_to_ocr:
                if tesseract_ok:
                    try:
                        page = doc[info.page_number - 1]
                        ocr_text = _ocr_page_text(page)
                        ocr_applied = True
                        ocr.engine_ran = True
                        ocr.ocr_pages.append(info.page_number)
                        if len(ocr_text.strip()) > len(text.strip()):
                            text = ocr_text
                        if (
                            not info.has_usable_text
                            and len(text.strip()) < MIN_USABLE_CHARS_PER_PAGE
                        ):
                            # OCR ran but recognized nothing usable.
                            page_warnings.append("ocr_produced_no_usable_text")
                            unresolved_ocr_pages.append(info.page_number)
                    except Exception as exc:
                        page_warnings.append(f"ocr_failed: {exc}")
                        if not info.has_usable_text:
                            unresolved_ocr_pages.append(info.page_number)
                else:
                    if not info.has_usable_text:
                        page_warnings.append("page_requires_ocr_but_engine_unavailable")
                        unresolved_ocr_pages.append(info.page_number)

            stripped = text.strip()
            page_texts[info.page_number] = text
            result.pages.append(
                ParsedPage(
                    page_number=info.page_number,
                    width=info.width,
                    height=info.height,
                    rotation=info.rotation,
                    text=text,
                    ocr_applied=ocr_applied,
                    has_embedded_text=info.has_usable_text,
                    warnings=page_warnings,
                )
            )
            page_stayed_textless = (
                len(stripped) < MIN_USABLE_CHARS_PER_PAGE and not info.has_usable_text
            )
            if (
                page_stayed_textless
                and info.page_number not in unresolved_ocr_pages
                and ocr_mode is OcrMode.NEVER
            ):
                result.pages[-1].warnings.append("page_has_no_text_and_ocr_disabled")

            page = doc[info.page_number - 1]
            result.tables.extend(_extract_tables(page, info.page_number))
            result.images.extend(extract_page_images(doc, page, info.page_number))

    if ocr.engine_ran:
        ocr.elapsed_seconds = round(time.monotonic() - ocr_started, 3)

    result.sections = _extract_sections_safe(path, page_texts, analysis.page_count)
    if not result.sections:
        result.warnings.append("no_section_structure_available")

    result.ocr = ocr
    if ocr_engine_missing:
        # OCR was required by the policy but could not run at all.
        result.status = "partial"
    if unresolved_ocr_pages:
        result.status = "partial"
        result.warnings.append(
            f"pages without text after OCR policy: {sorted(set(unresolved_ocr_pages))}"
        )
    return result


def _extract_sections_safe(
    path: Path, page_texts: dict[int, str], page_count: int
) -> list[ParsedSection]:
    import fitz

    try:
        with fitz.open(path) as doc:
            return _extract_sections(doc, page_texts, page_count)
    except Exception as exc:
        logger.warning("TOC extraction failed: %s", exc)
        return []

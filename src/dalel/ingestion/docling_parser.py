"""Docling-based primary parser for PDF and DOCX.

All Docling imports are lazy: importing this module never loads models.
The first real conversion may download layout/TableFormer models (~500 MB)
and EasyOCR weights; the CLI announces this beforehand.

OCR honesty: ``ocr.engine_ran`` is set only when OCR was actually enabled with
an importable engine, and ``ocr.ocr_pages`` lists only pages that (a) were
scheduled for OCR and (b) actually yielded text in the Docling output.
"""

from __future__ import annotations

import importlib.metadata
import io
import logging
import time
from pathlib import Path
from typing import Any

from dalel.config import MIN_USABLE_CHARS_PER_PAGE, OcrMode
from dalel.ingestion.parsed import (
    OcrOutcome,
    ParsedDocument,
    ParsedImage,
    ParsedPage,
    ParsedSection,
    ParsedTable,
)
from dalel.ingestion.pdf_mode import PdfAnalysis
from dalel.schemas.evidence import BBox

logger = logging.getLogger(__name__)

PARSER_NAME = "docling"

# EasyOCR language coverage relevant to this dataset. Kazakh is not supported
# by EasyOCR; documents declaring it get an explicit warning instead of a
# silent wrong-language OCR claim.
_EASYOCR_SUPPORTED = {"ru", "en"}


class DoclingUnavailableError(RuntimeError):
    """Docling is not importable in this environment."""


class DoclingConversionError(RuntimeError):
    """Docling reported a failed conversion."""


def parser_version() -> str | None:
    try:
        return importlib.metadata.version("docling")
    except importlib.metadata.PackageNotFoundError:
        return None


def _easyocr_available() -> bool:
    try:
        import easyocr  # noqa: F401

        return True
    except Exception:
        return False


def _easyocr_version() -> str | None:
    try:
        return importlib.metadata.version("easyocr")
    except importlib.metadata.PackageNotFoundError:
        return None


def _bbox_from_prov(prov: Any) -> BBox | None:
    bbox = getattr(prov, "bbox", None)
    if bbox is None:
        return None
    origin = getattr(bbox, "coord_origin", None)
    return BBox(
        l=float(bbox.l),
        t=float(bbox.t),
        r=float(bbox.r),
        b=float(bbox.b),
        coord_origin=str(getattr(origin, "value", origin) or "TOPLEFT"),
    )


def _first_prov(item: Any) -> Any | None:
    provs = getattr(item, "prov", None) or []
    return provs[0] if provs else None


def _confidence_dict(result: Any) -> tuple[dict[str, object] | None, str | None]:
    confidence = getattr(result, "confidence", None)
    if confidence is None:
        return None, None
    try:
        dump = confidence.model_dump(mode="json")
        if isinstance(dump, dict) and dump:
            return dump, "docling.ConversionResult.confidence"
    except Exception:
        pass
    return None, None


def _iter_doc_items(document: Any) -> list[tuple[Any, int]]:
    try:
        return [(item, level) for item, level in document.iterate_items()]
    except Exception as exc:
        logger.warning("docling iterate_items failed: %s", exc)
        return []


def _build_sections(document: Any) -> list[ParsedSection]:
    """Heading-delimited sections from the Docling reading order."""
    from docling_core.types.doc import DocItemLabel

    sections: list[ParsedSection] = []
    current: ParsedSection | None = None
    preamble_parts: list[str] = []
    preamble_pages: list[int] = []

    def _pages_of(item: Any) -> list[int]:
        return [
            int(p.page_no) for p in (getattr(item, "prov", None) or []) if p.page_no is not None
        ]

    def _close(section: ParsedSection | None) -> None:
        if section is not None:
            section.text = section.text.strip()
            sections.append(section)

    for item, _level in _iter_doc_items(document):
        text = getattr(item, "text", None)
        if text is None:
            continue
        label = getattr(item, "label", None)
        pages = _pages_of(item)
        if label == DocItemLabel.SECTION_HEADER or label == DocItemLabel.TITLE:
            _close(current)
            current = ParsedSection(
                title=text.strip() or None,
                level=int(getattr(item, "level", 1) or 1),
                page_start=min(pages) if pages else None,
                page_end=max(pages) if pages else None,
                text="",
                warnings=[] if pages else ["heading has no page provenance"],
            )
            continue
        if current is None:
            preamble_parts.append(text)
            preamble_pages.extend(pages)
            continue
        current.text += text + "\n"
        if pages:
            current.page_start = (
                min(pages) if current.page_start is None else min(current.page_start, min(pages))
            )
            current.page_end = (
                max(pages) if current.page_end is None else max(current.page_end, max(pages))
            )

    _close(current)

    if preamble_parts:
        preamble = ParsedSection(
            title=None,
            level=None,
            page_start=min(preamble_pages) if preamble_pages else None,
            page_end=max(preamble_pages) if preamble_pages else None,
            text="\n".join(preamble_parts).strip(),
            warnings=["content before the first heading"],
        )
        sections.insert(0, preamble)
    return sections


def _build_tables(document: Any) -> list[ParsedTable]:
    tables: list[ParsedTable] = []
    for table_item in getattr(document, "tables", []) or []:
        warnings: list[str] = []
        prov = _first_prov(table_item)
        page_number = int(prov.page_no) if prov is not None and prov.page_no is not None else None
        bbox = _bbox_from_prov(prov) if prov is not None else None
        if page_number is None:
            warnings.append("table has no page provenance")
        if bbox is None:
            warnings.append("table has no bbox")

        cells: list[list[str]] = []
        num_rows = 0
        num_cols = 0
        try:
            data = table_item.data
            num_rows = int(getattr(data, "num_rows", 0) or 0)
            num_cols = int(getattr(data, "num_cols", 0) or 0)
            grid = getattr(data, "grid", None) or []
            cells = [[str(getattr(cell, "text", "") or "") for cell in row] for row in grid]
        except Exception as exc:
            warnings.append(f"table grid extraction failed: {exc}")

        caption = None
        try:
            caption_text = table_item.caption_text(document)
            caption = caption_text.strip() or None
        except Exception:
            caption = None

        tables.append(
            ParsedTable(
                page_number=page_number,
                bbox=bbox,
                cells=cells,
                num_rows=num_rows or len(cells),
                num_cols=num_cols or max((len(r) for r in cells), default=0),
                caption=caption,
                warnings=warnings,
            )
        )
    return tables


def _build_images(document: Any) -> list[ParsedImage]:
    images: list[ParsedImage] = []
    for picture in getattr(document, "pictures", []) or []:
        warnings: list[str] = []
        prov = _first_prov(picture)
        page_number = int(prov.page_no) if prov is not None and prov.page_no is not None else None
        bbox = _bbox_from_prov(prov) if prov is not None else None
        if page_number is None:
            warnings.append("picture has no page provenance")
        if bbox is None:
            warnings.append("picture has no bbox")

        png_bytes: bytes | None = None
        width_px: int | None = None
        height_px: int | None = None
        try:
            pil_image = picture.get_image(document)
            if pil_image is not None:
                width_px, height_px = int(pil_image.width), int(pil_image.height)
                buffer = io.BytesIO()
                pil_image.save(buffer, format="PNG")
                png_bytes = buffer.getvalue()
            else:
                warnings.append("picture bytes unavailable from parser")
        except Exception as exc:
            warnings.append(f"picture image extraction failed: {exc}")

        images.append(
            ParsedImage(
                page_number=page_number,
                bbox=bbox,
                width_px=width_px,
                height_px=height_px,
                png_bytes=png_bytes,
                warnings=warnings,
            )
        )
    return images


def _build_pages(
    document: Any, analysis: PdfAnalysis | None, scheduled_ocr: set[int]
) -> tuple[list[ParsedPage], dict[int, int]]:
    """Aggregate item text per page. Returns pages and per-page char counts."""
    page_text: dict[int, list[str]] = {}
    for item in getattr(document, "texts", []) or []:
        text = getattr(item, "text", "") or ""
        if not text:
            continue
        for prov in getattr(item, "prov", None) or []:
            if prov.page_no is None:
                continue
            page_text.setdefault(int(prov.page_no), []).append(text)
            break  # one placement per item is enough for page aggregation

    embedded_by_page = (
        {info.page_number: info for info in analysis.pages} if analysis is not None else {}
    )

    pages: list[ParsedPage] = []
    char_counts: dict[int, int] = {}
    doc_pages = getattr(document, "pages", None) or {}
    page_numbers = sorted(int(number) for number in doc_pages)
    if not page_numbers and analysis is not None:
        page_numbers = [info.page_number for info in analysis.pages]

    for number in page_numbers:
        page_item = doc_pages.get(number)
        size = getattr(page_item, "size", None) if page_item is not None else None
        width = float(size.width) if size is not None else None
        height = float(size.height) if size is not None else None
        info = embedded_by_page.get(number)
        if (width is None or height is None) and info is not None:
            width, height = info.width, info.height

        text = "\n".join(page_text.get(number, []))
        char_counts[number] = len(text.strip())
        pages.append(
            ParsedPage(
                page_number=number,
                width=width,
                height=height,
                rotation=info.rotation if info is not None else None,
                text=text,
                ocr_applied=number in scheduled_ocr and bool(text.strip()),
                has_embedded_text=info.has_usable_text if info is not None else None,
                warnings=[],
            )
        )
    return pages, char_counts


def _convert(path: Path, format_options: dict[Any, Any]) -> Any:
    from docling.datamodel.base_models import ConversionStatus
    from docling.document_converter import DocumentConverter

    converter = DocumentConverter(format_options=format_options)
    result = converter.convert(path, raises_on_error=False)
    if result.status == ConversionStatus.FAILURE or result.document is None:
        errors = "; ".join(
            str(getattr(err, "error_message", err)) for err in getattr(result, "errors", [])
        )
        raise DoclingConversionError(f"docling conversion failed: {errors or 'unknown error'}")
    return result


def parse_pdf_docling(
    path: Path,
    analysis: PdfAnalysis,
    ocr_mode: OcrMode,
    languages: list[str] | None = None,
) -> ParsedDocument:
    """Parse a PDF with Docling, applying the OCR policy."""
    try:
        from docling.datamodel.base_models import ConversionStatus, InputFormat
        from docling.datamodel.pipeline_options import EasyOcrOptions, PdfPipelineOptions
        from docling.document_converter import PdfFormatOption
    except ImportError as exc:  # pragma: no cover - environment-specific
        raise DoclingUnavailableError(f"docling is not importable: {exc}") from exc

    version = parser_version()
    started = time.monotonic()

    candidates = analysis.ocr_candidate_pages
    ocr = OcrOutcome()
    ocr_warnings: list[str] = []

    if ocr_mode is OcrMode.NEVER:
        want_ocr = False
    elif ocr_mode is OcrMode.ALWAYS:
        want_ocr = True
    else:  # AUTO: OCR only when some pages lack usable embedded text
        want_ocr = bool(candidates)

    ocr_engine_missing = False
    easyocr_ok = _easyocr_available() if want_ocr else False
    if want_ocr and not easyocr_ok:
        ocr_warnings.append("ocr_engine_unavailable")
        ocr_engine_missing = True
        want_ocr = False

    unsupported = [lang for lang in (languages or []) if lang.lower() not in _EASYOCR_SUPPORTED]
    if want_ocr and unsupported:
        ocr_warnings.append(
            f"ocr_language_unsupported: {','.join(sorted(unsupported))} (easyocr runs ru+en)"
        )

    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_table_structure = True
    pipeline_options.generate_picture_images = True
    pipeline_options.images_scale = 2.0
    pipeline_options.do_ocr = want_ocr
    if want_ocr:
        pipeline_options.ocr_options = EasyOcrOptions(
            lang=["ru", "en"],
            force_full_page_ocr=(ocr_mode is OcrMode.ALWAYS),
        )
        ocr.engine = "easyocr"
        ocr.engine_version = _easyocr_version()
        ocr.engine_available = True

    result = _convert(path, {InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)})
    document = result.document

    if ocr_mode is OcrMode.ALWAYS and want_ocr:
        scheduled_ocr = {info.page_number for info in analysis.pages}
    elif want_ocr:
        scheduled_ocr = set(candidates)
    else:
        scheduled_ocr = set()

    pages, char_counts = _build_pages(document, analysis, scheduled_ocr)

    if want_ocr:
        ocr.engine_ran = True
        # Honest accounting: an OCR page "happened" only if a page that had no
        # usable embedded text now carries text in the Docling output.
        produced = [
            number
            for number in sorted(scheduled_ocr)
            if char_counts.get(number, 0) >= MIN_USABLE_CHARS_PER_PAGE
        ]
        if ocr_mode is OcrMode.ALWAYS:
            ocr.ocr_pages = sorted(scheduled_ocr)
        else:
            ocr.ocr_pages = produced
        ocr.elapsed_seconds = round(time.monotonic() - started, 3)

    # Keep per-page ocr_applied consistent with the document-level OCR claim.
    ocr_pages_set = set(ocr.ocr_pages)
    for page in pages:
        page.ocr_applied = page.page_number in ocr_pages_set

    unresolved = [
        number for number in candidates if char_counts.get(number, 0) < MIN_USABLE_CHARS_PER_PAGE
    ]

    parsed = ParsedDocument(
        parser_name=PARSER_NAME,
        parser_version=version,
        status="success",
        pages=pages,
        sections=_build_sections(document),
        tables=_build_tables(document),
        images=_build_images(document),
        ocr=ocr,
    )
    parsed.ocr.warnings.extend(ocr_warnings)
    parsed.warnings.extend(analysis.warnings)

    confidence, confidence_source = _confidence_dict(result)
    parsed.confidence = confidence
    parsed.confidence_source = confidence_source

    if result.status == ConversionStatus.PARTIAL_SUCCESS:
        parsed.status = "partial"
        parsed.warnings.append("docling reported partial success")
    if ocr_engine_missing:
        # OCR was required by the policy but no engine could run: the document
        # cannot honestly be called fully extracted.
        parsed.status = "partial"
    if unresolved:
        parsed.status = "partial"
        parsed.warnings.append(f"pages without text after OCR policy: {unresolved}")
        for page in parsed.pages:
            if page.page_number in unresolved:
                page.warnings.append("page_has_no_text_after_ocr_policy")
    return parsed


def parse_docx_docling(path: Path) -> ParsedDocument:
    """Parse a DOCX with Docling (no layout models required for Word input)."""
    try:
        from docling.datamodel.base_models import ConversionStatus, InputFormat
    except ImportError as exc:  # pragma: no cover - environment-specific
        raise DoclingUnavailableError(f"docling is not importable: {exc}") from exc

    result = _convert(path, {})
    document = result.document

    pages, _ = _build_pages(document, None, set())
    parsed = ParsedDocument(
        parser_name=PARSER_NAME,
        parser_version=parser_version(),
        status="success",
        pages=pages,
        sections=_build_sections(document),
        tables=_build_tables(document),
        images=_build_images(document),
        ocr=OcrOutcome(),
    )
    if not pages:
        # DOCX is a flow format: DoclingDocument has no page dict. Keep the full
        # text reachable through pages.jsonl as one pseudo-page with null
        # geometry instead of silently dropping page-level text.
        full_text = "\n".join(
            (getattr(item, "text", "") or "") for item in getattr(document, "texts", []) or []
        ).strip()
        parsed.pages = [
            ParsedPage(
                page_number=1,
                width=None,
                height=None,
                rotation=None,
                text=full_text,
                ocr_applied=False,
                has_embedded_text=bool(full_text),
                warnings=["pseudo-page: docx flow text without page geometry"],
            )
        ]
        parsed.warnings.append(
            "docx flow document exposes no reliable page numbers; a single pseudo-page"
            " carries the full text and provenance is section/table level"
        )
    confidence, confidence_source = _confidence_dict(result)
    parsed.confidence = confidence
    parsed.confidence_source = confidence_source
    if result.status == ConversionStatus.PARTIAL_SUCCESS:
        parsed.status = "partial"
        parsed.warnings.append("docling reported partial success")

    _ = InputFormat  # imported for parity; format options use converter defaults
    return parsed

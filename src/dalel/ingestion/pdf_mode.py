"""PDF page inventory: dimensions, embedded text and digital/scanned/mixed mode.

Uses PyMuPDF only (no Docling, no models). The analysis drives the OCR policy:
in ``auto`` mode only pages without usable embedded text become OCR candidates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dalel.config import MIN_USABLE_CHARS_PER_PAGE


@dataclass
class PdfPageInfo:
    page_number: int  # 1-based
    width: float
    height: float
    rotation: int
    text_chars: int
    has_usable_text: bool
    embedded_text: str
    image_count: int


@dataclass
class PdfAnalysis:
    page_count: int
    mode: str  # digital | scanned | mixed
    pages: list[PdfPageInfo] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ocr_candidate_pages(self) -> list[int]:
        return [p.page_number for p in self.pages if not p.has_usable_text]


def _open_pdf(path: Path) -> Any:
    import fitz  # lazy: PyMuPDF

    return fitz.open(path)


def analyze_pdf(path: Path) -> PdfAnalysis:
    """Inventory every page of a PDF without any OCR or model inference."""
    pages: list[PdfPageInfo] = []
    warnings: list[str] = []

    with _open_pdf(path) as doc:
        if doc.needs_pass:
            raise PermissionError(f"PDF is password-protected: {path}")
        for index, page in enumerate(doc):
            try:
                text = page.get_text("text") or ""
            except Exception as exc:  # per-page extraction failure must not abort
                text = ""
                warnings.append(f"page {index + 1}: embedded text extraction failed: {exc}")
            stripped = text.strip()
            try:
                image_count = len(page.get_images(full=True))
            except Exception:
                image_count = 0
            rect = page.rect
            pages.append(
                PdfPageInfo(
                    page_number=index + 1,
                    width=float(rect.width),
                    height=float(rect.height),
                    rotation=int(page.rotation),
                    text_chars=len(stripped),
                    has_usable_text=len(stripped) >= MIN_USABLE_CHARS_PER_PAGE,
                    embedded_text=text,
                    image_count=image_count,
                )
            )

    usable = sum(1 for p in pages if p.has_usable_text)
    if not pages:
        mode = "scanned"
        warnings.append("PDF has zero pages")
    elif usable == len(pages):
        mode = "digital"
    elif usable == 0:
        mode = "scanned"
    else:
        mode = "mixed"

    return PdfAnalysis(page_count=len(pages), mode=mode, pages=pages, warnings=warnings)

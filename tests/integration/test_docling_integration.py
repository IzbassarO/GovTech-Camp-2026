"""Real Docling/OCR integration tests.

Run with ``uv run pytest -m integration``. The first run may download Docling
layout/TableFormer models and EasyOCR weights; these tests are excluded from
the default ``uv run pytest`` selection.
"""

from pathlib import Path

import pytest

from dalel.config import OcrMode
from dalel.ingestion.pdf_mode import analyze_pdf

pytestmark = [pytest.mark.integration, pytest.mark.slow]


@pytest.fixture(scope="module")
def digital_pdf(tmp_path_factory) -> Path:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from fixtures.builders import make_digital_pdf

    path = tmp_path_factory.mktemp("docling") / "digital.pdf"
    make_digital_pdf(path)
    return path


@pytest.fixture(scope="module")
def scanned_pdf_with_text(tmp_path_factory) -> Path:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from fixtures.builders import make_scanned_pdf

    path = tmp_path_factory.mktemp("docling_ocr") / "scanned.pdf"
    make_scanned_pdf(
        path,
        pages=1,
        render_text="ENVIRONMENTAL PERMIT FIXTURE\nThis scanned page contains raster text.",
    )
    return path


def test_docling_digital_pdf(digital_pdf: Path) -> None:
    from dalel.ingestion.docling_parser import parse_pdf_docling

    analysis = analyze_pdf(digital_pdf)
    assert analysis.mode == "digital"

    parsed = parse_pdf_docling(digital_pdf, analysis, OcrMode.AUTO, ["ru"])
    assert parsed.parser_name == "docling"
    assert parsed.parser_version
    assert parsed.status in {"success", "partial"}
    assert len(parsed.pages) == 2
    joined = "\n".join(page.text for page in parsed.pages)
    assert "Fixture page 1" in joined
    # No OCR may be claimed for a fully digital document in auto mode.
    assert parsed.ocr.engine_ran is False
    assert parsed.ocr.ocr_pages == []


def test_docling_ocr_scanned_pdf(scanned_pdf_with_text: Path) -> None:
    from dalel.ingestion.docling_parser import parse_pdf_docling

    analysis = analyze_pdf(scanned_pdf_with_text)
    assert analysis.mode == "scanned"
    assert analysis.ocr_candidate_pages == [1]

    parsed = parse_pdf_docling(scanned_pdf_with_text, analysis, OcrMode.AUTO, ["ru"])
    assert parsed.ocr.engine == "easyocr"
    assert parsed.ocr.engine_ran is True
    assert parsed.ocr.ocr_pages == [1]
    joined = "\n".join(page.text for page in parsed.pages).upper()
    assert "ENVIRONMENTAL" in joined or "PERMIT" in joined


def test_docling_docx(tmp_path: Path) -> None:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from dalel.ingestion.docling_parser import parse_docx_docling
    from fixtures.builders import make_docx

    path = tmp_path / "summary.docx"
    make_docx(path)
    parsed = parse_docx_docling(path)
    assert parsed.status in {"success", "partial"}
    section_titles = " ".join(section.title or "" for section in parsed.sections)
    assert "Emissions" in section_titles
    assert parsed.tables and parsed.tables[0].cells

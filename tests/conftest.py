"""Shared fixtures: a synthetic repository with the canonical layout.

Unit tests never import Docling. The pipeline's Docling entry points are
monkeypatched with fakes (see ``fake_docling``); real Docling runs only in
``-m integration`` tests.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).parent
REPO_ROOT = TESTS_DIR.parent
sys.path.insert(0, str(TESTS_DIR))

from fixtures.builders import (  # noqa: E402
    PAGE_TEXT,
    make_digital_pdf,
    make_docx,
    make_fake_rar,
    make_manifest_document,
    make_scanned_pdf,
    write_manifest,
)


@dataclass
class TmpRepo:
    root: Path
    manifest_path: Path
    digital_pdf: Path
    scanned_pdf: Path
    docx: Path
    rar: Path
    protocol_pdf: Path

    @property
    def project_id(self) -> str:
        return "project_t1"


@pytest.fixture()
def tmp_repo(tmp_path: Path) -> TmpRepo:
    root = tmp_path
    raw = root / "data" / "raw" / "project_t1"
    raw.mkdir(parents=True)

    digital_pdf = raw / "digital.pdf"
    scanned_pdf = raw / "scanned.pdf"
    docx_path = raw / "summary.docx"
    rar_path = raw / "protocol_archive.rar"
    protocol_pdf = raw / "protocol.pdf"

    make_digital_pdf(digital_pdf)
    make_scanned_pdf(scanned_pdf)
    make_docx(docx_path)
    make_fake_rar(rar_path)
    make_digital_pdf(protocol_pdf, pages=1, with_table=False)

    manifest_path = root / "data" / "manifests" / "projects.jsonl"
    project = {
        "schema_version": "1.0",
        "project_id": "project_t1",
        "source_metadata_path": "data/raw/project_t1/source_metadata.json",
        "source_url": "https://example.invalid/hearing/1",
        "region": "Test Region",
        "industry": "testing",
        "languages": ["ru"],
        "documents": [
            make_manifest_document(root, "project_t1__ndv__001", digital_pdf, "ndv"),
            make_manifest_document(
                root, "project_t1__action_plan__001", scanned_pdf, "action_plan"
            ),
            make_manifest_document(
                root, "project_t1__nontechnical_summary__001", docx_path, "nontechnical_summary"
            ),
            make_manifest_document(
                root,
                "project_t1__archive__001",
                rar_path,
                "archive",
                role="auxiliary_archive",
            ),
            make_manifest_document(
                root,
                "project_t1__hearing_protocol__001",
                protocol_pdf,
                "hearing_protocol",
                role="label_source",
            ),
        ],
    }
    write_manifest(manifest_path, [project])
    (raw / "source_metadata.json").write_text("{}", encoding="utf-8")

    return TmpRepo(
        root=root,
        manifest_path=manifest_path,
        digital_pdf=digital_pdf,
        scanned_pdf=scanned_pdf,
        docx=docx_path,
        rar=rar_path,
        protocol_pdf=protocol_pdf,
    )


@pytest.fixture()
def fake_docling(monkeypatch: pytest.MonkeyPatch):
    """Replace Docling entry points with a lightweight fake parser.

    Returns the factory so tests can inspect call counts or customize output.
    """
    from dalel.ingestion import docling_parser
    from dalel.ingestion.parsed import (
        OcrOutcome,
        ParsedDocument,
        ParsedPage,
        ParsedSection,
        ParsedTable,
    )

    calls: dict[str, int] = {"pdf": 0, "docx": 0}

    def fake_parse_pdf(path, analysis, ocr_mode, languages=None):
        calls["pdf"] += 1
        pages = [
            ParsedPage(
                page_number=info.page_number,
                width=info.width,
                height=info.height,
                rotation=info.rotation,
                text=info.embedded_text or PAGE_TEXT,
                ocr_applied=False,
                has_embedded_text=info.has_usable_text,
            )
            for info in analysis.pages
        ]
        return ParsedDocument(
            parser_name="docling",
            parser_version="fake-2.0",
            status="success",
            pages=pages,
            sections=[
                ParsedSection(
                    title="Fixture Section", level=1, page_start=1, page_end=1, text=PAGE_TEXT
                )
            ],
            tables=[
                ParsedTable(
                    page_number=1,
                    bbox=None,
                    cells=[["a", "b"], ["c", "d"]],
                    num_rows=2,
                    num_cols=2,
                    warnings=["bbox unavailable in fake parser"],
                )
            ],
            ocr=OcrOutcome(),
        )

    def fake_parse_docx(path):
        calls["docx"] += 1
        return ParsedDocument(
            parser_name="docling",
            parser_version="fake-2.0",
            status="success",
            pages=[ParsedPage(page_number=1, text="docx text from fake docling")],
            sections=[ParsedSection(title="Docx Section", level=1, text="docx body")],
            ocr=OcrOutcome(),
        )

    monkeypatch.setattr(docling_parser, "parse_pdf_docling", fake_parse_pdf)
    monkeypatch.setattr(docling_parser, "parse_docx_docling", fake_parse_docx)
    return calls


@pytest.fixture()
def broken_docling(monkeypatch: pytest.MonkeyPatch):
    """Make every Docling entry point fail so the pipeline must fall back."""
    from dalel.ingestion import docling_parser

    def boom(*args, **kwargs):
        raise docling_parser.DoclingConversionError("synthetic docling failure")

    monkeypatch.setattr(docling_parser, "parse_pdf_docling", boom)
    monkeypatch.setattr(docling_parser, "parse_docx_docling", boom)
    return boom

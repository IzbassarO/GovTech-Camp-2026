"""Regression tests for the table validity contract (empty-table blocker).

An independent verifier found 54 empty Docling table items serialized as full
table records (0 rows, 0 cols, no cells, no warning). These tests pin the fix:
empty items are skipped with an ``empty_table_item_skipped`` warning and
counted, valid tables survive unchanged, and the schema rejects invalid records.
"""

import json

import pytest
from pydantic import ValidationError

from dalel.config import INGESTION_SCHEMA_VERSION, OcrMode
from dalel.ingestion.parsed import (
    OcrOutcome,
    ParsedDocument,
    ParsedPage,
    ParsedTable,
    SkippedTableItem,
)
from dalel.ingestion.pipeline import IngestOptions, ingest_documents
from dalel.ingestion.storage import compute_cache_key
from dalel.schemas.evidence import Provenance
from dalel.schemas.table import TableRecord, table_content_is_valid

DOC_ID = "project_t1__ndv__001"
OUT_REL = f"data/processed/model_inputs/project_t1/{DOC_ID}"


def _make_provenance() -> Provenance:
    return Provenance(
        project_id="p",
        document_id="d",
        document_type="ndv",
        role="model_input",
        source_path="data/raw/p/x.pdf",
        source_sha256="a" * 64,
        page_number=1,
        extraction_method="docling",
        parser_name="docling",
        parser_version="test",
        ocr_used=False,
        created_at="2026-01-01T00:00:00+00:00",
    )


@pytest.fixture()
def mixed_tables_docling(monkeypatch):
    """Fake docling: one valid table, one 0x0 empty, one all-blank-cells table,
    plus one parser-side pre-filtered skip (as the real docling parser emits)."""
    from dalel.ingestion import docling_parser

    def fake_parse_pdf(path, analysis, ocr_mode, languages=None):
        pages = [
            ParsedPage(
                page_number=info.page_number,
                width=info.width,
                height=info.height,
                text=info.embedded_text,
                has_embedded_text=info.has_usable_text,
            )
            for info in analysis.pages
        ]
        return ParsedDocument(
            parser_name="docling",
            parser_version="fake-2.0",
            status="success",
            pages=pages,
            tables=[
                ParsedTable(
                    page_number=1,
                    cells=[["substance", "limit"], ["dust", "0.5"]],
                    num_rows=2,
                    num_cols=2,
                ),
                # Case 1: 0x0 empty grid reaching the pipeline (layer-2 filter).
                ParsedTable(page_number=2, cells=[], num_rows=0, num_cols=0),
                # Case 2: has dimensions but every cell is blank after trim.
                ParsedTable(
                    page_number=2,
                    cells=[["", "  "], ["\t", ""]],
                    num_rows=2,
                    num_cols=2,
                ),
            ],
            skipped_empty_tables=[
                # Layer-1 pre-filtered item, as the real docling parser produces.
                SkippedTableItem(
                    page_number=1,
                    reference="#/tables/9",
                    extraction_method="docling",
                    message="docling table item has no rows/columns/cell content",
                )
            ],
            ocr=OcrOutcome(),
        )

    monkeypatch.setattr(docling_parser, "parse_pdf_docling", fake_parse_pdf)
    return fake_parse_pdf


def _ingest_ndv(tmp_repo) -> dict:
    batch = ingest_documents(
        IngestOptions(
            manifest_path=tmp_repo.manifest_path,
            repo_root=tmp_repo.root,
            document_id=DOC_ID,
            ocr_mode=OcrMode.AUTO,
        )
    )
    return {r.document_id: r for r in batch.results}


def test_table_content_is_valid_policy() -> None:
    assert table_content_is_valid(2, 2, [["a", ""], ["", "b"]])
    assert not table_content_is_valid(0, 0, [])
    assert not table_content_is_valid(2, 0, [["a"], ["b"]])
    assert not table_content_is_valid(0, 2, [])
    assert not table_content_is_valid(2, 2, [["", " "], ["\t", ""]])
    assert not table_content_is_valid(1, 1, [])


def test_empty_items_skipped_valid_table_kept(tmp_repo, mixed_tables_docling) -> None:
    results = _ingest_ndv(tmp_repo)
    result = results[DOC_ID]
    # Existing status policy: skipped empty tables are warnings, not failures.
    assert result.status == "success"
    assert result.tables == 1
    assert result.skipped_empty_tables == 3

    out = tmp_repo.root / OUT_REL
    tables = [json.loads(x) for x in (out / "tables.jsonl").read_text().splitlines() if x.strip()]
    assert len(tables) == 1
    assert tables[0]["cells"] == [["substance", "limit"], ["dust", "0.5"]]
    assert tables[0]["table_id"] == f"{DOC_ID}__tab_0001"


def test_skip_warnings_have_required_fields(tmp_repo, mixed_tables_docling) -> None:
    _ingest_ndv(tmp_repo)
    out = tmp_repo.root / OUT_REL
    record = json.loads((out / "document.json").read_text())
    skip_warnings = [w for w in record["warnings"] if w.startswith("empty_table_item_skipped:")]
    assert len(skip_warnings) == 3
    # Code, document_id, page (or null), reference when available, method, message.
    assert any(f"document_id={DOC_ID}" in w for w in skip_warnings)
    assert any("page=1" in w and "ref=#/tables/9" in w for w in skip_warnings)
    assert any("page=2" in w and "ref=null" in w for w in skip_warnings)
    assert all("method=docling" in w for w in skip_warnings)


def test_report_counters(tmp_repo, mixed_tables_docling) -> None:
    _ingest_ndv(tmp_repo)
    out = tmp_repo.root / OUT_REL
    report = json.loads((out / "ingestion_report.json").read_text())
    assert report["table_count"] == 1  # serialized valid tables only
    assert report["serialized_table_count"] == 1
    assert report["skipped_empty_table_items"] == 3
    assert report["detected_table_items"] == 4  # 1 valid + 2 pipeline-filtered + 1 parser skip
    assert report["warning_count"] == len(report["warnings"])
    assert sum(1 for w in report["warnings"] if w.startswith("empty_table_item_skipped:")) == 3


def test_batch_not_stopped_by_empty_tables(tmp_repo, mixed_tables_docling, fake_docling) -> None:
    """Note: mixed_tables_docling overrides the PDF path; DOCX path comes from
    fake_docling. The other documents still complete."""
    batch = ingest_documents(
        IngestOptions(
            manifest_path=tmp_repo.manifest_path,
            repo_root=tmp_repo.root,
            ocr_mode=OcrMode.AUTO,
        )
    )
    results = {r.document_id: r for r in batch.results}
    assert results[DOC_ID].status == "success"
    assert results["project_t1__nontechnical_summary__001"].status == "success"
    assert batch.ok


def test_schema_rejects_invalid_tables() -> None:
    base = dict(
        schema_version=INGESTION_SCHEMA_VERSION,
        table_id="t1",
        page_number=1,
        caption=None,
        provenance=_make_provenance(),
    )
    with pytest.raises(ValidationError):
        TableRecord(**base, num_rows=0, num_cols=0, cells=[])
    with pytest.raises(ValidationError):
        TableRecord(**base, num_rows=2, num_cols=2, cells=[])
    with pytest.raises(ValidationError):
        TableRecord(**base, num_rows=1, num_cols=2, cells=[["", "  "]])
    record = TableRecord(**base, num_rows=1, num_cols=2, cells=[["a", ""]])
    assert record.num_rows == 1


def test_schema_validation_error_becomes_skip_not_crash(tmp_repo, monkeypatch) -> None:
    """Layer-3: even if layer-2 validity passed, a schema rejection must turn
    into a warning, not a document failure."""
    from dalel.ingestion import pipeline as pipeline_module

    monkeypatch.setattr(pipeline_module, "table_content_is_valid", lambda *args: True)

    from dalel.ingestion import docling_parser

    def fake_parse_pdf(path, analysis, ocr_mode, languages=None):
        pages = [
            ParsedPage(
                page_number=info.page_number,
                width=info.width,
                height=info.height,
                text=info.embedded_text,
                has_embedded_text=info.has_usable_text,
            )
            for info in analysis.pages
        ]
        return ParsedDocument(
            parser_name="docling",
            parser_version="fake-2.0",
            status="success",
            pages=pages,
            tables=[ParsedTable(page_number=1, cells=[], num_rows=0, num_cols=0)],
            ocr=OcrOutcome(),
        )

    monkeypatch.setattr(docling_parser, "parse_pdf_docling", fake_parse_pdf)
    results = _ingest_ndv(tmp_repo)
    result = results[DOC_ID]
    assert result.status == "success"
    assert result.tables == 0
    assert result.skipped_empty_tables == 1
    out = tmp_repo.root / OUT_REL
    record = json.loads((out / "document.json").read_text())
    assert any("rejected by schema validation" in w for w in record["warnings"])


def test_cache_key_changes_with_output_version() -> None:
    identities = [("docling", "2.112.0")]
    current = compute_cache_key("a" * 64, identities, "auto")
    old = compute_cache_key("a" * 64, identities, "auto", schema_version="1.0.0")
    explicit_current = compute_cache_key(
        "a" * 64, identities, "auto", schema_version=INGESTION_SCHEMA_VERSION
    )
    assert current == explicit_current  # default is the current output version
    assert current != old  # bumping the version reproducibly invalidates caches
    assert INGESTION_SCHEMA_VERSION == "1.1.0"

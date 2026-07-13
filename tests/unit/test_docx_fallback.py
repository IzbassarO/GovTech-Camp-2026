import json

from dalel.config import OcrMode
from dalel.ingestion.docx_fallback import parse_docx_fallback
from dalel.ingestion.pipeline import IngestOptions, ingest_documents


def test_docx_fallback_parses_fixture(tmp_repo) -> None:
    parsed = parse_docx_fallback(tmp_repo.docx)
    assert parsed.parser_name == "python-docx"
    assert parsed.status == "success"

    titles = [section.title for section in parsed.sections]
    assert "Fixture Summary" in titles
    assert "Emissions" in titles

    assert len(parsed.tables) == 1
    assert parsed.tables[0].cells[1] == ["dust", "0.5"]
    assert parsed.tables[0].page_number is None
    assert any("no page number" in w for w in parsed.tables[0].warnings)

    assert parsed.pages[0].text  # pseudo-page carries the flow text


def test_docx_pipeline_fallback_used_when_docling_fails(tmp_repo, broken_docling) -> None:
    options = IngestOptions(
        manifest_path=tmp_repo.manifest_path,
        repo_root=tmp_repo.root,
        document_id="project_t1__nontechnical_summary__001",
        ocr_mode=OcrMode.AUTO,
    )
    batch = ingest_documents(options)
    result = batch.results[0]
    assert result.status == "success"
    assert result.parser_name == "python-docx"
    assert result.fallback_used

    document_json = (
        tmp_repo.root
        / "data/processed/model_inputs/project_t1"
        / "project_t1__nontechnical_summary__001/document.json"
    )
    record = json.loads(document_json.read_text(encoding="utf-8"))
    assert record["document_mode"] == "docx_flow"
    assert record["parser_name"] == "python-docx"
    # DOCX flow format: no invented page geometry.
    pages_path = document_json.parent / "pages.jsonl"
    page = json.loads(pages_path.read_text(encoding="utf-8").splitlines()[0])
    assert page["width"] is None
    assert any("pseudo-page" in w for w in page["warnings"])

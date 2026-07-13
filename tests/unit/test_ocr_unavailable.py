import json

from dalel.config import OcrMode
from dalel.ingestion.pipeline import IngestOptions, ingest_documents


def test_ocr_unavailable_degrades_to_partial(tmp_repo, broken_docling, monkeypatch) -> None:
    """Scanned PDF + no OCR engine anywhere: the pipeline must not crash,
    must fall back to PyMuPDF, produce ``partial`` and record
    ``ocr_engine_unavailable``."""
    from dalel.ingestion import pymupdf_fallback

    monkeypatch.setattr(pymupdf_fallback, "_tesseract_available", lambda: False)

    options = IngestOptions(
        manifest_path=tmp_repo.manifest_path,
        repo_root=tmp_repo.root,
        document_id="project_t1__action_plan__001",
        ocr_mode=OcrMode.AUTO,
    )
    batch = ingest_documents(options)
    result = batch.results[0]
    assert result.status == "partial"
    assert result.parser_name == "pymupdf"

    out_dir = tmp_repo.root / "data/processed/model_inputs/project_t1/project_t1__action_plan__001"
    record = json.loads((out_dir / "document.json").read_text(encoding="utf-8"))
    assert record["extraction_status"] == "partial"
    assert record["document_mode"] == "scanned"
    ocr = record["ocr"]
    assert ocr["engine_ran"] is False
    assert ocr["ocr_pages"] == []
    assert "ocr_engine_unavailable" in ocr["warnings"]
    assert ocr["candidate_pages"] == [1, 2]


def test_ocr_always_with_engine_unavailable_is_partial(
    tmp_repo, broken_docling, monkeypatch
) -> None:
    """--ocr always explicitly demands OCR; a missing engine may not be
    silently reported as full success even on a digital document."""
    from dalel.ingestion import pymupdf_fallback

    monkeypatch.setattr(pymupdf_fallback, "_tesseract_available", lambda: False)

    options = IngestOptions(
        manifest_path=tmp_repo.manifest_path,
        repo_root=tmp_repo.root,
        document_id="project_t1__ndv__001",  # digital PDF
        ocr_mode=OcrMode.ALWAYS,
    )
    batch = ingest_documents(options)
    result = batch.results[0]
    assert result.status == "partial"

    out_dir = tmp_repo.root / "data/processed/model_inputs/project_t1/project_t1__ndv__001"
    record = json.loads((out_dir / "document.json").read_text(encoding="utf-8"))
    assert "ocr_engine_unavailable" in record["ocr"]["warnings"]
    # OCR warnings must be visible at the document level too.
    assert any("ocr_engine_unavailable" in w for w in record["warnings"])
    report = json.loads((out_dir / "ingestion_report.json").read_text(encoding="utf-8"))
    assert report["warning_count"] >= 1


def test_ocr_never_mode_skips_ocr_without_partial_claim(tmp_repo, broken_docling) -> None:
    options = IngestOptions(
        manifest_path=tmp_repo.manifest_path,
        repo_root=tmp_repo.root,
        document_id="project_t1__action_plan__001",
        ocr_mode=OcrMode.NEVER,
    )
    batch = ingest_documents(options)
    result = batch.results[0]
    # OCR was explicitly disabled: no engine claim may appear.
    out_dir = tmp_repo.root / "data/processed/model_inputs/project_t1/project_t1__action_plan__001"
    record = json.loads((out_dir / "document.json").read_text(encoding="utf-8"))
    assert record["ocr"]["engine_ran"] is False
    assert record["ocr"]["mode"] == "never"
    assert result.ocr_pages == 0

import json
from pathlib import Path

from dalel.config import OcrMode
from dalel.ingestion.pipeline import IngestOptions, ingest_documents


def _options(tmp_repo, **overrides) -> IngestOptions:
    defaults = dict(
        manifest_path=tmp_repo.manifest_path,
        repo_root=tmp_repo.root,
        ocr_mode=OcrMode.AUTO,
    )
    defaults.update(overrides)
    return IngestOptions(**defaults)


def _result_map(batch):
    return {result.document_id: result for result in batch.results}


def test_batch_default_selection(tmp_repo, fake_docling) -> None:
    batch = ingest_documents(_options(tmp_repo))
    results = _result_map(batch)

    assert results["project_t1__ndv__001"].status == "success"
    assert results["project_t1__nontechnical_summary__001"].status == "success"
    assert results["project_t1__archive__001"].status == "skipped"
    assert results["project_t1__archive__001"].reason == "auxiliary_archive_never_ingested"
    assert results["project_t1__hearing_protocol__001"].status == "skipped"
    assert results["project_t1__hearing_protocol__001"].reason == "excluded_by_leakage_boundary"

    # Label sources must never appear under model_inputs.
    model_inputs = tmp_repo.root / "data" / "processed" / "model_inputs" / "project_t1"
    assert (model_inputs / "project_t1__ndv__001" / "document.json").is_file()
    assert not (model_inputs / "project_t1__hearing_protocol__001").exists()
    label_sources = tmp_repo.root / "data" / "processed" / "label_sources"
    assert not label_sources.exists()


def test_label_source_written_to_separate_tree(tmp_repo, fake_docling) -> None:
    batch = ingest_documents(_options(tmp_repo, include_label_sources=True))
    results = _result_map(batch)
    assert results["project_t1__hearing_protocol__001"].status == "success"

    label_dir = (
        tmp_repo.root
        / "data"
        / "processed"
        / "label_sources"
        / "project_t1"
        / "project_t1__hearing_protocol__001"
    )
    assert (label_dir / "document.json").is_file()
    model_inputs = tmp_repo.root / "data" / "processed" / "model_inputs" / "project_t1"
    assert not (model_inputs / "project_t1__hearing_protocol__001").exists()
    # Archive is skipped even with the flag.
    assert results["project_t1__archive__001"].status == "skipped"

    # The model_inputs project summary must record the label source only as a
    # skip entry: no success status and no pointer into the label_sources tree.
    summary = json.loads((model_inputs / "project.json").read_text(encoding="utf-8"))
    entry = next(
        d for d in summary["documents"] if d["document_id"] == "project_t1__hearing_protocol__001"
    )
    assert entry["status"] == "skipped"
    assert "label_sources" not in str(entry.get("output_dir") or "")


def test_missing_file_fails_without_stopping_batch(tmp_repo, fake_docling) -> None:
    tmp_repo.digital_pdf.unlink()
    batch = ingest_documents(_options(tmp_repo))
    results = _result_map(batch)
    assert results["project_t1__ndv__001"].status == "failed"
    assert results["project_t1__ndv__001"].reason == "file_missing"
    # The rest of the batch still completed.
    assert results["project_t1__nontechnical_summary__001"].status == "success"


def test_sha_mismatch_fails_document(tmp_repo, fake_docling) -> None:
    tmp_repo.digital_pdf.write_bytes(b"%PDF-1.4 tampered content")
    batch = ingest_documents(_options(tmp_repo))
    results = _result_map(batch)
    assert results["project_t1__ndv__001"].status == "failed"
    assert results["project_t1__ndv__001"].reason == "sha256_mismatch"
    out_dir = tmp_repo.root / "data/processed/model_inputs/project_t1/project_t1__ndv__001"
    assert not out_dir.exists()


def test_raw_file_unchanged_after_ingestion(tmp_repo, fake_docling) -> None:
    before = tmp_repo.digital_pdf.read_bytes()
    ingest_documents(_options(tmp_repo))
    assert tmp_repo.digital_pdf.read_bytes() == before

    report_path = (
        tmp_repo.root
        / "data/processed/model_inputs/project_t1/project_t1__ndv__001/ingestion_report.json"
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["hash_unchanged"] is True
    assert report["raw_hash_before"] == report["raw_hash_after"]


def test_stable_document_id_from_manifest(tmp_repo, fake_docling) -> None:
    ingest_documents(_options(tmp_repo))
    document_json = (
        tmp_repo.root / "data/processed/model_inputs/project_t1/project_t1__ndv__001/document.json"
    )
    record = json.loads(document_json.read_text(encoding="utf-8"))
    assert record["document_id"] == "project_t1__ndv__001"
    assert record["project_id"] == "project_t1"
    assert (
        record["source_sha256"]
        == json.loads(tmp_repo.manifest_path.read_text(encoding="utf-8").splitlines()[0])[
            "documents"
        ][0]["sha256"]
    )


def test_repeated_run_uses_cache(tmp_repo, fake_docling) -> None:
    first = ingest_documents(_options(tmp_repo))
    assert _result_map(first)["project_t1__ndv__001"].status == "success"
    assert fake_docling["pdf"] >= 1
    calls_after_first = fake_docling["pdf"]

    second = ingest_documents(_options(tmp_repo))
    results = _result_map(second)
    assert results["project_t1__ndv__001"].status == "skipped_cached"
    assert results["project_t1__ndv__001"].reason == "cache_key_match"
    assert fake_docling["pdf"] == calls_after_first  # parser not called again


def test_force_reprocesses(tmp_repo, fake_docling) -> None:
    ingest_documents(_options(tmp_repo))
    calls_after_first = fake_docling["pdf"]
    batch = ingest_documents(_options(tmp_repo, force=True))
    results = _result_map(batch)
    assert results["project_t1__ndv__001"].status == "success"
    assert fake_docling["pdf"] > calls_after_first


def test_cache_invalidated_by_ocr_mode(tmp_repo, fake_docling) -> None:
    ingest_documents(_options(tmp_repo))
    batch = ingest_documents(_options(tmp_repo, ocr_mode=OcrMode.NEVER))
    results = _result_map(batch)
    assert results["project_t1__ndv__001"].status == "success"  # reprocessed, not cached


def test_parser_fallback_on_docling_failure(tmp_repo, broken_docling) -> None:
    batch = ingest_documents(_options(tmp_repo, ocr_mode=OcrMode.NEVER))
    results = _result_map(batch)
    ndv = results["project_t1__ndv__001"]
    assert ndv.status == "success"
    assert ndv.parser_name == "pymupdf"
    assert ndv.fallback_used

    report_path = (
        tmp_repo.root
        / "data/processed/model_inputs/project_t1/project_t1__ndv__001/ingestion_report.json"
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["fallback_used"] is True
    attempts = {a["parser_name"]: a["status"] for a in report["parser_attempts"]}
    assert attempts["docling"] == "failed"
    assert attempts["pymupdf"] == "success"


def test_one_document_failure_does_not_stop_batch(tmp_repo, monkeypatch, fake_docling) -> None:
    from dalel.ingestion import pipeline

    original = pipeline._parse_pdf_with_fallback

    def explode_on_ndv(local_path: Path, analysis, ocr_mode, languages):
        if local_path.name == "digital.pdf":
            raise RuntimeError("synthetic catastrophic parser bug")
        return original(local_path, analysis, ocr_mode, languages)

    monkeypatch.setattr(pipeline, "_parse_pdf_with_fallback", explode_on_ndv)
    batch = ingest_documents(_options(tmp_repo))
    results = _result_map(batch)
    assert results["project_t1__ndv__001"].status == "failed"
    assert results["project_t1__ndv__001"].reason == "unexpected_error"
    assert results["project_t1__nontechnical_summary__001"].status == "success"


def test_page_provenance_recorded(tmp_repo, fake_docling) -> None:
    ingest_documents(_options(tmp_repo))
    pages_path = (
        tmp_repo.root / "data/processed/model_inputs/project_t1/project_t1__ndv__001/pages.jsonl"
    )
    lines = pages_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    page = json.loads(lines[0])
    provenance = page["provenance"]
    assert provenance["project_id"] == "project_t1"
    assert provenance["document_id"] == "project_t1__ndv__001"
    assert provenance["page_number"] == 1
    assert provenance["source_path"] == "data/raw/project_t1/digital.pdf"
    assert len(provenance["source_sha256"]) == 64
    assert provenance["parser_name"] == "docling"
    assert provenance["created_at"]
    assert page["width"] and page["height"]


def test_bbox_null_handling(tmp_repo, fake_docling) -> None:
    ingest_documents(_options(tmp_repo))
    tables_path = (
        tmp_repo.root / "data/processed/model_inputs/project_t1/project_t1__ndv__001/tables.jsonl"
    )
    table = json.loads(tables_path.read_text(encoding="utf-8").splitlines()[0])
    assert table["provenance"]["bbox"] is None
    assert any("bbox" in warning for warning in table["warnings"])


def test_project_summary_written(tmp_repo, fake_docling) -> None:
    ingest_documents(_options(tmp_repo))
    summary_path = tmp_repo.root / "data/processed/model_inputs/project_t1/project.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["project_id"] == "project_t1"
    assert summary["manifest_document_count"] == 5
    statuses = {d["document_id"]: d["status"] for d in summary["documents"]}
    assert statuses["project_t1__ndv__001"] == "success"
    assert statuses["project_t1__archive__001"] == "skipped"


def test_document_id_filter_unknown_id(tmp_repo, fake_docling) -> None:
    import pytest

    with pytest.raises(ValueError, match="not present in manifest"):
        ingest_documents(_options(tmp_repo, document_id="no_such_doc"))


def test_unsafe_document_id_refused(tmp_repo, fake_docling) -> None:
    lines = tmp_repo.manifest_path.read_text(encoding="utf-8").splitlines()
    project = json.loads(lines[0])
    project["documents"][0]["document_id"] = "../escape_attempt"
    tmp_repo.manifest_path.write_text(json.dumps(project) + "\n", encoding="utf-8")

    batch = ingest_documents(_options(tmp_repo))
    results = _result_map(batch)
    escaped = results["../escape_attempt"]
    assert escaped.status == "failed"
    assert escaped.reason == "unsafe_identifier"
    # Nothing may be written outside the intended tree.
    assert not (tmp_repo.root / "data" / "processed" / "escape_attempt").exists()


def test_skipped_cached_keeps_on_disk_summary_record(tmp_repo, fake_docling) -> None:
    ingest_documents(_options(tmp_repo))
    second = ingest_documents(_options(tmp_repo))
    assert _result_map(second)["project_t1__ndv__001"].status == "skipped_cached"

    summary_path = tmp_repo.root / "data/processed/model_inputs/project_t1/project.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    entry = next(d for d in summary["documents"] if d["document_id"] == "project_t1__ndv__001")
    # The richer on-disk success record survives a cached rerun.
    assert entry["status"] == "success"


def test_stale_tmp_dirs_ignored_in_summary(tmp_repo, fake_docling) -> None:
    ingest_documents(_options(tmp_repo))
    project_dir = tmp_repo.root / "data/processed/model_inputs/project_t1"
    stale = project_dir / ".tmp__project_t1__ndv__001__deadbeef"
    stale.mkdir()
    (stale / "document.json").write_text(
        '{"document_id": "ghost__doc", "extraction_status": "success"}', encoding="utf-8"
    )

    ingest_documents(_options(tmp_repo, document_id="project_t1__ndv__001", force=True))
    summary = json.loads((project_dir / "project.json").read_text(encoding="utf-8"))
    ids = {d["document_id"] for d in summary["documents"]}
    assert "ghost__doc" not in ids

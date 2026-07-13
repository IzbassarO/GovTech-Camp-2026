from typer.testing import CliRunner

from dalel.cli import app
from dalel.ingestion.reports import BatchResult, DocumentResult

runner = CliRunner()


def test_ingest_cli_nonzero_when_batch_produces_no_accounted_result(tmp_repo, monkeypatch) -> None:
    from dalel.ingestion import pipeline

    monkeypatch.setattr(
        pipeline,
        "ingest_documents",
        lambda options: BatchResult(started_at="2026-07-13T00:00:00+00:00"),
    )

    result = runner.invoke(
        app,
        ["ingest", "--manifest", str(tmp_repo.manifest_path), "--project-id", "project_t1"],
    )

    assert result.exit_code == 1
    assert "Totals: nothing selected" in result.output


def test_ingest_cli_zero_for_expected_cache_only_run(tmp_repo, monkeypatch) -> None:
    from dalel.ingestion import pipeline

    cached = DocumentResult(
        project_id="project_t1",
        document_id="project_t1__ndv__001",
        document_type="ndv",
        role="model_input",
        status="skipped_cached",
        reason="cache_key_match",
    )
    monkeypatch.setattr(
        pipeline,
        "ingest_documents",
        lambda options: BatchResult(started_at="2026-07-13T00:00:00+00:00", results=[cached]),
    )

    result = runner.invoke(
        app,
        ["ingest", "--manifest", str(tmp_repo.manifest_path), "--document-id", cached.document_id],
    )

    assert result.exit_code == 0
    assert "skipped_cached=1" in result.output


def test_ingest_cli_nonzero_for_unexpected_skip(tmp_repo, monkeypatch) -> None:
    from dalel.ingestion import pipeline

    unsupported = DocumentResult(
        project_id="project_t1",
        document_id="project_t1__ndv__001",
        document_type="ndv",
        role="model_input",
        status="skipped",
        reason="unsupported_file_format",
    )
    monkeypatch.setattr(
        pipeline,
        "ingest_documents",
        lambda options: BatchResult(started_at="2026-07-13T00:00:00+00:00", results=[unsupported]),
    )

    result = runner.invoke(
        app,
        [
            "ingest",
            "--manifest",
            str(tmp_repo.manifest_path),
            "--document-id",
            unsupported.document_id,
        ],
    )

    assert result.exit_code == 1
    assert "unsupported_file_format" in result.output


def test_ingest_cli_nonzero_and_reports_errors_for_failed_document(tmp_repo, monkeypatch) -> None:
    from dalel.ingestion import pipeline

    failed = DocumentResult(
        project_id="project_t1",
        document_id="project_t1__ndv__001",
        document_type="ndv",
        role="model_input",
        status="failed",
        reason="unexpected_error",
        errors=["RuntimeError: synthetic failure"],
    )
    monkeypatch.setattr(
        pipeline,
        "ingest_documents",
        lambda options: BatchResult(started_at="2026-07-13T00:00:00+00:00", results=[failed]),
    )

    result = runner.invoke(
        app,
        ["ingest", "--manifest", str(tmp_repo.manifest_path), "--document-id", failed.document_id],
    )

    assert result.exit_code == 1
    assert "reason=unexpected_error" in result.output
    assert "errors=1" in result.output

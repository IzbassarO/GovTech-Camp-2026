import json
import shutil
from pathlib import Path

from typer.testing import CliRunner

from dalel.cli import app
from dalel.ingestion.reports import BatchResult, DocumentResult

runner = CliRunner()


def _meta_args(output: Path) -> list[str]:
    return [
        "--p1",
        "data/results/p1/v1",
        "--p2",
        "data/results/p2/v1",
        "--p3",
        "data/results/p3/v1",
        "--p4",
        "data/results/p4/v1",
        "--output",
        str(output),
    ]


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


def test_run_meta_cli_reports_deterministic_order_and_honest_limits(tmp_path: Path) -> None:
    output = tmp_path / "meta"
    result = runner.invoke(app, ["run-meta", *_meta_args(output)])

    assert result.exit_code == 0, result.output
    assert "Meta complete: projects=4" in result.output
    assert result.output.index("project_003_bayterek") < result.output.index(
        "project_004_sintez_ural"
    )
    assert "score=26 level=moderate" in result.output
    assert "P2 contribution is discounted and bounded" in result.output
    assert "Calibration/SHAP: unavailable" in result.output
    rows = [
        json.loads(line)
        for line in (output / "project_assessments.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert all(row["calibrated_probability"] is None for row in rows)
    assert all(row["shap_contributions"] is None for row in rows)


def test_validate_meta_cli_accepts_fresh_output(tmp_path: Path) -> None:
    output = tmp_path / "meta"
    run_result = runner.invoke(app, ["run-meta", *_meta_args(output)])
    assert run_result.exit_code == 0, run_result.output

    result = runner.invoke(app, ["validate-meta", *_meta_args(output)])
    assert result.exit_code == 0, result.output
    assert "Meta outputs status: VALID" in result.output
    assert "Errors: 0" in result.output


def test_run_meta_cli_fail_on_review_priority_level(tmp_path: Path) -> None:
    output = tmp_path / "meta"
    result = runner.invoke(
        app,
        ["run-meta", *_meta_args(output), "--fail-on", "moderate"],
    )

    assert result.exit_code == 1
    assert "FAIL-ON: 1 project(s) at review priority >= moderate" in result.output
    assert (output / "project_assessments.jsonl").is_file()


def test_run_meta_cli_rejects_invalid_fail_on_without_traceback(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["run-meta", *_meta_args(tmp_path / "meta"), "--fail-on", "critical"],
    )

    assert result.exit_code == 2
    assert "--fail-on must be one of low, moderate, elevated, high" in result.output
    assert "Traceback" not in result.output


def test_run_meta_cli_rejects_duplicated_upstream_finding_without_traceback(
    tmp_path: Path,
) -> None:
    inputs = tmp_path / "inputs"
    for pillar in ("p1", "p2", "p3", "p4"):
        shutil.copytree(Path("data/results") / pillar / "v1", inputs / pillar)
    findings_path = inputs / "p1" / "findings.jsonl"
    findings = [
        json.loads(line) for line in findings_path.read_text(encoding="utf-8").splitlines() if line
    ]
    findings.append(dict(findings[0]))
    findings_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in findings), encoding="utf-8"
    )

    output = tmp_path / "meta"
    result = runner.invoke(
        app,
        [
            "run-meta",
            "--p1",
            str(inputs / "p1"),
            "--p2",
            str(inputs / "p2"),
            "--p3",
            str(inputs / "p3"),
            "--p4",
            str(inputs / "p4"),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 1
    assert "ERROR:" in result.output
    assert "duplicate" in result.output
    assert "Traceback" not in result.output
    assert not output.exists()


def test_run_meta_cli_expected_input_error_is_concise(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    result = runner.invoke(
        app,
        [
            "run-meta",
            "--p1",
            str(missing / "p1"),
            "--p2",
            str(missing / "p2"),
            "--p3",
            str(missing / "p3"),
            "--p4",
            str(missing / "p4"),
            "--output",
            str(tmp_path / "meta"),
        ],
    )

    assert result.exit_code == 1
    assert "ERROR: no P1--P4 artifact directories are available" in result.output
    assert "Traceback" not in result.output

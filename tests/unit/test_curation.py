"""Tests for the Curated Dataset v1 builder and validator."""

import json
from pathlib import Path

import pytest

from dalel.curation.builder import (
    CuratedBuildError,
    CurateOptions,
    build_curated_dataset,
    compute_input_fingerprint,
)
from dalel.curation.validation import validate_curated_dataset
from dalel.ingestion.hashing import sha256_file
from fixtures.curation_builders import (
    DOC_LABEL,
    DOC_LEGACY,
    DOC_NATIVE,
    PROJECT_ID,
    make_processed_repo,
)


@pytest.fixture()
def repo(tmp_path: Path) -> dict[str, Path]:
    paths = make_processed_repo(tmp_path)
    paths["root"] = tmp_path
    paths["output"] = tmp_path / "data" / "curated" / "v1"
    return paths


def _options(
    repo: dict[str, Path], force: bool = False, output: Path | None = None
) -> CurateOptions:
    return CurateOptions(
        input_root=repo["processed"],
        output_dir=output or repo["output"],
        repo_root=repo["root"],
        manifest_path=repo["manifest"],
        annotations_root=repo["annotations_root"],
        force=force,
    )


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _snapshot(root: Path) -> dict[str, tuple[str, int]]:
    return {
        p.relative_to(root).as_posix(): (sha256_file(p), p.stat().st_mtime_ns)
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_build_and_validate_roundtrip(repo) -> None:
    result = build_curated_dataset(_options(repo))
    assert result.status == "success"
    assert result.input_fingerprint
    validation = validate_curated_dataset(repo["output"], repo["root"])
    assert validation.ok, validation.errors
    assert validation.counts["documents"] == 2
    assert validation.counts["weak_findings"] == 1
    assert validation.counts["physical_images"] == 2


def test_physical_images_copied_with_checksums(repo) -> None:
    build_curated_dataset(_options(repo))
    images = _read_jsonl(repo["output"] / "images.jsonl")
    assert len(images) == 2
    for record in images:
        curated_path = record["curated_image_path"]
        assert curated_path.startswith(f"images/{PROJECT_ID}/")
        physical = repo["output"] / curated_path
        assert physical.is_file() and physical.stat().st_size > 0
        assert sha256_file(physical) == record["image_sha256"]
        assert record["image_size_bytes"] == physical.stat().st_size
        assert record["source_image_path"].startswith("data/processed/")

    # checksums.jsonl covers the physical images too.
    checksum_files = {r["file"] for r in _read_jsonl(repo["output"] / "checksums.jsonl")}
    for record in images:
        assert record["curated_image_path"] in checksum_files


def test_no_label_source_image_leakage(repo) -> None:
    build_curated_dataset(_options(repo))
    images_root = repo["output"] / "images"
    copied_docs = {p.name for p in (images_root / PROJECT_ID).iterdir()}
    assert copied_docs == {DOC_LEGACY, DOC_NATIVE}
    assert DOC_LABEL not in copied_docs


def test_missing_processed_image_blocks_build(repo) -> None:
    (repo["legacy_dir"] / "images" / "img_0001.png").unlink()
    result = build_curated_dataset(_options(repo))
    assert result.status == "failed"
    assert any("physical image missing" in e for e in result.errors)
    assert not repo["output"].exists()  # nothing written on failure


def test_mixed_schema_normalization(repo) -> None:
    build_curated_dataset(_options(repo))
    documents = {d["document_id"]: d for d in _read_jsonl(repo["output"] / "documents.jsonl")}
    legacy = documents[DOC_LEGACY]
    assert legacy["ingestion_schema_version"] == "1.0.0"
    assert "legacy_report_counters_inferred" in legacy["normalization_warnings"]
    assert legacy["serialized_table_count"] == 1
    assert legacy["detected_table_items"] == 1
    assert legacy["skipped_empty_table_items"] == 0
    native = documents[DOC_NATIVE]
    assert native["normalization_warnings"] == []
    assert native["detected_table_items"] == 2
    assert native["skipped_empty_table_items"] == 1


def test_invalid_table_blocks_build_without_touching_output(repo) -> None:
    tables_path = repo["legacy_dir"] / "tables.jsonl"
    record = json.loads(tables_path.read_text().splitlines()[0])
    record["num_rows"] = 0
    record["num_cols"] = 0
    record["cells"] = []
    tables_path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")

    result = build_curated_dataset(_options(repo))
    assert result.status == "failed"
    assert any("table validity contract" in e for e in result.errors)
    # Atomicity: a failed build writes NOTHING to the output location.
    assert not repo["output"].exists()


def test_invalid_label_source_table_also_blocks(repo) -> None:
    tables_path = repo["label_dir"] / "tables.jsonl"
    record = json.loads(tables_path.read_text().splitlines()[0])
    record["cells"] = [["", ""], ["", ""]]
    tables_path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    result = build_curated_dataset(_options(repo))
    assert result.status == "failed"
    assert not repo["output"].exists()


def test_failed_build_preserves_existing_dataset_bytes_and_mtimes(repo) -> None:
    """Verifier blocker B: a failed rebuild must leave every byte and mtime of
    the previous valid dataset untouched, including build_report.json."""
    build_curated_dataset(_options(repo))
    before = _snapshot(repo["output"])

    tables_path = repo["legacy_dir"] / "tables.jsonl"
    record = json.loads(tables_path.read_text().splitlines()[0])
    record["cells"] = []
    record["num_rows"] = 0
    record["num_cols"] = 0
    tables_path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")

    result = build_curated_dataset(_options(repo, force=True))
    assert result.status == "failed"
    after = _snapshot(repo["output"])
    assert before == after  # bytes AND mtimes identical
    assert not list(repo["output"].parent.glob(".tmp__*"))


def test_leakage_separation_and_weak_label_isolation(repo) -> None:
    build_curated_dataset(_options(repo))
    documents = _read_jsonl(repo["output"] / "documents.jsonl")
    assert {d["document_id"] for d in documents} == {DOC_LEGACY, DOC_NATIVE}
    for name in ("pages.jsonl", "sections.jsonl", "tables.jsonl", "images.jsonl"):
        for record in _read_jsonl(repo["output"] / name):
            assert record["provenance"]["role"] == "model_input"
            assert record["provenance"]["document_id"] != DOC_LABEL
    findings = _read_jsonl(repo["output"] / "weak_findings.jsonl")
    assert findings[0]["source_document_id"] == DOC_LABEL
    assert findings[0]["expert_verified"] is False


def test_provenance_tamper_blocks_build(repo) -> None:
    pages_path = repo["legacy_dir"] / "pages.jsonl"
    record = json.loads(pages_path.read_text().splitlines()[0])
    record["provenance"]["source_sha256"] = "f" * 64
    pages_path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    result = build_curated_dataset(_options(repo))
    assert result.status == "failed"
    assert any("source_sha256 mismatch" in e for e in result.errors)


def test_machine_readable_schemas_complete(repo) -> None:
    from dalel.curation.reports import RECORD_MODELS

    build_curated_dataset(_options(repo))
    schema = json.loads((repo["output"] / "schema.json").read_text(encoding="utf-8"))
    files = schema["files"]
    for name in RECORD_MODELS:
        entry = files[name]
        assert "properties" in entry, name
        assert "type" in entry, name
        assert "required" in entry, name
    # Nested/curated fields are present in the generated schemas.
    assert "record_ref" in files["pages.jsonl"]["properties"]
    assert "curated_image_path" in files["images.jsonl"]["properties"]
    assert "$defs" in files["pages.jsonl"]  # nested Provenance/RecordRef definitions


def test_validator_rejects_incomplete_schema(repo) -> None:
    build_curated_dataset(_options(repo))
    schema_path = repo["output"] / "schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema["files"]["pages.jsonl"] = {"description": "text only"}
    schema_path.write_text(json.dumps(schema, ensure_ascii=False), encoding="utf-8")
    validation = validate_curated_dataset(repo["output"], repo["root"])
    assert any("no machine-readable JSON Schema" in e for e in validation.errors)


def test_image_checksum_mismatch_blocks_validation(repo) -> None:
    build_curated_dataset(_options(repo))
    images = _read_jsonl(repo["output"] / "images.jsonl")
    physical = repo["output"] / images[0]["curated_image_path"]
    physical.write_bytes(b"\x89PNG\r\n\x1a\nTAMPERED")
    validation = validate_curated_dataset(repo["output"], repo["root"])
    assert any("image checksum mismatch" in e for e in validation.errors)


def test_path_traversal_rejected_by_validator(repo) -> None:
    build_curated_dataset(_options(repo))
    images_path = repo["output"] / "images.jsonl"
    records = _read_jsonl(images_path)
    records[0]["curated_image_path"] = "../../../evil.png"
    images_path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8"
    )
    validation = validate_curated_dataset(repo["output"], repo["root"])
    assert any("unsafe curated_image_path" in e for e in validation.errors)


def test_absolute_source_path_rejected_by_validator(repo) -> None:
    build_curated_dataset(_options(repo))
    images_path = repo["output"] / "images.jsonl"
    records = _read_jsonl(images_path)
    records[0]["source_image_path"] = "/etc/passwd"
    images_path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8"
    )
    validation = validate_curated_dataset(repo["output"], repo["root"])
    assert any("unsafe source_image_path" in e for e in validation.errors)


def test_checksums_detect_tampering(repo) -> None:
    build_curated_dataset(_options(repo))
    target = repo["output"] / "documents.jsonl"
    target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    validation = validate_curated_dataset(repo["output"], repo["root"])
    assert not validation.ok
    assert any("checksum mismatch" in e or "size mismatch" in e for e in validation.errors)


def test_foreign_keys_validated(repo) -> None:
    build_curated_dataset(_options(repo))
    documents_path = repo["output"] / "documents.jsonl"
    records = _read_jsonl(documents_path)
    records[0]["project_id"] = "ghost_project"
    documents_path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8"
    )
    validation = validate_curated_dataset(repo["output"], repo["root"])
    assert any("broken FK" in e or "unknown project_id" in e for e in validation.errors)


def test_two_builds_byte_identical(repo) -> None:
    """Verifier blocker D: full byte idempotency, no file excluded."""
    out_a = repo["root"] / "data" / "curated" / "build_a"
    out_b = repo["root"] / "data" / "curated" / "build_b"
    build_curated_dataset(_options(repo, output=out_a))
    build_curated_dataset(_options(repo, output=out_b))

    files_a = {
        p.relative_to(out_a).as_posix(): sha256_file(p) for p in out_a.rglob("*") if p.is_file()
    }
    files_b = {
        p.relative_to(out_b).as_posix(): sha256_file(p) for p in out_b.rglob("*") if p.is_file()
    }
    assert files_a.keys() == files_b.keys()
    mismatches = [name for name in files_a if files_a[name] != files_b[name]]
    assert mismatches == []
    # Deterministic checksums inventory in particular.
    assert files_a["checksums.jsonl"] == files_b["checksums.jsonl"]
    # Same inputs => same fingerprint.
    fp1, n1 = compute_input_fingerprint(_options(repo))
    fp2, n2 = compute_input_fingerprint(_options(repo))
    assert fp1 == fp2 and n1 == n2


def test_rebuild_without_force_refused(repo) -> None:
    build_curated_dataset(_options(repo))
    with pytest.raises(CuratedBuildError, match="--force"):
        build_curated_dataset(_options(repo))


def test_atomic_swap_failure_restores_previous_dataset(repo, monkeypatch) -> None:
    build_curated_dataset(_options(repo))
    before = _snapshot(repo["output"])

    from dalel.curation import builder as builder_module

    def boom(dataset_dir: Path) -> None:
        raise OSError("synthetic checksum failure")

    monkeypatch.setattr(builder_module, "write_checksums", boom)
    with pytest.raises(OSError):
        build_curated_dataset(_options(repo, force=True))
    assert _snapshot(repo["output"]) == before
    assert not list(repo["output"].parent.glob(".tmp__*"))


def test_malformed_processed_record_blocks_build(repo) -> None:
    pages_path = repo["legacy_dir"] / "pages.jsonl"
    pages_path.write_text(pages_path.read_text(encoding="utf-8") + "\n\n", encoding="utf-8")
    with pytest.raises(CuratedBuildError, match="blank JSONL line"):
        build_curated_dataset(_options(repo))


def test_no_absolute_paths_in_dataset(repo) -> None:
    build_curated_dataset(_options(repo))
    for name in (
        "projects.jsonl",
        "documents.jsonl",
        "pages.jsonl",
        "sections.jsonl",
        "tables.jsonl",
        "images.jsonl",
        "weak_findings.jsonl",
        "checksums.jsonl",
    ):
        for record in _read_jsonl(repo["output"] / name):
            payload = json.dumps(record, ensure_ascii=False)
            assert str(repo["root"]) not in payload, f"absolute path leaked into {name}"

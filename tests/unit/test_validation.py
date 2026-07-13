import json
from pathlib import Path

import pytest

from dalel.ingestion.validation import ManifestError, load_manifest, validate_manifest


def test_validate_ok(tmp_repo) -> None:
    result = validate_manifest(tmp_repo.manifest_path, tmp_repo.root, check_hashes=True)
    assert result.ok, result.errors
    assert len(result.projects) == 1
    assert result.document_count == 5


def test_missing_file_reported(tmp_repo) -> None:
    tmp_repo.digital_pdf.rename(tmp_repo.digital_pdf.with_name("gone.pdf"))
    result = validate_manifest(tmp_repo.manifest_path, tmp_repo.root, check_hashes=False)
    assert not result.ok
    assert any("does not exist" in error for error in result.errors)


def test_sha_mismatch_reported(tmp_repo) -> None:
    tmp_repo.digital_pdf.write_bytes(b"%PDF-1.4 tampered")
    result = validate_manifest(tmp_repo.manifest_path, tmp_repo.root, check_hashes=True)
    assert not result.ok
    assert any("SHA-256 mismatch" in error for error in result.errors)


def test_duplicate_document_id_reported(tmp_repo) -> None:
    lines = tmp_repo.manifest_path.read_text(encoding="utf-8").splitlines()
    project = json.loads(lines[0])
    project["documents"].append(dict(project["documents"][0]))
    tmp_repo.manifest_path.write_text(json.dumps(project) + "\n", encoding="utf-8")
    result = validate_manifest(tmp_repo.manifest_path, tmp_repo.root, check_hashes=False)
    assert any("duplicate document_id" in error for error in result.errors)
    assert any("duplicate local_path" in error for error in result.errors)


def test_leakage_boundary_enforced(tmp_repo) -> None:
    lines = tmp_repo.manifest_path.read_text(encoding="utf-8").splitlines()
    project = json.loads(lines[0])
    for document in project["documents"]:
        if document["role"] == "label_source":
            document["use_as_model_feature"] = True
    tmp_repo.manifest_path.write_text(json.dumps(project) + "\n", encoding="utf-8")
    result = validate_manifest(tmp_repo.manifest_path, tmp_repo.root, check_hashes=False)
    assert any("label_source must not be a model feature" in error for error in result.errors)


def test_absolute_path_rejected(tmp_repo) -> None:
    lines = tmp_repo.manifest_path.read_text(encoding="utf-8").splitlines()
    project = json.loads(lines[0])
    project["documents"][0]["local_path"] = str(tmp_repo.digital_pdf)
    tmp_repo.manifest_path.write_text(json.dumps(project) + "\n", encoding="utf-8")
    result = validate_manifest(tmp_repo.manifest_path, tmp_repo.root, check_hashes=False)
    assert any("absolute local_path" in error for error in result.errors)


def test_missing_manifest_raises(tmp_path: Path) -> None:
    with pytest.raises(ManifestError):
        load_manifest(tmp_path / "missing.jsonl")


def test_invalid_json_line_raises(tmp_path: Path) -> None:
    manifest = tmp_path / "projects.jsonl"
    manifest.write_text("{not json}\n", encoding="utf-8")
    with pytest.raises(ManifestError):
        load_manifest(manifest)

"""Input fingerprint semantics tests (verifier blocker B).

The fingerprint must cover ONLY upstream inputs the builder actually reads and
must be independent of P1 outputs, the review template, curated outputs,
absolute repository location and wall clock.
"""

import json
import shutil
from pathlib import Path

import pytest

from dalel.curation.builder import (
    CurateOptions,
    build_curated_dataset,
    collect_input_inventory,
    compute_input_fingerprint,
)
from fixtures.curation_builders import PROJECT_ID, make_processed_repo

ALLOWED_ROLES = {
    "canonical_manifest",
    "source_metadata",
    "processed_document",
    "processed_image",
    "label_source_table_gate",
    "weak_findings",
}


@pytest.fixture()
def repo(tmp_path: Path) -> dict[str, Path]:
    paths = make_processed_repo(tmp_path)
    paths["root"] = tmp_path
    paths["output"] = tmp_path / "data" / "curated" / "v1"
    return paths


def _options(repo: dict[str, Path], force: bool = False) -> CurateOptions:
    return CurateOptions(
        input_root=repo["processed"],
        output_dir=repo["output"],
        repo_root=repo["root"],
        manifest_path=repo["manifest"],
        annotations_root=repo["annotations_root"],
        force=force,
    )


def _fingerprint(repo: dict[str, Path]) -> str:
    return compute_input_fingerprint(_options(repo))[0]


def test_same_inputs_same_fingerprint(repo) -> None:
    assert _fingerprint(repo) == _fingerprint(repo)


def test_review_template_does_not_change_fingerprint(repo) -> None:
    before = _fingerprint(repo)
    template = repo["annotations_root"] / "p1_review_template.jsonl"
    template.write_text('{"finding_id": "X", "expert_decision": "confirmed"}\n', encoding="utf-8")
    assert _fingerprint(repo) == before
    template.write_text('{"finding_id": "Y"}\n', encoding="utf-8")
    assert _fingerprint(repo) == before


def test_p1_results_do_not_change_fingerprint(repo) -> None:
    before = _fingerprint(repo)
    results = repo["root"] / "data" / "results" / "p1" / "v1"
    results.mkdir(parents=True)
    (results / "findings.jsonl").write_text('{"finding_id": "F"}\n', encoding="utf-8")
    assert _fingerprint(repo) == before


def test_curated_output_does_not_change_fingerprint(repo) -> None:
    result = build_curated_dataset(_options(repo))
    assert result.status == "success"
    before = _fingerprint(repo)
    (repo["output"] / "dataset_card.md").write_text("tampered", encoding="utf-8")
    assert _fingerprint(repo) == before
    assert result.input_fingerprint == before


def test_processed_change_changes_fingerprint(repo) -> None:
    before = _fingerprint(repo)
    pages_path = repo["legacy_dir"] / "pages.jsonl"
    record = json.loads(pages_path.read_text().splitlines()[0])
    record["text"] = record["text"] + " изменено"
    record["char_count"] = len(record["text"].strip())
    pages_path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    assert _fingerprint(repo) != before


def test_weak_findings_change_changes_fingerprint(repo) -> None:
    before = _fingerprint(repo)
    weak = repo["annotations_root"] / PROJECT_ID / "weak_findings.json"
    payload = json.loads(weak.read_text(encoding="utf-8"))
    payload["findings"][0]["title"] = "Изменённая находка"
    weak.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    assert _fingerprint(repo) != before


def test_absolute_repo_path_does_not_matter(repo, tmp_path_factory) -> None:
    other_root = tmp_path_factory.mktemp("relocated_repo")
    shutil.copytree(repo["root"] / "data", other_root / "data")
    relocated = {
        "root": other_root,
        "processed": other_root / "data" / "processed",
        "manifest": other_root / "data" / "manifests" / "projects.jsonl",
        "annotations_root": other_root / "data" / "annotations",
        "output": other_root / "data" / "curated" / "v1",
    }
    assert _fingerprint(relocated) == _fingerprint(repo)


def test_inventory_contains_only_allowed_upstream_roles(repo) -> None:
    # Downstream artifacts present on disk must not enter the inventory.
    (repo["annotations_root"] / "p1_review_template.jsonl").write_text("{}\n", encoding="utf-8")
    results = repo["root"] / "data" / "results" / "p1" / "v1"
    results.mkdir(parents=True)
    (results / "metrics.json").write_text("{}", encoding="utf-8")

    entries = collect_input_inventory(_options(repo))
    assert entries, "inventory must not be empty"
    paths = [entry.relative_path for entry in entries]
    assert paths == sorted(paths)
    for entry in entries:
        assert entry.input_role in ALLOWED_ROLES
        assert not entry.relative_path.startswith("data/curated/")
        assert not entry.relative_path.startswith("data/results/")
        assert "p1_review_template" not in entry.relative_path
    # Label sources contribute ONLY their table-gate file.
    label_files = [p for p in paths if "label_sources" in p]
    assert label_files and all(p.endswith("tables.jsonl") for p in label_files)


def test_build_report_contains_inventory_summary(repo) -> None:
    build_curated_dataset(_options(repo))
    report = json.loads((repo["output"] / "build_report.json").read_text(encoding="utf-8"))
    assert report["fingerprint_algorithm"] == "dalel-input-inventory/v2"
    entries = [
        json.loads(x)
        for x in (repo["output"] / "input_manifest.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert report["input_files_hashed"] == len(entries)
    roles: dict[str, int] = {}
    for entry in entries:
        roles[entry["input_role"]] = roles.get(entry["input_role"], 0) + 1
    assert report["input_roles"] == dict(sorted(roles.items()))

"""Load the actual audited manifest of this repository (read-only)."""

from pathlib import Path

import pytest

from dalel.ingestion.routing import select_documents
from dalel.ingestion.validation import load_manifest

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = REPO_ROOT / "data" / "manifests" / "projects.jsonl"

pytestmark = pytest.mark.skipif(not MANIFEST.is_file(), reason="canonical manifest not present")


def test_audited_manifest_loads() -> None:
    projects = load_manifest(MANIFEST)
    assert len(projects) == 4
    assert sum(len(p.documents) for p in projects) == 24


def test_audited_manifest_role_distribution() -> None:
    projects = load_manifest(MANIFEST)
    roles: dict[str, int] = {}
    for project in projects:
        for document in project.documents:
            roles[document.role] = roles.get(document.role, 0) + 1
    assert roles == {"model_input": 19, "label_source": 4, "auxiliary_archive": 1}


def test_audited_manifest_default_selection_is_19_model_inputs() -> None:
    projects = load_manifest(MANIFEST)
    selection = select_documents(projects)
    assert len(selection.selected) == 19
    assert all(s.document.role == "model_input" for s in selection.selected)
    skipped_roles = {s.document.role for s in selection.skipped}
    assert skipped_roles == {"label_source", "auxiliary_archive"}


def test_audited_manifest_label_sources_never_features() -> None:
    projects = load_manifest(MANIFEST)
    for project in projects:
        for document in project.documents:
            if document.role in {"label_source", "auxiliary_archive"}:
                assert document.use_as_model_feature is False
                assert document.label_timing == "post_review"

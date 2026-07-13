import json

import pytest
from pydantic import ValidationError

from dalel.schemas.manifest import ManifestDocument, ManifestProject

VALID_DOC = {
    "document_id": "p1__ndv__001",
    "local_path": "data/raw/p1/ndv.pdf",
    "original_filename": "ndv.pdf",
    "document_type": "ndv",
    "role": "model_input",
    "use_as_model_feature": True,
    "file_format": "pdf",
    "sha256": "a" * 64,
    "label_timing": "pre_review",
    "notes": None,
}


def test_document_parses() -> None:
    document = ManifestDocument.model_validate(VALID_DOC)
    assert document.is_default_ingestible


def test_invalid_sha256_rejected() -> None:
    with pytest.raises(ValidationError):
        ManifestDocument.model_validate({**VALID_DOC, "sha256": "zz"})


def test_invalid_document_type_rejected() -> None:
    with pytest.raises(ValidationError):
        ManifestDocument.model_validate({**VALID_DOC, "document_type": "not_a_type"})


def test_invalid_role_rejected() -> None:
    with pytest.raises(ValidationError):
        ManifestDocument.model_validate({**VALID_DOC, "role": "feature_source"})


def test_all_audited_document_types_accepted() -> None:
    for document_type in [
        "ndv",
        "pek",
        "puo",
        "ovvos",
        "roos",
        "action_plan",
        "nontechnical_summary",
        "explanatory_note",
        "working_project_note",
        "hearing_protocol",
        "motivated_refusal",
        "map",
        "photo",
        "appendix",
        "archive",
        "unknown",
    ]:
        document = ManifestDocument.model_validate({**VALID_DOC, "document_type": document_type})
        assert document.document_type == document_type


def test_label_source_not_default_ingestible() -> None:
    document = ManifestDocument.model_validate(
        {
            **VALID_DOC,
            "role": "label_source",
            "use_as_model_feature": False,
            "label_timing": "post_review",
        }
    )
    assert not document.is_default_ingestible


def test_unknown_fields_survive_roundtrip() -> None:
    raw = {**VALID_DOC, "future_field": {"nested": [1, 2, 3]}}
    document = ManifestDocument.model_validate(raw)
    dumped = json.loads(document.model_dump_json())
    assert dumped["future_field"] == {"nested": [1, 2, 3]}


def test_project_unknown_fields_survive_roundtrip() -> None:
    project = ManifestProject.model_validate(
        {
            "schema_version": "1.0",
            "project_id": "p1",
            "source_metadata_path": "data/raw/p1/source_metadata.json",
            "languages": ["ru"],
            "documents": [VALID_DOC],
            "portal_extra": "keep-me",
        }
    )
    dumped = json.loads(project.model_dump_json())
    assert dumped["portal_extra"] == "keep-me"
    assert project.company_id is None
    assert project.developer_id is None

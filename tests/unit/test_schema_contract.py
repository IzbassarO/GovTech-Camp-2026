"""Standalone JSON Schema contract tests (verifier blocker A).

Every test here calls a standard Draft 2020-12 validator on the DISTRIBUTED
``schema.json`` — Pydantic models are never invoked. Semantically invalid
records must be rejected by the schema alone.
"""

import json
from pathlib import Path

import jsonschema
import pytest

from dalel.curation.builder import CurateOptions, build_curated_dataset
from fixtures.curation_builders import make_processed_repo


@pytest.fixture(scope="module")
def dataset(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("schema_repo")
    paths = make_processed_repo(root)
    output = root / "data" / "curated" / "v1"
    result = build_curated_dataset(
        CurateOptions(
            input_root=paths["processed"],
            output_dir=output,
            repo_root=root,
            manifest_path=paths["manifest"],
            annotations_root=paths["annotations_root"],
        )
    )
    assert result.status == "success"
    return output


@pytest.fixture(scope="module")
def schemas(dataset: Path) -> dict:
    return json.loads((dataset / "schema.json").read_text(encoding="utf-8"))["files"]


def _first_record(dataset: Path, name: str) -> dict:
    if name.endswith(".jsonl"):
        return json.loads((dataset / name).read_text(encoding="utf-8").splitlines()[0])
    return json.loads((dataset / name).read_text(encoding="utf-8"))


def _errors(schemas: dict, name: str, record: dict) -> list[str]:
    validator = jsonschema.Draft202012Validator(schemas[name])
    return [e.message for e in validator.iter_errors(record)]


ALL_FILES = [
    "projects.jsonl",
    "documents.jsonl",
    "pages.jsonl",
    "sections.jsonl",
    "tables.jsonl",
    "images.jsonl",
    "weak_findings.jsonl",
    "document_groups.jsonl",
    "input_manifest.jsonl",
    "build_report.json",
    "dataset_statistics.json",
]


def test_all_schemas_are_valid_draft_2020_12(schemas) -> None:
    for name in ALL_FILES:
        jsonschema.Draft202012Validator.check_schema(schemas[name])
        assert "properties" in schemas[name], name


def test_valid_records_of_all_types_accepted(dataset, schemas) -> None:
    for name in ALL_FILES:
        record = _first_record(dataset, name)
        assert _errors(schemas, name, record) == [], name


def test_production_valid_image_record_accepted(dataset, schemas) -> None:
    record = _first_record(dataset, "images.jsonl")
    assert _errors(schemas, "images.jsonl", record) == []


def test_table_zero_dims_rejected(dataset, schemas) -> None:
    record = _first_record(dataset, "tables.jsonl")
    record["num_rows"] = 0
    record["num_cols"] = 0
    record["cells"] = []
    assert _errors(schemas, "tables.jsonl", record)


def test_table_empty_cells_rejected(dataset, schemas) -> None:
    record = _first_record(dataset, "tables.jsonl")
    record["cells"] = []
    assert _errors(schemas, "tables.jsonl", record)


def test_table_all_blank_cells_rejected(dataset, schemas) -> None:
    record = _first_record(dataset, "tables.jsonl")
    record["cells"] = [["", "  "], ["\t", " "]]
    errors = _errors(schemas, "tables.jsonl", record)
    assert errors, "all-blank grid must fail the standalone contains-constraint"


def test_table_missing_dimensions_rejected(dataset, schemas) -> None:
    record = _first_record(dataset, "tables.jsonl")
    del record["num_rows"]
    del record["cells"]
    assert _errors(schemas, "tables.jsonl", record)


def test_image_zero_size_rejected(dataset, schemas) -> None:
    record = _first_record(dataset, "images.jsonl")
    record["image_size_bytes"] = 0
    assert _errors(schemas, "images.jsonl", record)


def test_image_invalid_sha_rejected(dataset, schemas) -> None:
    record = _first_record(dataset, "images.jsonl")
    record["image_sha256"] = "not-a-sha"
    assert _errors(schemas, "images.jsonl", record)


def test_image_absolute_path_rejected(dataset, schemas) -> None:
    record = _first_record(dataset, "images.jsonl")
    record["curated_image_path"] = "/tmp/evil.png"
    assert _errors(schemas, "images.jsonl", record)


def test_image_traversal_path_rejected(dataset, schemas) -> None:
    record = _first_record(dataset, "images.jsonl")
    record["curated_image_path"] = "images/../../evil.png"
    assert _errors(schemas, "images.jsonl", record)


def test_consecutive_dots_in_filename_accepted(dataset, schemas) -> None:
    """Regression: real corpus filenames contain '…гг..pdf' — consecutive dots
    inside a name are NOT traversal and must pass the standalone contract."""
    record = _first_record(dataset, "documents.jsonl")
    record["source_path"] = "data/raw/project_002_azm/1. НДВ для АО АЗМ на 2026-2035гг..pdf"
    assert _errors(schemas, "documents.jsonl", record) == []

    from dalel.curation.schemas import CuratedDocument

    CuratedDocument.model_validate(record)  # Pydantic layer agrees

    bad = _first_record(dataset, "documents.jsonl")
    bad["source_path"] = "data/raw/../secrets.pdf"
    assert _errors(schemas, "documents.jsonl", bad)

    image = _first_record(dataset, "images.jsonl")
    image["source_image_path"] = "data/processed/images/рисунок 2026-2035гг..png"
    assert _errors(schemas, "images.jsonl", image) == []


@pytest.mark.parametrize(
    "field_name",
    ("curated_image_path", "image_sha256", "image_size_bytes"),
)
def test_image_missing_materialization_key_rejected(dataset, schemas, field_name) -> None:
    """Omitted keys must fail, not only present keys whose value is null."""
    record = _first_record(dataset, "images.jsonl")
    del record[field_name]
    assert _errors(schemas, "images.jsonl", record)


@pytest.mark.parametrize(
    "field_name",
    ("curated_image_path", "image_sha256", "image_size_bytes"),
)
def test_image_null_materialization_value_rejected(dataset, schemas, field_name) -> None:
    record = _first_record(dataset, "images.jsonl")
    record[field_name] = None
    assert _errors(schemas, "images.jsonl", record)


def test_document_label_source_role_rejected(dataset, schemas) -> None:
    """Verifier synthetic case: role=label_source in the feature layer."""
    record = _first_record(dataset, "documents.jsonl")
    record["role"] = "label_source"
    assert _errors(schemas, "documents.jsonl", record)


def test_provenance_role_rejected_in_feature_records(dataset, schemas) -> None:
    record = _first_record(dataset, "pages.jsonl")
    record["provenance"]["role"] = "label_source"
    assert _errors(schemas, "pages.jsonl", record)


def test_invalid_statuses_rejected(dataset, schemas) -> None:
    report = _first_record(dataset, "build_report.json")
    report["status"] = "banana"  # verifier synthetic case
    assert _errors(schemas, "build_report.json", report)

    document = _first_record(dataset, "documents.jsonl")
    document["extraction_status"] = "banana"
    assert _errors(schemas, "documents.jsonl", document)


def test_missing_required_provenance_rejected(dataset, schemas) -> None:
    record = _first_record(dataset, "pages.jsonl")
    del record["provenance"]
    assert _errors(schemas, "pages.jsonl", record)

    record2 = _first_record(dataset, "sections.jsonl")
    del record2["provenance"]["source_sha256"]
    assert _errors(schemas, "sections.jsonl", record2)


def test_weak_finding_gold_claims_rejected(dataset, schemas) -> None:
    record = _first_record(dataset, "weak_findings.jsonl")
    record["confidence"] = "gold"
    assert _errors(schemas, "weak_findings.jsonl", record)
    record2 = _first_record(dataset, "weak_findings.jsonl")
    record2["expert_verified"] = True
    assert _errors(schemas, "weak_findings.jsonl", record2)

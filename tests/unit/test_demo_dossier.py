"""Structured dossier demo tests: schema, manifest reconciliation, honesty.

The prepared Bayterek manifest describes the FULL official source package
(7 registered materials + 2 archive extractions), while only 2 curated
documents are analyzed by P1–P4. These tests pin the three-scope honesty
(official package / local copy / analyzed subset), the computed — never
hardcoded — reconciliation states, prepared-replay immutability, tokenized
job access, and the absence of private data in every response.
"""

from __future__ import annotations

import warnings

import pytest

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    from fastapi.testclient import TestClient

from dalel.api.app import create_app
from dalel.api.demo import reset_demo_jobs
from dalel.api.dossier import PreparedDocument, reconcile_document
from dalel.api.repository import get_store, reset_store_cache

BAYTEREK = "project_003_bayterek"

# Strings that must never appear in any demo/dossier response: private
# surnames from source filenames, the public commenter's name, the
# initiator's BIN, machine paths.
FORBIDDEN_STRINGS = (
    "Онгарова",
    "Оразалинов",
    "ОРАЗАЛИНОВ",
    "751112402169",
    "/Users/",
    "data/raw",
    "data/results",
    ".venv",
    "@gmail",
    "@mail.",
)


@pytest.fixture(scope="module")
def client() -> TestClient:
    reset_store_cache()
    reset_demo_jobs()
    return TestClient(create_app())


# --- package schema -----------------------------------------------------------


def test_package_schema_sections(client: TestClient) -> None:
    body = client.get("/api/demo/package-schema").json()
    sections = body["sections"]
    assert [s["section_id"] for s in sections] == [
        "project_documents",
        "media_publication",
        "notice_boards",
        "hearing_protocol",
        "public_feedback",
    ]
    assert [s["order"] for s in sections] == [1, 2, 3, 4, 5]
    by_id = {s["section_id"]: s for s in sections}
    assert by_id["project_documents"]["title_ru"] == "Проектная документация"
    assert by_id["project_documents"]["requirement_level"] == "required"
    assert by_id["project_documents"]["pillar_relevance"] == ["P1", "P2", "P3", "P4"]
    assert by_id["hearing_protocol"]["accepted_formats"] == ["pdf", "docx", "zip", "rar"]
    assert by_id["media_publication"]["future_pillar"] == "P5"
    assert by_id["public_feedback"]["upload_enabled"] is False
    assert by_id["public_feedback"]["requirement_level"] == "external_source"
    # Safe, non-legal wording only.
    text = str(body)
    assert "Закон требует" not in text
    assert "юридически" not in text.lower()


# --- prepared manifest reconciliation ------------------------------------------


def test_manifest_shows_full_official_package(client: TestClient) -> None:
    body = client.get("/api/demo/manifest").json()
    assert body["prepared"] is True

    documents = [d for s in body["sections"] for d in s["documents"]]
    assert len(documents) == 9  # 7 official materials + 2 archive extractions

    completeness = body["completeness"]
    # Counts are computed from the reconciled documents — verify against a
    # recomputation from the response itself (no hardcoded backend numbers).
    assert completeness["official_registered_total"] == sum(
        1 for d in documents if d["official_source_registered"]
    )
    assert completeness["official_registered_total"] == 7
    assert completeness["locally_available_total"] == sum(
        1 for d in documents if d["local_available"]
    )
    assert completeness["locally_available_total"] == 6
    assert completeness["analyzed_total"] == 2
    assert completeness["supporting_total"] == 4
    assert completeness["official_only_total"] == 3
    assert completeness["sections_total"] == 5
    assert completeness["sections_with_materials"] == 5
    assert completeness["heading"] == "Комплектность материалов для анализа"

    by_section = {s["definition"]["section_id"]: s for s in body["sections"]}
    assert len(by_section["project_documents"]["documents"]) == 3
    assert len(by_section["media_publication"]["documents"]) == 1
    assert len(by_section["notice_boards"]["documents"]) == 2
    assert len(by_section["hearing_protocol"]["documents"]) == 3
    assert by_section["public_feedback"]["documents"] == []

    # No silent drops: every document appears exactly once in the matrix.
    matrix_ids = [row["document_id"] for row in body["coverage_matrix"]]
    assert sorted(matrix_ids) == sorted(d["document_id"] for d in documents)
    # Every document carries an honest reconciled state and a label.
    for document in documents:
        assert document["reconciled_status"]
        assert document["status_label"]


def test_manifest_identity_block_is_safe(client: TestClient) -> None:
    identity = client.get("/api/demo/manifest").json()["identity"]
    assert identity["project_id"] == BAYTEREK
    assert identity["hearing_registration_number"] == "260518001029"
    assert identity["initiator_type_label"] == "Индивидуальный предприниматель"
    assert identity["hearing_method_label"] == "Публичное обсуждение"
    assert identity["source_url"].startswith("https://hearings.ndbecology.gov.kz/")
    # P6 readiness is registered but never presented as active analysis.
    assert identity["geospatial_analysis_status"] == "not_available"


def test_manifest_analyzed_subset_is_artifact_backed(client: TestClient) -> None:
    body = client.get("/api/demo/manifest").json()
    documents = [d for s in body["sections"] for d in s["documents"]]
    analyzed = [d for d in documents if d["reconciled_status"] == "analyzed"]
    assert len(analyzed) == 2
    real_documents = client.get(f"/api/projects/{BAYTEREK}").json()["documents"]
    real_ids = {d["document_id"] for d in real_documents}
    for document in analyzed:
        assert document["curated_document_id"] in real_ids
        assert document["analyzed_by"] == ["P1", "P2", "P3", "P4"]
        assert document["meta_evidence"] is True
        assert document["text_extracted"] is True
        assert document["page_count"]


def test_manifest_archive_honesty(client: TestClient) -> None:
    body = client.get("/api/demo/manifest").json()
    documents = {d["document_id"]: d for s in body["sections"] for d in s["documents"]}
    archive = documents["bt_doc_protocol_rar"]
    assert archive["media_type"] == "rar"
    assert archive["archive_status"] == "extracted"
    assert archive["reconciled_status"] == "extracted"
    # An extracted archive is never presented as semantically analyzed.
    assert archive["analyzed_by"] == []
    assert any("не входит" in item for item in archive["limitations"])
    for child_id in ("bt_doc_protocol_kk", "bt_doc_protocol_ru"):
        child = documents[child_id]
        assert child["extracted_from"] == "bt_doc_protocol_rar"
        assert child["source_origin"] == "extracted_archive"
        assert child["reconciled_status"] == "supporting_only"
        assert child["analyzed_by"] == []
        # Registered in the curated project record as post-review label
        # sources — verified against the store, not asserted blindly.
        assert child["registered_label_source"] is True


def test_manifest_official_only_materials_stay_visible(client: TestClient) -> None:
    body = client.get("/api/demo/manifest").json()
    documents = {d["document_id"]: d for s in body["sections"] for d in s["documents"]}
    for document_id in ("bt_doc_newspaper", "bt_doc_board_1", "bt_doc_board_2"):
        document = documents[document_id]
        assert document["official_source_registered"] is True
        assert document["local_available"] is False
        assert document["reconciled_status"] == "official_only"
        assert document["missing_reason"]
        # Future P5 input: registered as eligible, never as analyzed.
        assert document["eligible_for_p5"] is True
        assert document["visual_analysis_status"] == "not_available"
        assert document["analyzed_by"] == []


def test_manifest_public_feedback_honest(client: TestClient) -> None:
    feedback = client.get("/api/demo/manifest").json()["public_feedback"]
    assert feedback["registered_in_official_source"] is True
    assert feedback["submission_count"] == 1
    assert feedback["question_count"] == 22
    assert feedback["included_in_analysis"] is False
    assert feedback["feeds_pillars"] == []
    assert "не включено в текущий автоматический анализ" in feedback["note"]


def test_manifest_has_no_private_data(client: TestClient) -> None:
    text = client.get("/api/demo/manifest").text
    for forbidden in FORBIDDEN_STRINGS:
        assert forbidden not in text, forbidden


def test_manifest_original_names_only_when_safe(client: TestClient) -> None:
    body = client.get("/api/demo/manifest").json()
    documents = {d["document_id"]: d for s in body["sections"] for d in s["documents"]}
    # Source filenames containing a private surname are never exposed.
    for hidden in ("bt_doc_roos", "bt_doc_refusal", "bt_doc_protocol_rar"):
        assert documents[hidden]["original_name"] is None
    # Explicitly public, personal-data-free names may be shown.
    assert documents["bt_doc_opz"]["original_name"] == "1. ОПЗ+база.pdf"
    assert documents["bt_doc_board_1"]["original_name"] == "доска 1.pdf"


# --- immutable prepared-replay job ---------------------------------------------


def _structured_payload() -> dict[str, object]:
    return {"mode": "prepared_replay"}


def _create_replay(client: TestClient) -> tuple[dict[str, object], str]:
    response = client.post("/api/demo/jobs", json=_structured_payload())
    assert response.status_code == 200
    payload = response.json()
    token = payload.pop("access_token")
    assert isinstance(token, str) and len(token) >= 40
    return payload, token


def test_structured_job_stages_and_scopes(client: TestClient) -> None:
    body, _token = _create_replay(client)
    assert [s["stage_id"] for s in body["stages"]] == [
        "p0",
        "p0_5",
        "p1",
        "p2",
        "p3",
        "p4",
        "meta",
    ]
    # Three scopes stay distinct and computed.
    assert body["registered_source_count"] == 7
    assert body["locally_available_count"] == 6
    assert body["analyzed_count"] == 2
    assert "включённым в текущий доказательный анализ" in body["analysis_scope_note"]

    p0 = body["stages"][0]
    assert p0["pillar_id"] == "P0"
    assert "Не найдено в локальной копии" in (p0["warning"] or "")
    p0_5 = body["stages"][1]
    assert p0_5["pillar_id"] == "P0.5"
    deep = next(m for m in p0_5["metrics"] if m["label"] == "К глубокому анализу")
    assert deep["value"] == "2"

    # Pillar stages expose input/operation/output separately.
    p1 = next(s for s in body["stages"] if s["stage_id"] == "p1")
    assert p1["operation"]
    assert p1["inputs"]
    assert "2 из 9" in (p1["input_note"] or "")
    p2 = next(s for s in body["stages"] if s["stage_id"] == "p2")
    assert "Демонстрационный нормативный корпус" in p2["inputs"]

    # AlemLLM slot: reserved, never silently populated.
    assert body["generated_explanation"] is None
    assert body["generation_status"] == "not_available"


def test_structured_job_meta_is_artifact_derived_and_translated(client: TestClient) -> None:
    real_meta = client.get(f"/api/projects/{BAYTEREK}/summary").json()["meta"]
    body, _token = _create_replay(client)
    meta_stage = next(s for s in body["stages"] if s["stage_id"] == "meta")
    score_metric = next(m for m in meta_stage["metrics"] if m["label"] == "Приоритет проверки")
    assert score_metric["value"] == f"{real_meta['review_priority_score']:g}/100"
    level_metric = next(m for m in meta_stage["metrics"] if m["label"] == "Уровень")
    # Primary label is Russian; the raw level stays as the technical id.
    assert level_metric["value"] == "умеренный"
    assert level_metric["technical_id"] == real_meta["review_priority_level"]
    # Strong factors carry user-facing Russian titles, raw feature ids only
    # in technical_id, and untouched artifact contributions as values.
    factor_metrics = [
        m for m in meta_stage["metrics"] if m["technical_id"] and "·" in m["technical_id"]
    ]
    assert factor_metrics
    real_factors = {f["feature_name"]: f["contribution"] for f in real_meta["top_positive_factors"]}
    for metric in factor_metrics:
        feature_name = metric["technical_id"].split("·")[-1].strip()
        assert feature_name in real_factors
        assert metric["label"] != feature_name  # translated, not raw
        assert metric["value"] == f"+{real_factors[feature_name]:g}"
    assert "не вероятность нарушения" in (meta_stage["warning"] or "")


@pytest.mark.parametrize(
    "forbidden_field",
    [
        {"selected_files": [{"filename": "unrelated.pdf", "size_bytes": 12_345}]},
        {
            "sections": [
                {
                    "section_id": "project_documents",
                    "files": [{"document_id": "bt_doc_opz"}],
                }
            ]
        },
    ],
)
def test_prepared_replay_rejects_upload_and_selection_controls(
    client: TestClient, forbidden_field: dict[str, object]
) -> None:
    response = client.post(
        "/api/demo/jobs",
        json={**_structured_payload(), **forbidden_field},
    )
    assert response.status_code == 422
    assert "unrelated.pdf" not in response.text


def test_coverage_matrix_matches_artifacts(client: TestClient) -> None:
    body, _token = _create_replay(client)
    matrix = {row["document_id"]: row for row in body["dossier"]["coverage_matrix"]}
    assert len(matrix) == 9
    for analyzed_id in ("bt_doc_opz", "bt_doc_roos"):
        row = matrix[analyzed_id]
        assert row["prepared"] is True
        assert row["p1"] and row["p2"] and row["p3"] and row["p4"]
        assert row["meta_evidence"] is True
    for other_id, row in matrix.items():
        if other_id in ("bt_doc_opz", "bt_doc_roos"):
            continue
        assert not any((row["p1"], row["p2"], row["p3"], row["p4"]))
        assert row["meta_evidence"] is False
        assert row["limitation"]


def test_prepared_replay_job_requires_its_access_token(client: TestClient) -> None:
    body, token = _create_replay(client)
    job_id = body["job_id"]
    assert isinstance(job_id, str)
    assert job_id.startswith("demo_")
    assert "DEMOJOB__" not in job_id

    assert client.get(f"/api/demo/jobs/{job_id}").status_code in {403, 404}
    assert client.get(
        f"/api/demo/jobs/{job_id}", headers={"X-Dalel-Job-Token": "wrong"}
    ).status_code in {403, 404}
    fetched = client.get(f"/api/demo/jobs/{job_id}", headers={"X-Dalel-Job-Token": token})
    assert fetched.status_code == 200
    assert fetched.json() == body
    assert "access_token" not in fetched.text


def test_job_response_has_no_private_data(client: TestClient) -> None:
    response = client.post("/api/demo/jobs", json=_structured_payload())
    for forbidden in FORBIDDEN_STRINGS:
        assert forbidden not in response.text, forbidden


def test_meta_score_not_affected_by_dossier_layer(client: TestClient) -> None:
    """The dossier/demo layer reads Meta; it must never change it."""
    before = client.get(f"/api/projects/{BAYTEREK}/summary").json()["meta"]
    client.post("/api/demo/jobs", json=_structured_payload())
    client.get("/api/demo/manifest")
    after = client.get(f"/api/projects/{BAYTEREK}/summary").json()["meta"]
    assert before == after
    assert after["review_priority_score"] == before["review_priority_score"]


# --- reconciliation unit behavior ------------------------------------------------


def test_stale_curated_reference_degrades_honestly() -> None:
    """A manifest pointing at a missing curated document must degrade to
    "not analyzed" with an explicit limitation — never a false claim."""
    reset_store_cache()
    store = get_store()
    prepared = PreparedDocument(
        manifest_id="bt_doc_ghost",
        section_id="project_documents",
        safe_display_name="Несуществующий документ",
        media_type="pdf",
        source_origin="official_portal",
        official_source_registered=True,
        local_available=True,
        curated_document_id="project_003_bayterek__ghost__001",
    )
    document = reconcile_document(store, BAYTEREK, prepared)
    assert document.curated is False
    assert document.analyzed_by == []
    assert document.reconciled_status == "available_raw"
    assert any("не найдена в curated-наборе" in item for item in document.limitations)

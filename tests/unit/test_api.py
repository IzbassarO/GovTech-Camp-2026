"""DÁLEL Eco demo API tests.

Exercise the read-only API over the accepted P1/P2/P3 artifacts. No
network, no LLM: the FastAPI ``TestClient`` runs the app in-process
against the real on-disk artifacts. Focus areas: health, project list,
summary, finding filters, finding detail, missing resources, the P2
synthetic-corpus notice, the P3 zero-findings representation, and the
absence of absolute paths in any response.
"""

from __future__ import annotations

import warnings

import pytest

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    from fastapi.testclient import TestClient

from dalel.api.app import create_app
from dalel.api.repository import reset_store_cache

BAYTEREK = "project_003_bayterek"
BEREKE = "project_001_bereke"


@pytest.fixture(scope="module")
def client() -> TestClient:
    reset_store_cache()
    return TestClient(create_app())


# --- health & discovery ------------------------------------------------------


def test_health(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["data_ready"] is True
    assert body["projects_available"] == 4
    assert set(body["pillars_available"]) == {"P1", "P2", "P3", "P4"}


def test_list_projects(client: TestClient) -> None:
    response = client.get("/api/projects")
    assert response.status_code == 200
    projects = response.json()
    assert len(projects) == 4
    ids = {p["project_id"] for p in projects}
    assert BAYTEREK in ids and BEREKE in ids
    bayterek = next(p for p in projects if p["project_id"] == BAYTEREK)
    assert bayterek["name"] == "Bayterek"
    assert bayterek["document_count"] == 2
    assert bayterek["pillar_finding_counts"]["p2"] >= 1
    assert bayterek["has_demo_pillar"] is True


def test_system_metrics(client: TestClient) -> None:
    body = client.get("/api/system/metrics").json()
    assert body["projects"] == 4
    assert body["documents"] == 19
    assert body["findings_by_pillar"]["p1"] == 142
    assert body["findings_by_pillar"]["p3"] == 0
    assert body["dataset_fingerprint"] is not None
    assert len(body["dataset_fingerprint"]) == 64


# --- project detail & summary ------------------------------------------------


def test_project_detail(client: TestClient) -> None:
    body = client.get(f"/api/projects/{BAYTEREK}").json()
    assert body["name"] == "Bayterek"
    assert body["document_count"] == len(body["documents"])
    assert all("document_type" in d for d in body["documents"])


def test_project_summary_has_four_pillars(client: TestClient) -> None:
    body = client.get(f"/api/projects/{BAYTEREK}/summary").json()
    pillars = {p["pillar_id"]: p for p in body["pillars"]}
    assert set(pillars) == {"P1", "P2", "P3", "P4"}
    assert body["integrated_risk_available"] is False
    assert "следующий этап" in body["integrated_risk_note"]
    # P4 is now implemented; spatial/cartographic analysis moved to the P5
    # roadmap slot, integrated risk stays META.
    reserved = {p["pillar_id"] for p in body["reserved_pillars"]}
    assert "P5" in reserved and "META" in reserved
    assert "P4" not in reserved
    assert all(p["available"] is False for p in body["reserved_pillars"])


def test_summary_has_no_fabricated_risk_fields(client: TestClient) -> None:
    body = client.get(f"/api/projects/{BEREKE}/summary").json()
    for pillar in body["pillars"]:
        # Reserved future fields are present in the contract but never
        # fabricated — they stay null.
        assert pillar["calibrated_risk"] is None
        assert pillar["model_score"] is None
        assert pillar["shap_contributions"] is None


def test_pillars_endpoint_matches_summary(client: TestClient) -> None:
    pillars = client.get(f"/api/projects/{BEREKE}/pillars").json()
    assert [p["pillar_id"] for p in pillars] == ["P1", "P2", "P3", "P4"]


# --- P2 demo honesty ---------------------------------------------------------


def test_p2_pillar_carries_demo_warning(client: TestClient) -> None:
    body = client.get(f"/api/projects/{BAYTEREK}/summary").json()
    p2 = next(p for p in body["pillars"] if p["pillar_id"] == "P2")
    assert p2["is_demo"] is True
    assert p2["is_authoritative"] is False
    assert p2["warning"] is not None
    assert "Не является официальным источником права" in p2["warning"]


def test_p2_finding_detail_marks_demo(client: TestClient) -> None:
    findings = client.get(f"/api/projects/{BAYTEREK}/findings?pillar=p2").json()["findings"]
    missing_doc = next(f for f in findings if f["finding_type"] == "missing_required_document")
    detail = client.get(f"/api/projects/{BAYTEREK}/findings/{missing_doc['finding_id']}").json()
    assert detail["is_demo"] is True
    assert detail["demo_warning"] is not None
    assert detail["requirement"]["demo_only"] is True
    assert detail["requirement"]["is_authoritative"] is False
    assert "экспертной проверки" in detail["review_notice"]


# --- P3 zero-findings honesty ------------------------------------------------


def test_p3_zero_findings_positive_empty_state(client: TestClient) -> None:
    body = client.get(f"/api/projects/{BEREKE}/summary").json()
    p3 = next(p for p in body["pillars"] if p["pillar_id"] == "P3")
    assert p3["finding_count"] == 0
    assert p3["status"] == "clear"
    assert p3["empty_state"] is not None
    assert "не обнаружено" in p3["empty_state"]
    assert "исключен" in p3["empty_state"].lower()
    # Per-project quantitative pipeline metrics are still surfaced.
    labels = {m["label"] for m in p3["metrics"]}
    assert any("упоминан" in label.lower() for label in labels)


def test_p3_no_findings_across_projects(client: TestClient) -> None:
    for project in ("project_001_bereke", "project_002_azm", "project_004_sintez_ural"):
        page = client.get(f"/api/projects/{project}/findings?pillar=p3").json()
        assert page["returned"] == 0


# --- findings filters --------------------------------------------------------


def test_findings_filter_by_pillar(client: TestClient) -> None:
    page = client.get(f"/api/projects/{BAYTEREK}/findings?pillar=p2").json()
    assert page["returned"] >= 1
    assert all(f["pillar_key"] == "p2" for f in page["findings"])
    assert page["total"] >= page["returned"]


def test_findings_filter_by_severity(client: TestClient) -> None:
    page = client.get(f"/api/projects/{BEREKE}/findings?severity=medium").json()
    assert all(f["severity"] == "medium" for f in page["findings"])
    assert page["returned"] > 0


def test_findings_filter_by_type_and_search(client: TestClient) -> None:
    page = client.get(f"/api/projects/{BEREKE}/findings?finding_type=empty_page").json()
    assert all(f["finding_type"] == "empty_page" for f in page["findings"])
    searched = client.get(f"/api/projects/{BEREKE}/findings?search=страница").json()
    assert searched["returned"] >= 1


def test_findings_available_filters(client: TestClient) -> None:
    page = client.get(f"/api/projects/{BEREKE}/findings").json()
    filters = page["available_filters"]
    assert "p1" in filters["pillars"]
    assert all("value" in o and "label" in o and "count" in o for o in filters["finding_types"])
    assert filters["finding_types"][0]["count"] >= filters["finding_types"][-1]["count"]


# --- Blocker 1: P3 remains selectable at zero findings -----------------------


def test_p3_present_in_available_filters_despite_zero_findings(client: TestClient) -> None:
    # Filter list is the registry of implemented pillars, NOT derived from
    # which pillars currently have finding rows.
    for project in (BEREKE, BAYTEREK):
        filters = client.get(f"/api/projects/{project}/findings").json()["available_filters"]
        assert filters["pillars"] == ["p1", "p2", "p3", "p4"]
        assert "p3" in filters["pillars"]


def test_pillar_p3_returns_200_with_zero_findings(client: TestClient) -> None:
    response = client.get(f"/api/projects/{BAYTEREK}/findings?pillar=p3")
    assert response.status_code == 200
    body = response.json()
    assert body["returned"] == 0
    assert body["findings"] == []


def test_selected_p3_filter_state_is_preserved(client: TestClient) -> None:
    # Selecting p3 must not silently reset the available list to "all": p3
    # stays present so the frontend keeps it selected.
    body = client.get(f"/api/projects/{BAYTEREK}/findings?pillar=p3").json()
    assert body["available_filters"]["pillars"] == ["p1", "p2", "p3", "p4"]


# --- Blocker 2: every P2 finding preserves demo/legal-safety metadata --------

_P2_PROJECTS = (
    "project_001_bereke",
    "project_002_azm",
    "project_003_bayterek",
    "project_004_sintez_ural",
)


def _all_p2_findings(client: TestClient) -> list[dict]:
    findings: list[dict] = []
    for project in _P2_PROJECTS:
        findings.extend(
            client.get(f"/api/projects/{project}/findings?pillar=p2").json()["findings"]
        )
    return findings


def test_all_eleven_p2_findings_marked_demo(client: TestClient) -> None:
    findings = _all_p2_findings(client)
    assert len(findings) == 11
    for f in findings:
        assert f["is_demo"] is True, f["finding_id"]
        assert f["is_authoritative"] is False, f["finding_id"]


def test_all_four_demo_notice_findings_marked(client: TestClient) -> None:
    findings = _all_p2_findings(client)
    notices = [f for f in findings if f["finding_type"] == "non_authoritative_demo_requirement"]
    assert len(notices) == 4
    for notice in notices:
        assert notice["is_demo"] is True
        assert notice["is_authoritative"] is False
        detail = client.get(
            f"/api/projects/{notice['project_id']}/findings/{notice['finding_id']}"
        ).json()
        assert detail["demo_warning"] is not None
        assert "источником права" in detail["demo_warning"]
        # No compliance/non-compliance statement is introduced.
        assert "соответствует закон" not in detail["explanation"].lower()


def test_every_p2_finding_detail_has_demo_warning(client: TestClient) -> None:
    for f in _all_p2_findings(client):
        detail = client.get(f"/api/projects/{f['project_id']}/findings/{f['finding_id']}").json()
        assert detail["demo_warning"] is not None


def test_non_p2_findings_are_not_demo(client: TestClient) -> None:
    p1 = client.get(f"/api/projects/{BEREKE}/findings?pillar=p1").json()["findings"]
    assert p1
    for f in p1:
        assert f["is_demo"] is False
        assert f["is_authoritative"] is None  # not a regulatory claim


# --- Blocker 3: unsupported pillar filters are rejected ----------------------


def test_findings_valid_pillar_filters_ok(client: TestClient) -> None:
    for pillar in ("p1", "p2", "p3"):
        response = client.get(f"/api/projects/{BAYTEREK}/findings?pillar={pillar}")
        assert response.status_code == 200, pillar


def test_findings_invalid_pillar_p9_returns_404(client: TestClient) -> None:
    response = client.get(f"/api/projects/{BAYTEREK}/findings?pillar=p9")
    assert response.status_code == 404
    body = response.json()
    assert body == {"error": "pillar_not_found", "detail": "Unknown pillar: p9"}
    assert "Traceback" not in response.text
    assert "/Users/" not in response.text


def test_findings_arbitrary_pillar_returns_404(client: TestClient) -> None:
    response = client.get(f"/api/projects/{BAYTEREK}/findings?pillar=banana")
    assert response.status_code == 404
    assert response.json()["error"] == "pillar_not_found"


def test_findings_roadmap_pillars_rejected_as_filters(client: TestClient) -> None:
    # Roadmap pillars exist in the contract but are NOT selectable filters.
    # (P4 is now implemented and selectable; P5/META remain roadmap.)
    for pillar in ("p5", "meta"):
        response = client.get(f"/api/projects/{BAYTEREK}/findings?pillar={pillar}")
        assert response.status_code == 404, pillar
        assert response.json()["error"] == "pillar_not_found"


def test_findings_sorted_by_severity(client: TestClient) -> None:
    page = client.get(f"/api/projects/{BEREKE}/findings").json()
    order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    ranks = [order[f["severity"]] for f in page["findings"]]
    assert ranks == sorted(ranks)


# --- P1 detail ---------------------------------------------------------------


def test_p1_finding_detail_evidence(client: TestClient) -> None:
    page = client.get(f"/api/projects/{BEREKE}/findings?finding_type=empty_page").json()
    finding_id = page["findings"][0]["finding_id"]
    detail = client.get(f"/api/projects/{BEREKE}/findings/{finding_id}").json()
    assert detail["explanation"]
    assert detail["page_references"]
    assert detail["requirement"] is None  # P1 has no regulatory requirement


# --- reports -----------------------------------------------------------------


def test_report_markdown_demo(client: TestClient) -> None:
    body = client.get(f"/api/projects/{BAYTEREK}/reports/p2").json()
    assert body["format"] == "markdown"
    assert body["is_demo"] is True
    assert "источником права" in body["content"]


def test_report_p3_empty_state(client: TestClient) -> None:
    body = client.get(f"/api/projects/{BEREKE}/reports/p3").json()
    assert "не обнаружено" in body["content"]


# --- error handling ----------------------------------------------------------


def test_missing_project_returns_clean_json(client: TestClient) -> None:
    response = client.get("/api/projects/does_not_exist/summary")
    assert response.status_code == 404
    body = response.json()
    assert body["error"] == "project_not_found"
    assert "does_not_exist" in body["detail"]
    assert "Traceback" not in response.text


def test_missing_finding_returns_404(client: TestClient) -> None:
    response = client.get(f"/api/projects/{BEREKE}/findings/P2__ghost00000000")
    assert response.status_code == 404
    assert response.json()["error"] == "finding_not_found"


def test_unknown_pillar_report_returns_404(client: TestClient) -> None:
    response = client.get(f"/api/projects/{BEREKE}/reports/p9")
    assert response.status_code == 404
    assert response.json()["error"] == "pillar_not_found"


# --- data safety -------------------------------------------------------------


def test_no_absolute_paths_in_responses(client: TestClient) -> None:
    paths = [
        "/api/health",
        "/api/projects",
        "/api/system/metrics",
        f"/api/projects/{BEREKE}",
        f"/api/projects/{BEREKE}/summary",
        f"/api/projects/{BEREKE}/pillars",
        f"/api/projects/{BEREKE}/documents",
        f"/api/projects/{BEREKE}/findings",
        f"/api/projects/{BAYTEREK}/reports/p3",
    ]
    for path in paths:
        text = client.get(path).text
        assert "/Users/" not in text, path
        assert ".venv" not in text, path
        assert "data/results" not in text, path
    # Finding detail too.
    finding_id = client.get(f"/api/projects/{BEREKE}/findings").json()["findings"][0]["finding_id"]
    detail_text = client.get(f"/api/projects/{BEREKE}/findings/{finding_id}").text
    assert "/Users/" not in detail_text

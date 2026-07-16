"""P4 Cross-Document Coherence: normalization, extraction, resolution, checks,
graph, scoring, validation tampering, pipeline, CLI and API integration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from dalel.cli import app
from dalel.pillars.cross_document_coherence.entity_resolution import resolve_entities
from dalel.pillars.cross_document_coherence.extractor import extract_claims, section_evidence_text
from dalel.pillars.cross_document_coherence.normalization import (
    normalize_bin,
    normalize_org_name,
    normalize_period,
    normalize_text,
    strip_legal_form,
)
from dalel.pillars.cross_document_coherence.pipeline import P4Options, P4RunError, run_p4
from dalel.pillars.cross_document_coherence.scoring import (
    cap_severity,
    finding_confidence,
    points_for,
)
from dalel.pillars.cross_document_coherence.validation import validate_p4_outputs
from fixtures.p4_builders import (
    DOC_NDV,
    DOC_PEK,
    PROJECT,
    document,
    section,
    write_dataset,
)

runner = CliRunner()


# --- normalization -----------------------------------------------------------


def test_normalize_org_folds_quote_and_case() -> None:
    a = normalize_org_name("ТОО «Синтез Урал»")[1]
    b = normalize_org_name("ТОО «СИНТЕЗ УРАЛ»")[1]
    c = normalize_org_name('ТОО "Синтез  Урал"')[1]
    assert a == b == c == "синтез урал"


def test_strip_legal_form_separates_prefix() -> None:
    assert strip_legal_form("АО «АЗМ»") == ("АО", "азм")
    assert strip_legal_form("ТОО «X Y»") == ("ТОО", "x y")
    assert strip_legal_form("ИП КХ «Береке»") == ("ИП КХ", "береке")


def test_transliteration_variants_have_distinct_keys() -> None:
    # и/й spelling variants are genuinely different letters: they must NOT be
    # folded lexically (they only merge via a shared explicit identifier).
    assert (
        normalize_org_name("АО «металлоконструкции»")[1]
        != normalize_org_name("АО «металлоконструкций»")[1]
    )


def test_normalize_bin() -> None:
    assert normalize_bin("БИН 010540003201")[-12:] == "010540003201"
    assert normalize_bin("010540003201") == "010540003201"
    assert normalize_bin("12345") is None
    assert normalize_bin("0105400032011") is None  # 13 digits


def test_normalize_period_orders_and_validates() -> None:
    assert normalize_period("2026", "2035") == "2026-2035"
    assert normalize_period("2035", "2026") is None  # inverted
    assert normalize_period("1800", "2035") is None  # out of range


def test_normalize_text_collapses_whitespace() -> None:
    assert normalize_text("  А  Б\nВ ") == "а б в"


# --- helpers -----------------------------------------------------------------


def _sec(document_id: str, index: int, text: str, doc_type: str = "ndv") -> dict[str, Any]:
    return section(document_id, index, text, doc_type=doc_type)


def _run(
    tmp_path: Path,
    documents: list[dict[str, Any]],
    sections: list[dict[str, Any]],
    projects_meta: dict[str, dict[str, Any]] | None = None,
) -> tuple[Any, Path, Path, Path]:
    dataset = write_dataset(tmp_path, documents, sections, projects_meta=projects_meta)
    out = tmp_path / "out"
    ann = tmp_path / "ann"
    result = run_p4(P4Options(dataset_dir=dataset, output_dir=out, annotations_root=ann))
    return result, out, ann, dataset


def _two_doc_operator(bin_ndv: str, bin_pek: str, name: str = "Х-Завод") -> tuple[list, list]:
    docs = [document(DOC_NDV, "ndv"), document(DOC_PEK, "pek")]
    sections = [
        _sec(DOC_NDV, 1, f"Наименование предприятия: АО «{name}» БИН: {bin_ndv}", "ndv"),
        _sec(DOC_PEK, 1, f"Наименование предприятия: АО «{name}» БИН: {bin_pek}", "pek"),
    ]
    return docs, sections


# --- extraction --------------------------------------------------------------


def test_extract_operator_name_and_bin() -> None:
    docs = [document(DOC_NDV, "ndv")]
    sections = [_sec(DOC_NDV, 1, "Наименование предприятия: АО «Завод» БИН: 010540003201")]
    projects = {PROJECT: {}}
    extraction = extract_claims(docs, {DOC_NDV: sections}, {}, {PROJECT: projects[PROJECT]})
    attrs = {c.attribute for c in extraction.claims}
    assert "operator_name" in attrs
    assert "bin" in attrs
    bin_claim = next(c for c in extraction.claims if c.attribute == "bin")
    assert bin_claim.normalized_value == "010540003201"
    assert "role:operator" in bin_claim.qualifiers


def test_designer_marker_wins_over_operator() -> None:
    docs = [document(DOC_NDV, "ndv")]
    sections = [_sec(DOC_NDV, 1, "Проект разработан ТОО «Проектировщик»")]
    extraction = extract_claims(docs, {DOC_NDV: sections}, {}, {PROJECT: {}})
    org = next(c for c in extraction.claims if c.candidate_entity_type == "organization")
    assert org.attribute == "designer_name"


def test_claim_raw_value_grounded_in_section(tmp_path: Path) -> None:
    docs, sections = _two_doc_operator("111111111111", "111111111111")
    _result, out, _ann, dataset = _run(tmp_path, docs, sections)
    validation = validate_p4_outputs(dataset, out)
    assert validation.ok, validation.errors


# --- resolution --------------------------------------------------------------


def test_operator_merged_by_shared_bin() -> None:
    # Same BIN, different name spellings -> single operator, names become aliases.
    docs = [document(DOC_NDV, "ndv"), document(DOC_PEK, "pek")]
    sections = [
        _sec(DOC_NDV, 1, "Наименование предприятия: АО «Завод-и» БИН: 010540003201", "ndv"),
        _sec(DOC_PEK, 1, "Наименование предприятия: АО «Завод-й» БИН: 010540003201", "pek"),
    ]
    extraction = extract_claims(
        docs, {DOC_NDV: [sections[0]], DOC_PEK: [sections[1]]}, {}, {PROJECT: {}}
    )
    resolution = resolve_entities(extraction.claims, {PROJECT: {}}, docs)
    op = resolution.operator_by_project[PROJECT]
    assert op.status == "confirmed_by_identifier"
    operator = next(
        e for e in resolution.entities if e.entity_type == "organization" and e.role == "operator"
    )
    assert operator.identifiers == ["010540003201"]
    assert len(operator.aliases) >= 1  # the other spelling folded as an alias


def test_operator_merged_by_name_without_bin() -> None:
    docs = [document(DOC_NDV, "ndv"), document(DOC_PEK, "pek")]
    sections = [
        _sec(DOC_NDV, 1, "для ТОО «Синтез Урал»", "ndv"),
        _sec(DOC_PEK, 1, "для ТОО «СИНТЕЗ УРАЛ»", "pek"),
    ]
    extraction = extract_claims(
        docs, {DOC_NDV: [sections[0]], DOC_PEK: [sections[1]]}, {}, {PROJECT: {}}
    )
    resolution = resolve_entities(extraction.claims, {PROJECT: {}}, docs)
    assert resolution.operator_by_project[PROJECT].status == "confirmed_by_name"


def test_conflicting_bins_stay_unresolved() -> None:
    docs, sections = _two_doc_operator("111111111111", "222222222222")
    extraction = extract_claims(
        docs, {DOC_NDV: [sections[0]], DOC_PEK: [sections[1]]}, {}, {PROJECT: {}}
    )
    resolution = resolve_entities(extraction.claims, {PROJECT: {}}, docs)
    op = resolution.operator_by_project[PROJECT]
    assert op.status == "conflicting_identifier"
    assert set(op.bins) == {"111111111111", "222222222222"}
    assert any(d.decision == "unresolved" for d in resolution.decisions)


def test_operator_absent_when_no_markers() -> None:
    docs = [document(DOC_NDV, "ndv"), document(DOC_PEK, "pek")]
    sections = [
        _sec(DOC_NDV, 1, "Просто текст без оператора", "ndv"),
        _sec(DOC_PEK, 1, "Ещё текст", "pek"),
    ]
    extraction = extract_claims(
        docs, {DOC_NDV: [sections[0]], DOC_PEK: [sections[1]]}, {}, {PROJECT: {}}
    )
    resolution = resolve_entities(extraction.claims, {PROJECT: {}}, docs)
    assert resolution.operator_by_project[PROJECT].status == "absent"


# --- cross-document checks ---------------------------------------------------


def test_conflicting_operator_finding(tmp_path: Path) -> None:
    docs, sections = _two_doc_operator("111111111111", "222222222222")
    result, _out, _ann, _ds = _run(tmp_path, docs, sections)
    finding = next(f for f in result.findings if f.finding_type == "conflicting_operator")
    assert finding.severity == "medium"  # same name, different explicit BIN
    assert finding.priority_score == points_for("medium")
    assert len(finding.conflicting_claims) == 2


def test_compatible_operator_no_finding(tmp_path: Path) -> None:
    docs, sections = _two_doc_operator("111111111111", "111111111111")
    result, _out, _ann, _ds = _run(tmp_path, docs, sections)
    assert not any(f.finding_type == "conflicting_operator" for f in result.findings)
    assert result.metrics["proven_cross_document_conflicts"] == 0


def test_conflicting_reporting_period(tmp_path: Path) -> None:
    docs = [document(DOC_NDV, "ndv"), document(DOC_PEK, "pek")]
    sections = [
        _sec(DOC_NDV, 1, "Программа на 2026-2035 гг.", "ndv"),
        _sec(DOC_PEK, 1, "Программа на 2027-2036 гг.", "pek"),
    ]
    result, _out, _ann, _ds = _run(tmp_path, docs, sections)
    finding = next(f for f in result.findings if f.finding_type == "conflicting_reporting_period")
    assert finding.severity == "low"


def test_compatible_period_no_finding(tmp_path: Path) -> None:
    docs = [document(DOC_NDV, "ndv"), document(DOC_PEK, "pek")]
    sections = [
        _sec(DOC_NDV, 1, "Программа на 2026-2035 гг.", "ndv"),
        _sec(DOC_PEK, 1, "Программа на 2026-2035 гг.", "pek"),
    ]
    result, _out, _ann, _ds = _run(tmp_path, docs, sections)
    assert not any(f.finding_type == "conflicting_reporting_period" for f in result.findings)


def test_conflicting_location(tmp_path: Path) -> None:
    docs = [document(DOC_NDV, "ndv"), document(DOC_PEK, "pek")]
    sections = [
        _sec(DOC_NDV, 1, "Юридический адрес предприятия: Актюбинская область, г. Хромтау", "ndv"),
        _sec(
            DOC_PEK, 1, "Юридический адрес предприятия: Кызылординская область, г. Байконур", "pek"
        ),
    ]
    result, _out, _ann, _ds = _run(tmp_path, docs, sections)
    assert any(f.finding_type == "conflicting_location" for f in result.findings)


def test_insufficient_context_when_operator_absent(tmp_path: Path) -> None:
    docs = [document(DOC_NDV, "ndv"), document(DOC_PEK, "pek")]
    sections = [_sec(DOC_NDV, 1, "Только числа 123", "ndv"), _sec(DOC_PEK, 1, "И текст", "pek")]
    result, _out, _ann, _ds = _run(tmp_path, docs, sections)
    finding = next(
        f for f in result.findings if f.finding_type == "insufficient_cross_document_context"
    )
    assert finding.severity == "info"


def test_period_scope_mismatch_suppressed(tmp_path: Path) -> None:
    # A design document (roos) period is a different purpose -> suppressed.
    docs = [document(DOC_NDV, "ndv"), document(f"{PROJECT}__roos__001", "roos")]
    sections = [
        _sec(DOC_NDV, 1, "Программа на 2026-2035 гг.", "ndv"),
        _sec(f"{PROJECT}__roos__001", 1, "Рабочий проект на 2020-2021 гг.", "roos"),
    ]
    result, _out, _ann, _ds = _run(tmp_path, docs, sections)
    assert not any(f.finding_type == "conflicting_reporting_period" for f in result.findings)
    assert any(s.check == "reporting_period" for s in result.suppressed)


# --- graph -------------------------------------------------------------------


def test_graph_has_structural_and_operator_edges(tmp_path: Path) -> None:
    docs, sections = _two_doc_operator("111111111111", "111111111111")
    result, _out, _ann, _ds = _run(tmp_path, docs, sections)
    relations = {e.relation for e in result.edges}
    assert "project_contains_document" in relations
    assert "document_identifies_operator" in relations
    entity_ids = {e.entity_id for e in result.entities}
    for edge in result.edges:
        assert edge.source_entity_id in entity_ids
        assert edge.target_entity_id in entity_ids


def test_project_and_document_nodes_present(tmp_path: Path) -> None:
    docs, sections = _two_doc_operator("111111111111", "111111111111")
    result, _out, _ann, _ds = _run(tmp_path, docs, sections)
    types = {e.entity_type for e in result.entities}
    assert "project" in types and "document" in types


# --- scoring -----------------------------------------------------------------


def test_severity_points_scale() -> None:
    assert points_for("medium") == 12
    assert points_for("low") == 5
    assert points_for("info") == 2


def test_cap_severity_never_high() -> None:
    assert cap_severity("high") == "medium"


def test_finding_confidence_recomputes_from_factors() -> None:
    value, factors = finding_confidence("conflicting_operator", ["ocr_source"])
    assert abs(sum(f.delta for f in factors) - value) < 0.001


# --- pipeline determinism ----------------------------------------------------


def test_pipeline_is_byte_deterministic(tmp_path: Path) -> None:
    docs, sections = _two_doc_operator("111111111111", "222222222222")
    dataset = write_dataset(tmp_path, docs, sections)
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    run_p4(P4Options(dataset_dir=dataset, output_dir=out_a, annotations_root=tmp_path / "ann_a"))
    run_p4(P4Options(dataset_dir=dataset, output_dir=out_b, annotations_root=tmp_path / "ann_b"))
    for name in ("claims.jsonl", "entities.jsonl", "edges.jsonl", "findings.jsonl", "metrics.json"):
        assert (out_a / name).read_bytes() == (out_b / name).read_bytes(), name


def test_findings_deterministically_ordered(tmp_path: Path) -> None:
    docs, sections = _two_doc_operator("111111111111", "222222222222")
    _result, out, _ann, dataset = _run(tmp_path, docs, sections)
    validation = validate_p4_outputs(dataset, out)
    assert validation.ok, validation.errors


def test_run_missing_dataset_raises() -> None:
    with pytest.raises(P4RunError):
        run_p4(
            P4Options(
                dataset_dir=Path("/nonexistent/xyz"),
                output_dir=Path("/tmp/none"),
                annotations_root=Path("/tmp/none_ann"),
            )
        )


# --- validation clean --------------------------------------------------------


def _conflict_outputs(tmp_path: Path) -> tuple[Path, Path]:
    docs, sections = _two_doc_operator("111111111111", "222222222222")
    _result, out, _ann, dataset = _run(tmp_path, docs, sections)
    return out, dataset


def test_validation_passes_on_clean_output(tmp_path: Path) -> None:
    out, dataset = _conflict_outputs(tmp_path)
    result = validate_p4_outputs(dataset, out)
    assert result.ok, result.errors


# --- validation tamper -------------------------------------------------------


def _rewrite(path: Path, records: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8"
    )


def _load(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_tamper_entity_id_detected(tmp_path: Path) -> None:
    out, dataset = _conflict_outputs(tmp_path)
    records = _load(out / "entities.jsonl")
    operator = next(r for r in records if r.get("role") == "operator")
    operator["entity_id"] = "P4E__deadbeef0000"
    _rewrite(out / "entities.jsonl", records)
    assert not validate_p4_outputs(dataset, out).ok


def test_tamper_claim_evidence_detected(tmp_path: Path) -> None:
    out, dataset = _conflict_outputs(tmp_path)
    records = _load(out / "claims.jsonl")
    target = next(r for r in records if r["attribute"] == "operator_name")
    target["raw_value"] = "АО «Совсем другое имя»"
    _rewrite(out / "claims.jsonl", records)
    assert not validate_p4_outputs(dataset, out).ok


def test_tamper_edge_endpoint_detected(tmp_path: Path) -> None:
    out, dataset = _conflict_outputs(tmp_path)
    records = _load(out / "edges.jsonl")
    records[0]["target_entity_id"] = "P4E__bogus0000000"
    _rewrite(out / "edges.jsonl", records)
    assert not validate_p4_outputs(dataset, out).ok


def test_tamper_finding_evidence_detected(tmp_path: Path) -> None:
    out, dataset = _conflict_outputs(tmp_path)
    records = _load(out / "findings.jsonl")
    records[0]["claim_ids"] = []  # break the content-derived finding id basis
    _rewrite(out / "findings.jsonl", records)
    assert not validate_p4_outputs(dataset, out).ok


def test_tamper_finding_severity_detected(tmp_path: Path) -> None:
    out, dataset = _conflict_outputs(tmp_path)
    records = _load(out / "findings.jsonl")
    target = next(r for r in records if r["finding_type"] == "conflicting_operator")
    target["severity"] = "low"  # points no longer match
    _rewrite(out / "findings.jsonl", records)
    assert not validate_p4_outputs(dataset, out).ok


def test_tamper_high_severity_rejected(tmp_path: Path) -> None:
    out, dataset = _conflict_outputs(tmp_path)
    records = _load(out / "findings.jsonl")
    target = next(r for r in records if r["finding_type"] == "conflicting_operator")
    target["severity"] = "high"
    target["priority_score"] = 25
    _rewrite(out / "findings.jsonl", records)
    result = validate_p4_outputs(dataset, out)
    assert not result.ok
    assert any("high severity" in e for e in result.errors)


def test_tamper_confidence_detected(tmp_path: Path) -> None:
    out, dataset = _conflict_outputs(tmp_path)
    records = _load(out / "findings.jsonl")
    records[0]["confidence"] = 0.99
    _rewrite(out / "findings.jsonl", records)
    assert not validate_p4_outputs(dataset, out).ok


def test_tamper_project_score_detected(tmp_path: Path) -> None:
    out, dataset = _conflict_outputs(tmp_path)
    records = _load(out / "project_scores.jsonl")
    records[0]["cross_document_coherence_priority_score"] = 77
    _rewrite(out / "project_scores.jsonl", records)
    assert not validate_p4_outputs(dataset, out).ok


def test_tamper_review_template_finding_id_detected(tmp_path: Path) -> None:
    docs, sections = _two_doc_operator("111111111111", "222222222222")
    _result, out, ann, dataset = _run(tmp_path, docs, sections)
    template = ann / "p4_review_template.jsonl"
    rows = _load(template)
    rows[0]["finding_id"] = "P4__tampered0000"
    _rewrite(template, rows)
    result = validate_p4_outputs(dataset, out, annotations_root=ann)
    assert not result.ok


# --- CLI ---------------------------------------------------------------------


def test_cli_run_and_validate_p4(tmp_path: Path) -> None:
    docs, sections = _two_doc_operator("111111111111", "222222222222")
    dataset = write_dataset(tmp_path, docs, sections)
    out = tmp_path / "results"
    run = runner.invoke(
        app,
        ["run-p4", "--dataset", str(dataset), "--output", str(out)],
    )
    assert run.exit_code == 0, run.output
    assert "P4 complete" in run.output
    validate = runner.invoke(app, ["validate-p4", "--dataset", str(dataset), "--output", str(out)])
    assert validate.exit_code == 0, validate.output
    assert "VALID" in validate.output


def test_cli_fail_on_medium(tmp_path: Path) -> None:
    docs, sections = _two_doc_operator("111111111111", "222222222222")
    dataset = write_dataset(tmp_path, docs, sections)
    out = tmp_path / "results"
    run = runner.invoke(
        app,
        ["run-p4", "--dataset", str(dataset), "--output", str(out), "--fail-on", "medium"],
    )
    assert run.exit_code == 1
    assert "FAIL-ON" in run.output


def test_cli_invalid_fail_on() -> None:
    run = runner.invoke(app, ["run-p4", "--fail-on", "bogus"])
    assert run.exit_code == 2


# --- API / frontend contract (over the accepted production artifacts) --------


@pytest.fixture(scope="module")
def client() -> Any:
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from fastapi.testclient import TestClient

    from dalel.api.app import create_app
    from dalel.api.repository import reset_store_cache

    reset_store_cache()
    return TestClient(create_app())


def test_api_health_includes_p4(client: Any) -> None:
    body = client.get("/api/health").json()
    assert "P4" in body["pillars_available"]


def test_api_p4_pillar_summary_fields(client: Any) -> None:
    body = client.get("/api/projects/project_002_azm/summary").json()
    p4 = next(p for p in body["pillars"] if p["pillar_id"] == "P4")
    assert p4["available"] is True
    assert p4["entity_count"] is not None and p4["entity_count"] > 0
    assert p4["linked_document_count"] is not None
    graph = p4["graph"]
    assert graph is not None
    assert "notable_entities" in graph and "confirmed_links" in graph
    operator = next(e for e in graph["notable_entities"] if e["role"] == "operator")
    assert operator["identifiers"] == ["010540003201"]
    # spelling/abbreviation variants folded to aliases, not conflicts
    assert operator["aliases"]


def test_api_p4_reserved_pillar_is_not_spatial(client: Any) -> None:
    body = client.get("/api/projects/project_002_azm/summary").json()
    reserved = {p["pillar_id"] for p in body["reserved_pillars"]}
    assert "P4" not in reserved  # P4 is implemented now
    p4 = next(p for p in body["pillars"] if p["pillar_id"] == "P4")
    assert "простран" not in p4["description"].lower()
    assert "картограф" not in p4["description"].lower()


def test_api_p4_finding_filter_and_empty_state(client: Any) -> None:
    # bereke has zero P4 findings -> selectable filter, honest empty representation.
    page = client.get("/api/projects/project_001_bereke/findings?pillar=p4").json()
    assert page["returned"] == 0
    assert "p4" in page["available_filters"]["pillars"]


def test_api_p4_info_finding_detail(client: Any) -> None:
    page = client.get("/api/projects/project_003_bayterek/findings?pillar=p4").json()
    assert page["returned"] >= 1
    finding_id = page["findings"][0]["finding_id"]
    detail = client.get(f"/api/projects/project_003_bayterek/findings/{finding_id}").json()
    assert detail["severity"] == "info"
    assert "экспертной проверки" in detail["review_notice"]


# ===========================================================================
# Blocker A — organization merges must respect legal form
# ===========================================================================


def _org_resolution(sections_by_doc, documents):
    from dalel.pillars.cross_document_coherence.entity_resolution import resolve_entities
    from dalel.pillars.cross_document_coherence.extractor import extract_claims

    ext = extract_claims(documents, sections_by_doc, {}, {PROJECT: {}})
    return ext, resolve_entities(ext.claims, {PROJECT: {}}, documents)


def test_A_same_name_same_form_no_bin_merges() -> None:
    docs = [document(DOC_NDV, "ndv"), document(DOC_PEK, "pek")]
    sections = {
        DOC_NDV: [_sec(DOC_NDV, 1, "для ТОО «Синтез Урал»", "ndv")],
        DOC_PEK: [_sec(DOC_PEK, 1, "для ТОО «Синтез Урал»", "pek")],
    }
    _ext, res = _org_resolution(sections, docs)
    operators = [
        e for e in res.entities if e.entity_type == "organization" and e.role == "operator"
    ]
    assert len(operators) == 1
    assert res.operator_by_project[PROJECT].status == "confirmed_by_name"


def test_A_same_name_different_forms_no_bin_not_merged() -> None:
    # ТОО «Аяжан» vs АО «Аяжан» as plain mentions → separate, never one node.
    docs = [document(DOC_NDV, "ndv")]
    sections = {
        DOC_NDV: [
            _sec(DOC_NDV, 1, "Подрядчик ТОО «Аяжан» и поставщик АО «Аяжан» участвовали", "ndv")
        ]
    }
    _ext, res = _org_resolution(sections, docs)
    ayajan = [e for e in res.entities if e.normalized_label == "аяжан"]
    assert len(ayajan) == 2  # two distinct legal forms → two entities
    assert any(
        d.decision == "separate" and d.signal == "legal_form_distinct" for d in res.decisions
    )


def test_A_same_name_different_forms_identical_bin_merges() -> None:
    docs = [document(DOC_NDV, "ndv"), document(DOC_PEK, "pek")]
    sections = {
        DOC_NDV: [
            _sec(DOC_NDV, 1, "Наименование предприятия: ТОО «Завод» БИН: 010540003201", "ndv")
        ],
        DOC_PEK: [
            _sec(DOC_PEK, 1, "Наименование предприятия: АО «Завод» БИН: 010540003201", "pek")
        ],
    }
    _ext, res = _org_resolution(sections, docs)
    operators = [
        e for e in res.entities if e.entity_type == "organization" and e.role == "operator"
    ]
    assert len(operators) == 1
    assert operators[0].identifiers == ["010540003201"]
    assert res.operator_by_project[PROJECT].status == "confirmed_by_identifier"


def test_A_abbreviation_plus_full_name_identical_bin_merges() -> None:
    docs = [document(DOC_NDV, "ndv"), document(DOC_PEK, "pek")]
    sections = {
        DOC_NDV: [
            _sec(
                DOC_NDV,
                1,
                "Наименование предприятия: АО «Актюбинский завод» БИН: 010540003201",
                "ndv",
            )
        ],
        DOC_PEK: [_sec(DOC_PEK, 1, "Наименование предприятия: АО «АЗ» БИН: 010540003201", "pek")],
    }
    _ext, res = _org_resolution(sections, docs)
    operator = next(e for e in res.entities if e.role == "operator")
    assert operator.identifiers == ["010540003201"]
    assert operator.aliases  # abbreviation folded as an alias under the shared BIN


def test_A_designer_not_merged_with_operator() -> None:
    docs = [document(DOC_NDV, "ndv")]
    sections = {
        DOC_NDV: [
            _sec(
                DOC_NDV,
                1,
                "Наименование предприятия: АО «Оператор» БИН: 010540003201."
                " Проект разработан ТОО «Проектировщик».",
                "ndv",
            )
        ]
    }
    _ext, res = _org_resolution(sections, docs)
    operator = next(e for e in res.entities if e.role == "operator")
    designers = [e for e in res.entities if e.role == "designer"]
    assert operator.normalized_label == "оператор"
    assert any(d.normalized_label == "проектировщик" for d in designers)
    assert "проектировщик" not in operator.aliases


def test_A_unresolved_identity_no_proven_conflict(tmp_path: Path) -> None:
    # Same name, different legal forms, both marked operator, no BIN → unresolved
    # diagnostic (info), never a proven conflict.
    docs = [document(DOC_NDV, "ndv"), document(DOC_PEK, "pek")]
    sections = [
        _sec(DOC_NDV, 1, "для ТОО «Спорный»", "ndv"),
        _sec(DOC_PEK, 1, "для АО «Спорный»", "pek"),
    ]
    result, _out, _ann, _ds = _run(tmp_path, docs, sections)
    assert result.metrics["proven_cross_document_conflicts"] == 0
    assert res_status(result) == "unresolved"


def res_status(result: Any) -> str:
    types = {f.finding_type for f in result.findings}
    if "unresolved_entity_identity" in types:
        return "unresolved"
    return "other"


# ===========================================================================
# Blocker B — character spans resolve exactly to raw_value
# ===========================================================================


def _all_spans_valid(dataset_dir: Path, out: Path) -> int:
    sections = {
        json.loads(line)["section_id"]: json.loads(line)
        for line in (dataset_dir / "sections.jsonl").read_text().splitlines()
    }
    bad = 0
    for line in (out / "claims.jsonl").read_text().splitlines():
        c = json.loads(line)
        p = c["provenance"]
        if p["source_kind"] != "section_text" or p["char_start"] is None:
            continue
        text = section_evidence_text(sections[p["section_id"]])
        if text[p["char_start"] : p["char_end"]] != c["raw_value"]:
            bad += 1
    return bad


def test_B_spans_valid_repeated_whitespace_and_linebreaks(tmp_path: Path) -> None:
    docs = [document(DOC_NDV, "ndv")]
    sections = [
        _sec(
            DOC_NDV,
            1,
            "Наименование предприятия: ТОО  «Синтез\nУрал»  БИН:  010540003201."
            " Программа на  2026-2035 гг.",
            "ndv",
        )
    ]
    _result, out, _ann, dataset = _run(tmp_path, docs, sections)
    assert _all_spans_valid(dataset, out) == 0
    assert validate_p4_outputs(dataset, out).ok


def test_B_spans_valid_unicode_quotes_and_truncation(tmp_path: Path) -> None:
    docs = [document(DOC_NDV, "ndv")]
    long_obj = "Производство " + "смесевых продуктов и прочих химикатов " * 4
    sections = [
        _sec(DOC_NDV, 1, 'для ТОО "Синтез Урал". ' + long_obj, "ndv"),
    ]
    _result, out, _ann, dataset = _run(tmp_path, docs, sections)
    assert _all_spans_valid(dataset, out) == 0
    assert validate_p4_outputs(dataset, out).ok


def test_B_multiple_occurrences_distinct_spans(tmp_path: Path) -> None:
    docs = [document(DOC_NDV, "ndv")]
    sections = [
        _sec(DOC_NDV, 1, "для ТОО «Альфа». Также упомянута ТОО «Альфа» повторно.", "ndv"),
    ]
    _result, out, _ann, dataset = _run(tmp_path, docs, sections)
    # both occurrences resolve exactly; validator passes
    assert _all_spans_valid(dataset, out) == 0
    assert validate_p4_outputs(dataset, out).ok


def test_B_validator_rejects_tampered_span(tmp_path: Path) -> None:
    out, dataset = _conflict_outputs(tmp_path)
    records = _load(out / "claims.jsonl")
    target = next(r for r in records if r["provenance"]["char_start"] is not None)
    target["provenance"]["char_end"] = target["provenance"]["char_start"] + 1  # break the span
    _rewrite(out / "claims.jsonl", records)
    assert not validate_p4_outputs(dataset, out).ok


# ===========================================================================
# Blocker C — validator rejects material tampering
# ===========================================================================


def _bayterek_absent_outputs(tmp_path: Path) -> tuple[Path, Path]:
    # Two documents with NO operator markers → insufficient_cross_document_context.
    docs = [document(DOC_NDV, "roos"), document(DOC_PEK, "explanatory_note")]
    sections = [
        _sec(DOC_NDV, 1, "Рабочий проект строительства без сведений об операторе", "roos"),
        _sec(DOC_PEK, 1, "Пояснительная записка к проекту", "explanatory_note"),
    ]
    _result, out, _ann, dataset = _run(tmp_path, docs, sections)
    return out, dataset


def test_C_valid_output_passes(tmp_path: Path) -> None:
    out, dataset = _bayterek_absent_outputs(tmp_path)
    assert validate_p4_outputs(dataset, out).ok


def test_C_unrelated_resolution_claim_rejected(tmp_path: Path) -> None:
    out, dataset = _conflict_outputs(tmp_path)
    decisions = _load(out / "resolution_decisions.jsonl")
    claims = {c["claim_id"] for c in _load(out / "claims.jsonl")}
    target = next(d for d in decisions if d["claim_ids"])
    unrelated = next(cid for cid in sorted(claims) if cid not in target["claim_ids"])
    target["claim_ids"][0] = unrelated
    _rewrite(out / "resolution_decisions.jsonl", decisions)
    assert not validate_p4_outputs(dataset, out).ok


def test_C_altered_resolution_reason_rejected(tmp_path: Path) -> None:
    out, dataset = _conflict_outputs(tmp_path)
    decisions = _load(out / "resolution_decisions.jsonl")
    decisions[0]["reason"] = "сфабрикованная причина слияния"
    _rewrite(out / "resolution_decisions.jsonl", decisions)
    assert not validate_p4_outputs(dataset, out).ok


def test_C_fabricated_finding_evidence_note_rejected(tmp_path: Path) -> None:
    out, dataset = _bayterek_absent_outputs(tmp_path)
    findings = _load(out / "findings.jsonl")
    findings[0]["evidence"][0]["note"] = "Оператор точно отсутствует (сфабриковано)"
    _rewrite(out / "findings.jsonl", findings)
    assert not validate_p4_outputs(dataset, out).ok


def test_C_altered_inspected_document_rejected(tmp_path: Path) -> None:
    out, dataset = _bayterek_absent_outputs(tmp_path)
    findings = _load(out / "findings.jsonl")
    findings[0]["package_check"]["inspected_document_ids"][0] = f"{PROJECT}__ghost__001"
    _rewrite(out / "findings.jsonl", findings)
    assert not validate_p4_outputs(dataset, out).ok


def test_C_altered_checked_attribute_rejected(tmp_path: Path) -> None:
    out, dataset = _bayterek_absent_outputs(tmp_path)
    findings = _load(out / "findings.jsonl")
    findings[0]["package_check"]["checked_attributes"] = ["something_else"]
    _rewrite(out / "findings.jsonl", findings)
    assert not validate_p4_outputs(dataset, out).ok


def test_C_altered_zero_match_count_rejected(tmp_path: Path) -> None:
    out, dataset = _bayterek_absent_outputs(tmp_path)
    findings = _load(out / "findings.jsonl")
    findings[0]["package_check"]["qualifying_claims_found"] = 3
    _rewrite(out / "findings.jsonl", findings)
    assert not validate_p4_outputs(dataset, out).ok


def test_C_altered_finding_explanation_rejected(tmp_path: Path) -> None:
    out, dataset = _bayterek_absent_outputs(tmp_path)
    findings = _load(out / "findings.jsonl")
    findings[0]["explanation"] = "Произвольное пояснение"
    _rewrite(out / "findings.jsonl", findings)
    assert not validate_p4_outputs(dataset, out).ok


# ===========================================================================
# Activity-identity-gate suppression — validator tamper detection
# ===========================================================================


def _activity_identity_suppressed_outputs(tmp_path: Path) -> tuple[Path, Path]:
    # No operator markers at all + two incompatible structured categories →
    # the new "activity_identity_not_established" suppression. An unrelated
    # designer-name claim is included so tamper tests have a distinct,
    # unreferenced claim to substitute in.
    docs = [document(DOC_NDV, "ndv"), document(DOC_PEK, "pek")]
    sections = [
        _sec(DOC_NDV, 1, "Категория объекта: II. Проект разработан ТОО «Инженер».", "ndv"),
        _sec(DOC_PEK, 1, "Категория объекта: III.", "pek"),
    ]
    _result, out, _ann, dataset = _run(tmp_path, docs, sections)
    return out, dataset


def _activity_identity_suppression(records: list[dict[str, Any]]) -> dict[str, Any]:
    return next(
        r
        for r in records
        if r["check"] == "activity" and r["reason"] == "activity_identity_not_established"
    )


def test_activity_identity_suppression_valid_output_passes(tmp_path: Path) -> None:
    out, dataset = _activity_identity_suppressed_outputs(tmp_path)
    assert validate_p4_outputs(dataset, out).ok


def test_activity_identity_suppression_reason_tamper_rejected(tmp_path: Path) -> None:
    out, dataset = _activity_identity_suppressed_outputs(tmp_path)
    records = _load(out / "suppressed_comparisons.jsonl")
    target = _activity_identity_suppression(records)
    target["reason"] = "unspecific_category_not_comparable"
    _rewrite(out / "suppressed_comparisons.jsonl", records)
    assert not validate_p4_outputs(dataset, out).ok


def test_activity_identity_suppression_claim_id_tamper_rejected(tmp_path: Path) -> None:
    out, dataset = _activity_identity_suppressed_outputs(tmp_path)
    records = _load(out / "suppressed_comparisons.jsonl")
    claims = {c["claim_id"] for c in _load(out / "claims.jsonl")}
    target = _activity_identity_suppression(records)
    unrelated = next(cid for cid in sorted(claims) if cid not in target["claim_ids"])
    target["claim_ids"][0] = unrelated
    _rewrite(out / "suppressed_comparisons.jsonl", records)
    assert not validate_p4_outputs(dataset, out).ok


def test_activity_identity_suppression_identity_status_tamper_rejected(tmp_path: Path) -> None:
    out, dataset = _activity_identity_suppressed_outputs(tmp_path)
    records = _load(out / "suppressed_comparisons.jsonl")
    target = _activity_identity_suppression(records)
    target["detail"] = target["detail"].replace("absent", "confirmed_by_identifier")
    _rewrite(out / "suppressed_comparisons.jsonl", records)
    assert not validate_p4_outputs(dataset, out).ok


# ===========================================================================
# Blocker C / §6 — Bayterek-style finding carries structured provenance
# ===========================================================================


def test_bayterek_finding_structured_provenance(tmp_path: Path) -> None:
    out, _dataset = _bayterek_absent_outputs(tmp_path)
    finding = _load(out / "findings.jsonl")[0]
    assert finding["finding_type"] == "insufficient_cross_document_context"
    assert finding["severity"] == "info"
    pc = finding["package_check"]
    assert pc["check"] == "operator_identity"
    assert pc["entity_type"] == "organization"
    assert pc["role"] == "operator"
    assert pc["checked_attributes"] == ["bin", "operator_name"]
    assert len(pc["inspected_document_ids"]) == 2
    assert pc["qualifying_claims_found"] == 0
    # evidence references the inspected documents, not a fabricated absence quote
    assert {e["document_id"] for e in finding["evidence"]} == set(pc["inspected_document_ids"])
    assert all(e["quote"] is None for e in finding["evidence"])
    assert finding["observed_value"] == "0"


# ===========================================================================
# Blocker D — explicit activity/category conflict check
# ===========================================================================


def _operator_prefix(bin_value: str | None) -> str:
    if not bin_value:
        return ""
    return f"Наименование предприятия: АО «Завод» БИН: {bin_value}. "


def _category_run(
    tmp_path: Path,
    ndv_cat: str,
    pek_cat: str,
    pek_type: str = "pek",
    extra_ndv: str = "",
    extra_pek: str = "",
    ndv_operator_bin: str | None = None,
    pek_operator_bin: str | None = None,
) -> Any:
    docs = [document(DOC_NDV, "ndv"), document(DOC_PEK, pek_type)]
    sections = [
        _sec(
            DOC_NDV,
            1,
            f"{_operator_prefix(ndv_operator_bin)}Категория объекта: {ndv_cat}. {extra_ndv}",
            "ndv",
        ),
        _sec(
            DOC_PEK,
            1,
            f"{_operator_prefix(pek_operator_bin)}Категория объекта: {pek_cat}. {extra_pek}",
            pek_type,
        ),
    ]
    result, _out, _ann, _ds = _run(tmp_path, docs, sections)
    return result


_SHARED_BIN = "010540003201"


def test_D_incompatible_structured_categories_conflict(tmp_path: Path) -> None:
    # Regression test 1: same resolved operator (shared BIN) + incompatible
    # structured categories → produces conflicting_activity_or_category.
    result = _category_run(
        tmp_path, "II", "III", ndv_operator_bin=_SHARED_BIN, pek_operator_bin=_SHARED_BIN
    )
    finding = next(
        f for f in result.findings if f.finding_type == "conflicting_activity_or_category"
    )
    assert finding.severity in ("medium", "low")
    assert len(finding.conflicting_claims) == 2
    assert finding.entity_ids  # anchored to the resolved operator entity
    assert result.metrics["proven_cross_document_conflicts"] >= 1


def test_D_equivalent_aliases_no_conflict(tmp_path: Path) -> None:
    # Regression test 2: same resolved operator + equivalent aliases → no conflict.
    result = _category_run(
        tmp_path,
        "food_production",
        "пищевое производство",
        ndv_operator_bin=_SHARED_BIN,
        pek_operator_bin=_SHARED_BIN,
    )
    assert not any(f.finding_type == "conflicting_activity_or_category" for f in result.findings)


def test_D_compatible_hierarchy_alias_no_conflict(tmp_path: Path) -> None:
    result = _category_run(
        tmp_path,
        "construction_materials",
        "стройматериалы",
        ndv_operator_bin=_SHARED_BIN,
        pek_operator_bin=_SHARED_BIN,
    )
    assert not any(f.finding_type == "conflicting_activity_or_category" for f in result.findings)


def test_D_scope_mismatch_suppressed(tmp_path: Path) -> None:
    # category from a design document (roos) is out of the permit-package scope
    result = _category_run(tmp_path, "II", "III", pek_type="roos")
    assert not any(f.finding_type == "conflicting_activity_or_category" for f in result.findings)
    assert any(
        s.check == "activity" and s.reason == "different_document_purpose"
        for s in result.suppressed
    )


def test_D_reporting_period_mismatch_suppressed(tmp_path: Path) -> None:
    # Identity established (shared BIN) so the reporting-context gate — not the
    # identity gate — is the one actually exercised here.
    result = _category_run(
        tmp_path,
        "II",
        "III",
        extra_ndv="на 2026-2035 гг",
        extra_pek="на 2028-2037 гг",
        ndv_operator_bin=_SHARED_BIN,
        pek_operator_bin=_SHARED_BIN,
    )
    assert not any(f.finding_type == "conflicting_activity_or_category" for f in result.findings)
    assert any(
        s.check == "activity" and s.reason == "reporting_context_mismatch"
        for s in result.suppressed
    )


def test_D_no_identity_incompatible_categories_suppressed(tmp_path: Path) -> None:
    # Regression test 3: no resolved operator/facility identity + incompatible
    # structured categories → no conflict; deterministic unresolved-identity
    # suppression instead.
    result = _category_run(tmp_path, "II", "III")
    assert not any(f.finding_type == "conflicting_activity_or_category" for f in result.findings)
    suppression = next(
        s
        for s in result.suppressed
        if s.check == "activity" and s.reason == "activity_identity_not_established"
    )
    assert suppression.attribute == "category"
    assert len(suppression.claim_ids) == 2
    assert "absent" in suppression.detail
    # explicitly states categories are NOT claimed compatible — only incomparable
    assert "не означает, что категории совместимы" in suppression.detail


def test_D_conflicting_operators_incompatible_categories_suppressed(tmp_path: Path) -> None:
    # Regression test 4: different explicit operators (conflicting BINs) +
    # incompatible categories → no activity conflict; suppression.
    result = _category_run(
        tmp_path,
        "II",
        "III",
        ndv_operator_bin="111111111111",
        pek_operator_bin="222222222222",
    )
    assert not any(f.finding_type == "conflicting_activity_or_category" for f in result.findings)
    suppression = next(
        s
        for s in result.suppressed
        if s.check == "activity" and s.reason == "activity_identity_not_established"
    )
    assert "conflicting_identifier" in suppression.detail
    # the conflicting-identifier candidate entities are referenced for traceability
    assert suppression.entity_ids


def test_D_missing_identity_info_finding_remains_no_medium_conflict(tmp_path: Path) -> None:
    # Regression test 5: missing operator identity + insufficient context — the
    # info finding may remain, but no medium activity conflict is emitted. This
    # is the exact combination originally reported as the blocker.
    result = _category_run(tmp_path, "II", "III")
    assert any(f.finding_type == "insufficient_cross_document_context" for f in result.findings)
    assert not any(
        f.finding_type == "conflicting_activity_or_category" and f.severity == "medium"
        for f in result.findings
    )
    assert not any(f.finding_type == "conflicting_activity_or_category" for f in result.findings)


def test_D_free_text_object_suppressed_not_conflict(tmp_path: Path) -> None:
    # Regression test 6: free-text activity claims remain
    # free_text_activity_scope_uncertain (unaffected by the identity gate, which
    # applies only to structured category claims).
    docs = [document(DOC_NDV, "ndv"), document(DOC_PEK, "pek")]
    sections = [
        _sec(DOC_NDV, 1, "Производство подсолнечного масла на площадке", "ndv"),
        _sec(DOC_PEK, 1, "Производство металлоконструкций и профиля", "pek"),
    ]
    result, _out, _ann, _ds = _run(tmp_path, docs, sections)
    assert not any(f.finding_type == "conflicting_activity_or_category" for f in result.findings)
    assert any(s.reason == "free_text_activity_scope_uncertain" for s in result.suppressed)


def test_D_no_false_production_finding() -> None:
    # Regression test 7: the accepted production corpus has no explicit
    # category label → zero category claims → zero activity/category
    # contradictions, even after the identity gate is applied end to end.
    from dalel.pillars.cross_document_coherence.checks import run_checks
    from dalel.pillars.cross_document_coherence.entity_resolution import resolve_entities
    from dalel.pillars.cross_document_coherence.extractor import extract_claims

    projects = {
        json.loads(line)["project_id"]: json.loads(line)
        for line in Path("data/curated/v1/projects.jsonl").read_text().splitlines()
    }
    documents = [
        json.loads(line)
        for line in Path("data/curated/v1/documents.jsonl").read_text().splitlines()
    ]
    by_doc: dict[str, list[Any]] = {}
    for line in Path("data/curated/v1/sections.jsonl").read_text().splitlines():
        record = json.loads(line)
        by_doc.setdefault(record["provenance"]["document_id"], []).append(record)
    ext = extract_claims(documents, by_doc, {}, projects)
    assert not any(c.attribute == "category" for c in ext.claims)

    resolution = resolve_entities(ext.claims, projects, documents)
    checks = run_checks(ext.claims, resolution.operator_by_project, projects, documents)
    assert not any(f.finding_type == "conflicting_activity_or_category" for f in checks.findings)

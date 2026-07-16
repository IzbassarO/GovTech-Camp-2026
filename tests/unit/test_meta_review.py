from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from dalel.meta_review.calibration import (
    ExperimentalCalibrationFixture,
    production_calibration_metadata,
    scan_expert_labels,
)
from dalel.meta_review.pipeline import MetaRunError, run_meta
from dalel.meta_review.schemas import MetaFeatureRecord
from dalel.meta_review.scoring import priority_level
from dalel.meta_review.validation import validate_meta
from fixtures.meta_builders import (
    DOC_B,
    PROJECT,
    load_jsonl,
    make_p1_finding,
    make_p2_finding,
    make_p3_finding,
    make_p4_finding,
    rewrite_jsonl,
    write_meta_inputs,
)

OUTPUT_FILES = {
    "features.jsonl",
    "project_assessments.jsonl",
    "pillar_contributions.jsonl",
    "feature_contributions.jsonl",
    "metrics.json",
    "config_snapshot.json",
    "calibration_metadata.json",
    "model_metadata.json",
    "report.md",
}


def _run(paths: dict[str, Path], output: Path) -> Any:
    return run_meta(
        paths["P1"],
        paths["P2"],
        paths["P3"],
        paths["P4"],
        output,
        paths["annotations"],
    )


def _validate(paths: dict[str, Path], output: Path) -> Any:
    return validate_meta(
        paths["P1"],
        paths["P2"],
        paths["P3"],
        paths["P4"],
        output,
        paths["annotations"],
    )


def _score(paths: dict[str, Path], output: Path) -> float:
    return _run(paths, output).assessments[0].review_priority_score


def test_feature_schema_is_strict() -> None:
    payload = {
        "feature_id": "META_F__111111111111",
        "project_id": PROJECT,
        "feature_name": "fixture",
        "pillar_source": "P1",
        "raw_value": 1,
        "normalized_value": 0.5,
        "weight": 2.0,
        "contribution": 1.0,
        "source_artifact_ids": [],
        "source_finding_ids": [],
        "explanation": "fixture",
        "limitations": [],
        "unexpected": True,
    }
    with pytest.raises(ValidationError):
        MetaFeatureRecord.model_validate(payload)


@pytest.mark.parametrize(
    ("score", "level"),
    [(0.0, "low"), (25.0, "moderate"), (50.0, "elevated"), (75.0, "high")],
)
def test_priority_level_thresholds(score: float, level: str) -> None:
    assert priority_level(score) == level


def test_synthetic_calibration_fixture_requires_explicit_flag() -> None:
    with pytest.raises(ValidationError, match="experimental_test_only"):
        ExperimentalCalibrationFixture(
            experimental_test_only=False,
            labels=[0, 1],
            raw_scores=[0.1, 0.9],
            project_groups=["a", "b"],
        )


def test_synthetic_calibration_fixture_enforces_alignment() -> None:
    with pytest.raises(ValidationError, match="equal length"):
        ExperimentalCalibrationFixture(
            experimental_test_only=True,
            labels=[0, 1],
            raw_scores=[0.1],
            project_groups=["a", "b"],
        )


def test_pipeline_writes_required_artifacts(tmp_path: Path) -> None:
    paths = write_meta_inputs(tmp_path / "inputs")
    output = tmp_path / "output"
    _run(paths, output)
    assert {path.name for path in output.iterdir()} == OUTPUT_FILES


def test_clean_output_validates(tmp_path: Path) -> None:
    paths = write_meta_inputs(tmp_path / "inputs")
    output = tmp_path / "output"
    _run(paths, output)
    result = _validate(paths, output)
    assert result.ok, result.errors
    assert result.counts["projects"] == 1


def test_pipeline_is_byte_deterministic(tmp_path: Path) -> None:
    paths = write_meta_inputs(tmp_path / "inputs")
    output_a = tmp_path / "a"
    output_b = tmp_path / "b"
    _run(paths, output_a)
    _run(paths, output_b)
    for name in sorted(OUTPUT_FILES):
        assert (output_a / name).read_bytes() == (output_b / name).read_bytes(), name


def test_exact_additive_decomposition(tmp_path: Path) -> None:
    paths = write_meta_inputs(tmp_path / "inputs")
    assessment = _run(paths, tmp_path / "output").assessments[0]
    assert assessment.review_priority_score == round(
        assessment.base_score
        + sum(item.contribution for item in assessment.feature_contributions)
        + assessment.uncertainty_adjustment
        + assessment.global_cap_adjustment,
        2,
    )
    for pillar in assessment.pillar_contributions:
        assert pillar.subtotal == round(
            pillar.raw_subtotal + pillar.discount_amount + pillar.cap_adjustment, 2
        )


def test_p2_synthetic_contribution_is_discounted_and_capped(tmp_path: Path) -> None:
    paths = write_meta_inputs(tmp_path / "inputs")
    assessment = _run(paths, tmp_path / "output").assessments[0]
    p2 = next(item for item in assessment.pillar_contributions if item.pillar_id == "P2")
    assert p2.discount_factor == 0.35
    assert p2.cap == 8.0
    assert p2.subtotal <= 8.0
    assert p2.discounts_applied and p2.caps_applied


def test_production_has_no_probability_or_shap(tmp_path: Path) -> None:
    paths = write_meta_inputs(tmp_path / "inputs")
    assessment = _run(paths, tmp_path / "output").assessments[0]
    assert assessment.calibration_status == "not_available_without_expert_labels"
    assert assessment.calibrated_probability is None
    assert assessment.shap_contributions is None
    assert assessment.model_metadata.model_status == "not_trained"


def test_all_positive_features_are_traceable(tmp_path: Path) -> None:
    paths = write_meta_inputs(tmp_path / "inputs")
    assessment = _run(paths, tmp_path / "output").assessments[0]
    for feature in assessment.feature_contributions:
        if feature.contribution > 0:
            assert feature.source_artifact_ids or feature.source_finding_ids


def test_review_templates_have_no_completed_labels(tmp_path: Path) -> None:
    paths = write_meta_inputs(tmp_path / "inputs")
    summary = scan_expert_labels(paths["annotations"])
    metadata = production_calibration_metadata(summary)
    assert summary.completed_labels == 0
    assert metadata.calibrated_probability is None


def test_completed_expert_decision_is_counted_but_does_not_auto_train(tmp_path: Path) -> None:
    paths = write_meta_inputs(tmp_path / "inputs")
    template = paths["annotations"] / "p1_review_template.jsonl"
    rows = load_jsonl(template)
    rows[0]["expert_decision"] = "confirmed"
    rewrite_jsonl(template, rows)
    summary = scan_expert_labels(paths["annotations"])
    metadata = production_calibration_metadata(summary)
    assert summary.completed_labels == 1
    assert metadata.calibration_status == "not_available_without_expert_labels"


def test_missing_pillar_reduces_coverage_and_is_visible(tmp_path: Path) -> None:
    complete = write_meta_inputs(tmp_path / "complete")
    missing = write_meta_inputs(tmp_path / "missing", missing={"P3"})
    full_assessment = _run(complete, tmp_path / "full_output").assessments[0]
    missing_assessment = _run(missing, tmp_path / "missing_output").assessments[0]
    assert missing_assessment.evidence_coverage < full_assessment.evidence_coverage
    assert missing_assessment.assessment_confidence < full_assessment.assessment_confidence
    p3 = next(item for item in missing_assessment.pillar_contributions if item.pillar_id == "P3")
    assert p3.available is False
    assert any("не считаются пройденными" in text for text in missing_assessment.limitations)


def test_missing_zero_signal_pillar_does_not_create_safe_bonus(tmp_path: Path) -> None:
    complete = write_meta_inputs(tmp_path / "complete")
    missing = write_meta_inputs(tmp_path / "missing", missing={"P3"})
    full = _run(complete, tmp_path / "full_output").assessments[0]
    partial = _run(missing, tmp_path / "missing_output").assessments[0]
    assert partial.review_priority_score == full.review_priority_score
    assert partial.assessment_confidence < full.assessment_confidence


def test_high_severity_p1_finding_cannot_lower_priority(tmp_path: Path) -> None:
    paths = write_meta_inputs(tmp_path / "inputs")
    baseline = _score(paths, tmp_path / "baseline")
    findings = load_jsonl(paths["P1"] / "findings.jsonl")
    findings.append(make_p1_finding("P1__222222222222", "structural_anomaly", "high"))
    rewrite_jsonl(paths["P1"] / "findings.jsonl", findings)
    assert _score(paths, tmp_path / "changed") >= baseline


def test_authoritative_p2_conflict_cannot_lower_priority(tmp_path: Path) -> None:
    paths = write_meta_inputs(tmp_path / "inputs")
    baseline = _score(paths, tmp_path / "baseline")
    assessments = load_jsonl(paths["P2"] / "assessments.jsonl")
    assessments.append(
        {
            "assessment_id": "P2A__333333333333",
            "project_id": PROJECT,
            "label": "potential_conflict",
            "confidence": 0.9,
            "requirement_is_authoritative": True,
            "retrieval_id": "P2R__333333333333",
            "evidence_ids": ["P2E__333333333333"],
        }
    )
    rewrite_jsonl(paths["P2"] / "assessments.jsonl", assessments)
    retrievals = load_jsonl(paths["P2"] / "retrievals.jsonl")
    retrievals.append({"project_id": PROJECT, "retrieval_id": "P2R__333333333333"})
    rewrite_jsonl(paths["P2"] / "retrievals.jsonl", retrievals)
    assert _score(paths, tmp_path / "changed") >= baseline


def test_synthetic_p2_info_notice_has_zero_score_effect(tmp_path: Path) -> None:
    paths = write_meta_inputs(tmp_path / "inputs")
    baseline = _score(paths, tmp_path / "baseline")
    findings = load_jsonl(paths["P2"] / "findings.jsonl")
    findings.append(
        make_p2_finding("P2__222222222222", "non_authoritative_demo_requirement", "info")
    )
    rewrite_jsonl(paths["P2"] / "findings.jsonl", findings)
    assert _score(paths, tmp_path / "changed") == baseline


def test_proven_p3_conflict_increases_priority(tmp_path: Path) -> None:
    paths = write_meta_inputs(tmp_path / "inputs")
    baseline = _score(paths, tmp_path / "baseline")
    rewrite_jsonl(
        paths["P3"] / "findings.jsonl",
        [make_p3_finding("P3__222222222222", "direct_value_conflict", "high")],
    )
    assert _score(paths, tmp_path / "changed") > baseline


def test_proven_p4_conflict_increases_priority(tmp_path: Path) -> None:
    paths = write_meta_inputs(tmp_path / "inputs")
    baseline = _score(paths, tmp_path / "baseline")
    rewrite_jsonl(
        paths["P4"] / "findings.jsonl",
        [make_p4_finding("P4__222222222222", "conflicting_operator", "medium")],
    )
    assert _score(paths, tmp_path / "changed") > baseline


def test_more_p3_suppression_reduces_confidence(tmp_path: Path) -> None:
    paths = write_meta_inputs(tmp_path / "inputs")
    baseline = _run(paths, tmp_path / "baseline").assessments[0].assessment_confidence
    candidates = load_jsonl(paths["P3"] / "candidates.jsonl")
    for index in range(3, 13):
        candidates.append(
            {
                "project_id": PROJECT,
                "candidate_id": f"P3C__{index:012x}",
                "status": "suppressed",
            }
        )
    rewrite_jsonl(paths["P3"] / "candidates.jsonl", candidates)
    changed = _run(paths, tmp_path / "changed").assessments[0].assessment_confidence
    assert changed < baseline


def test_score_remains_bounded_under_many_findings(tmp_path: Path) -> None:
    paths = write_meta_inputs(tmp_path / "inputs")
    rewrite_jsonl(
        paths["P1"] / "findings.jsonl",
        [
            make_p1_finding(
                f"P1__{index:012x}", "structural_anomaly", "high", document_id=f"doc_p1_{index}"
            )
            for index in range(1, 51)
        ],
    )
    rewrite_jsonl(
        paths["P3"] / "findings.jsonl",
        [
            make_p3_finding(
                f"P3__{index:012x}", "direct_value_conflict", "high", document_id=f"doc_p3_{index}"
            )
            for index in range(1, 51)
        ],
    )
    rewrite_jsonl(
        paths["P4"] / "findings.jsonl",
        [
            make_p4_finding(
                f"P4__{index:012x}", "conflicting_operator", "medium", document_id=f"doc_p4_{index}"
            )
            for index in range(1, 51)
        ],
    )
    assert _score(paths, tmp_path / "output") <= 100.0


def test_one_p4_info_finding_cannot_dominate(tmp_path: Path) -> None:
    paths = write_meta_inputs(tmp_path / "inputs")
    baseline = _score(paths, tmp_path / "baseline")
    rewrite_jsonl(
        paths["P4"] / "findings.jsonl",
        [make_p4_finding("P4__222222222222", "insufficient_cross_document_context", "info")],
    )
    assert _score(paths, tmp_path / "changed") - baseline <= 1.0


def test_counterfactual_does_not_claim_compliance(tmp_path: Path) -> None:
    paths = write_meta_inputs(tmp_path / "inputs")
    text = _run(paths, tmp_path / "output").assessments[0].counterfactual_explanation
    assert "не доказывает соответствие" in text


def test_top_factors_are_deterministically_ordered(tmp_path: Path) -> None:
    paths = write_meta_inputs(tmp_path / "inputs")
    factors = _run(paths, tmp_path / "output").assessments[0].top_positive_factors
    assert [item.contribution for item in factors] == sorted(
        [item.contribution for item in factors], reverse=True
    )


def test_project_alignment_mismatch_is_rejected(tmp_path: Path) -> None:
    paths = write_meta_inputs(tmp_path / "inputs")
    rows = load_jsonl(paths["P4"] / "project_scores.jsonl")
    rows[0]["project_id"] = "project_other"
    rewrite_jsonl(paths["P4"] / "project_scores.jsonl", rows)
    with pytest.raises(MetaRunError, match=r"project alignment|unknown project_id"):
        _run(paths, tmp_path / "output")


def test_exact_duplicate_p1_finding_is_rejected_before_scoring(tmp_path: Path) -> None:
    paths = write_meta_inputs(tmp_path / "inputs")
    findings = load_jsonl(paths["P1"] / "findings.jsonl")
    findings.append(dict(findings[0]))
    rewrite_jsonl(paths["P1"] / "findings.jsonl", findings)
    output = tmp_path / "output"
    with pytest.raises(MetaRunError, match="duplicate"):
        _run(paths, output)
    assert not output.exists()


def test_duplicate_p1_finding_id_with_modified_content_is_rejected(tmp_path: Path) -> None:
    paths = write_meta_inputs(tmp_path / "inputs")
    findings = load_jsonl(paths["P1"] / "findings.jsonl")
    mutated = dict(findings[0])
    mutated["severity"] = "high"
    findings.append(mutated)
    rewrite_jsonl(paths["P1"] / "findings.jsonl", findings)
    with pytest.raises(MetaRunError, match="duplicate record ID"):
        _run(paths, tmp_path / "output")


def test_duplicate_finding_content_with_mutated_id_is_rejected(tmp_path: Path) -> None:
    paths = write_meta_inputs(tmp_path / "inputs")
    findings = load_jsonl(paths["P1"] / "findings.jsonl")
    same_content_new_id = dict(findings[0])
    same_content_new_id["finding_id"] = "P1__000000000000"
    findings.append(same_content_new_id)
    rewrite_jsonl(paths["P1"] / "findings.jsonl", findings)
    with pytest.raises(MetaRunError, match="duplicate record content"):
        _run(paths, tmp_path / "output")


def test_findings_with_same_type_and_severity_but_different_evidence_are_not_deduped(
    tmp_path: Path,
) -> None:
    paths = write_meta_inputs(tmp_path / "inputs")
    findings = load_jsonl(paths["P1"] / "findings.jsonl")
    distinct_document = dict(findings[0])
    distinct_document["finding_id"] = "P1__222222222222"
    distinct_document["document_id"] = DOC_B
    findings.append(distinct_document)
    rewrite_jsonl(paths["P1"] / "findings.jsonl", findings)
    result = _run(paths, tmp_path / "output")
    medium_feature = next(
        item for item in result.features if item.feature_name == "p1_medium_severity_rate"
    )
    assert medium_feature.raw_value == 2
    assert len(result.assessments) == 1


def test_duplicate_p1_document_score_is_rejected(tmp_path: Path) -> None:
    paths = write_meta_inputs(tmp_path / "inputs")
    rows = load_jsonl(paths["P1"] / "document_scores.jsonl")
    rows.append(dict(rows[0]))
    rewrite_jsonl(paths["P1"] / "document_scores.jsonl", rows)
    with pytest.raises(MetaRunError, match="duplicate record ID"):
        _run(paths, tmp_path / "output")


def test_duplicate_p2_finding_is_rejected(tmp_path: Path) -> None:
    paths = write_meta_inputs(tmp_path / "inputs")
    findings = load_jsonl(paths["P2"] / "findings.jsonl")
    findings.append(dict(findings[0]))
    rewrite_jsonl(paths["P2"] / "findings.jsonl", findings)
    with pytest.raises(MetaRunError, match="duplicate"):
        _run(paths, tmp_path / "output")


def test_duplicate_p3_candidate_is_rejected(tmp_path: Path) -> None:
    paths = write_meta_inputs(tmp_path / "inputs")
    rows = load_jsonl(paths["P3"] / "candidates.jsonl")
    rows.append(dict(rows[0]))
    rewrite_jsonl(paths["P3"] / "candidates.jsonl", rows)
    with pytest.raises(MetaRunError, match="duplicate record ID"):
        _run(paths, tmp_path / "output")


def test_duplicate_p4_finding_is_rejected(tmp_path: Path) -> None:
    paths = write_meta_inputs(tmp_path / "inputs")
    finding = make_p4_finding()
    rewrite_jsonl(paths["P4"] / "findings.jsonl", [finding, dict(finding)])
    with pytest.raises(MetaRunError, match="duplicate"):
        _run(paths, tmp_path / "output")


def test_clean_production_scores_and_ordering_are_unchanged(tmp_path: Path) -> None:
    """Guards the accepted P1--P4 production artifacts against duplicate-input regressions."""
    result = run_meta(
        Path("data/results/p1/v1"),
        Path("data/results/p2/v1"),
        Path("data/results/p3/v1"),
        Path("data/results/p4/v1"),
        tmp_path / "meta",
    )
    scores = {item.project_id: item.review_priority_score for item in result.assessments}
    assert scores == {
        "project_003_bayterek": 26.00,
        "project_004_sintez_ural": 14.72,
        "project_002_azm": 14.35,
        "project_001_bereke": 13.15,
    }
    ordered = sorted(scores, key=lambda project_id: (-scores[project_id], project_id))
    assert ordered == [
        "project_003_bayterek",
        "project_004_sintez_ural",
        "project_002_azm",
        "project_001_bereke",
    ]


def test_production_project_names_are_not_hardcoded_in_scorer() -> None:
    package = Path(__file__).parents[2] / "src" / "dalel" / "meta_review"
    implementation = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(package.glob("*.py"))
        if path.name not in {"validation.py"}
    )
    for project_name in (
        "project_001_bereke",
        "project_002_azm",
        "project_003_bayterek",
        "project_004_sintez_ural",
    ):
        assert project_name not in implementation


def _tamper(output: Path, case: str) -> None:
    if case == "report_count":
        report = output / "report.md"
        report.write_text(report.read_text(encoding="utf-8") + "tampered\n", encoding="utf-8")
        return
    if case == "metrics_ordering":
        path = output / "metrics.json"
        row = json.loads(path.read_text(encoding="utf-8"))
        row["score_ordering"] = ["fake_project"]
        path.write_text(json.dumps(row, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return
    if case in {
        "raw_value",
        "normalized_value",
        "feature_weight",
        "raw_feature_contribution",
        "duplicate_feature_id",
    }:
        path = output / "features.jsonl"
        rows = load_jsonl(path)
        if case == "duplicate_feature_id":
            rows[1]["feature_id"] = rows[0]["feature_id"]
            rewrite_jsonl(path, rows)
            return
        field = {
            "raw_value": "raw_value",
            "normalized_value": "normalized_value",
            "feature_weight": "weight",
            "raw_feature_contribution": "contribution",
        }[case]
        rows[0][field] = float(rows[0][field]) + 1.0
        rewrite_jsonl(path, rows)
        return
    if case in {"pillar_subtotal", "p2_cap", "p2_discount"}:
        path = output / "pillar_contributions.jsonl"
        rows = load_jsonl(path)
        target = next(row for row in rows if row["pillar_id"] == "P2")
        field = {
            "pillar_subtotal": "subtotal",
            "p2_cap": "cap",
            "p2_discount": "discount_amount",
        }[case]
        target[field] = float(target[field]) + (1.0 if field != "discount_amount" else -1.0)
        rewrite_jsonl(path, rows)
        return
    if case == "separate_feature_contribution":
        path = output / "feature_contributions.jsonl"
        rows = load_jsonl(path)
        rows[0]["contribution"] = float(rows[0]["contribution"]) + 1.0
        rewrite_jsonl(path, rows)
        return

    path = output / "project_assessments.jsonl"
    rows = load_jsonl(path)
    assessment = rows[0]
    if case == "coverage":
        assessment["evidence_coverage"] = 0.01
    elif case == "confidence":
        assessment["assessment_confidence"] = 0.01
    elif case == "final_score":
        assessment["review_priority_score"] += 1.0
    elif case == "level":
        assessment["review_priority_level"] = "high"
    elif case == "source_finding_id":
        target = next(
            item for item in assessment["feature_contributions"] if item["source_finding_ids"]
        )
        target["source_finding_ids"] = ["P1__deadbeef0000"]
    elif case == "calibration_status":
        assessment["calibration_status"] = "available"
    elif case == "fake_probability":
        assessment["calibrated_probability"] = 0.9
    elif case == "fake_shap":
        assessment["shap_contributions"] = [{"fake": 1.0}]
    elif case == "local_path":
        assessment["limitations"].append("/Users/example/private.pdf")
    elif case == "timestamp":
        assessment["created_at"] = "2026-01-01T00:00:00Z"
    else:  # pragma: no cover - guarded by parametrization
        raise AssertionError(case)
    rewrite_jsonl(path, rows)


@pytest.mark.parametrize(
    "case",
    [
        "raw_value",
        "normalized_value",
        "feature_weight",
        "raw_feature_contribution",
        "duplicate_feature_id",
        "pillar_subtotal",
        "p2_cap",
        "p2_discount",
        "separate_feature_contribution",
        "coverage",
        "confidence",
        "final_score",
        "level",
        "source_finding_id",
        "calibration_status",
        "fake_probability",
        "fake_shap",
        "metrics_ordering",
        "report_count",
        "local_path",
        "timestamp",
    ],
)
def test_material_tampering_is_rejected(tmp_path: Path, case: str) -> None:
    paths = write_meta_inputs(tmp_path / "inputs")
    output = tmp_path / "output"
    _run(paths, output)
    _tamper(output, case)
    result = _validate(paths, output)
    assert not result.ok, case

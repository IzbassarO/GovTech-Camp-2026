"""Small accepted-shape P1--P4 artifacts for Meta tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PROJECT = "project_meta_fixture"
DOC_A = f"{PROJECT}__ndv__001"
DOC_B = f"{PROJECT}__pek__001"


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _finding(
    pillar: str,
    finding_id: str,
    finding_type: str,
    severity: str,
    document_id: str | None = DOC_A,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "finding_id": finding_id,
        "pillar_id": pillar,
        "project_id": PROJECT,
        "document_id": document_id,
        "finding_type": finding_type,
        "severity": severity,
        "priority_score": {"high": 25, "medium": 12, "low": 5, "info": 2}[severity],
        "confidence": None,
        "rule_id": f"{pillar.lower()}.fixture",
        "title": "Fixture finding",
        "explanation": "Fixture review cue.",
        "evidence": [],
        "page_references": [],
        "limitations": "Expert-review fixture; not a legal conclusion.",
        "review_status": "pending",
    }
    if pillar == "P1":
        base.update({"observed_value": None, "expected_value": None})
    elif pillar == "P2":
        base.update(
            {
                "confidence_factors": [],
                "requirement_id": "DEMO-REQ-001",
                "requirement_source": "Synthetic fixture",
                "requirement_is_authoritative": False,
                "requirement_demo_only": True,
                "assessment_id": "P2A__111111111111",
                "retrieval_score": 1.0,
                "inference_label": "insufficient_evidence",
                "inference_engine": "deterministic",
                "evidence_ids": [],
            }
        )
    elif pillar == "P3":
        base.update(
            {
                "confidence_factors": [],
                "mention_ids": [],
                "candidate_id": None,
                "comparison": None,
                "semantic_rationale": "Fixture arithmetic check.",
                "observed_value": None,
                "expected_value": None,
                "quality_flags": [],
            }
        )
    elif pillar == "P4":
        base.update(
            {
                "confidence_factors": [],
                "entity_ids": [],
                "claim_ids": [],
                "edge_ids": [],
                "conflicting_claims": [],
                "package_check": None,
                "observed_value": None,
                "expected_value": None,
                "quality_flags": [],
            }
        )
    return base


def make_p1_finding(
    finding_id: str = "P1__111111111111",
    finding_type: str = "missing_expected_section",
    severity: str = "medium",
    document_id: str | None = DOC_A,
) -> dict[str, Any]:
    return _finding("P1", finding_id, finding_type, severity, document_id)


def make_p2_finding(
    finding_id: str = "P2__111111111111",
    finding_type: str = "insufficient_regulatory_evidence",
    severity: str = "info",
    document_id: str | None = None,
) -> dict[str, Any]:
    return _finding("P2", finding_id, finding_type, severity, document_id)


def make_p3_finding(
    finding_id: str = "P3__111111111111",
    finding_type: str = "direct_value_conflict",
    severity: str = "high",
    document_id: str | None = DOC_A,
) -> dict[str, Any]:
    return _finding("P3", finding_id, finding_type, severity, document_id)


def make_p4_finding(
    finding_id: str = "P4__111111111111",
    finding_type: str = "conflicting_operator",
    severity: str = "medium",
    document_id: str | None = None,
) -> dict[str, Any]:
    return _finding("P4", finding_id, finding_type, severity, document_id)


def _document_scores(score_name: str, score: int) -> list[dict[str, Any]]:
    return [
        {
            "project_id": PROJECT,
            "document_id": document_id,
            "document_type": document_type,
            score_name: score,
            "finding_count": 0,
            "contributions": [],
            "scoring_config_version": "1.0.0",
        }
        for document_id, document_type in ((DOC_A, "ndv"), (DOC_B, "pek"))
    ]


def _project_score(score_name: str, score: int) -> dict[str, Any]:
    return {
        "project_id": PROJECT,
        score_name: score,
        "document_scores": {DOC_A: score, DOC_B: score},
        "package_finding_count": 0,
        "package_contributions": [],
        "scoring_config_version": "1.0.0",
    }


def _write_common(
    directory: Path,
    project_score: dict[str, Any],
    document_scores: list[dict[str, Any]],
    findings: list[dict[str, Any]],
) -> None:
    directory.mkdir(parents=True)
    _write_jsonl(directory / "project_scores.jsonl", [project_score])
    _write_jsonl(directory / "document_scores.jsonl", document_scores)
    _write_jsonl(directory / "findings.jsonl", findings)
    (directory / "metrics.json").write_text("{}\n", encoding="utf-8")
    (directory / "config_snapshot.json").write_text("{}\n", encoding="utf-8")


def write_meta_inputs(root: Path, missing: set[str] | None = None) -> dict[str, Path]:
    missing = missing or set()
    paths = {pillar: root / pillar.lower() for pillar in ("P1", "P2", "P3", "P4")}
    if "P1" not in missing:
        _write_common(
            paths["P1"],
            _project_score("document_integrity_priority_score", 12),
            _document_scores("document_integrity_priority_score", 12),
            [make_p1_finding()],
        )
    if "P2" not in missing:
        _write_common(
            paths["P2"],
            _project_score("regulatory_compliance_priority_score", 2),
            _document_scores("regulatory_compliance_priority_score", 0),
            [make_p2_finding()],
        )
        assessments = [
            {
                "assessment_id": "P2A__111111111111",
                "project_id": PROJECT,
                "label": "insufficient_evidence",
                "confidence": 0.4,
                "requirement_is_authoritative": False,
                "retrieval_id": "P2R__111111111111",
                "evidence_ids": [],
            },
            {
                "assessment_id": "P2A__222222222222",
                "project_id": PROJECT,
                "label": "supported_by_evidence",
                "confidence": 0.9,
                "requirement_is_authoritative": False,
                "retrieval_id": "P2R__222222222222",
                "evidence_ids": ["P2E__222222222222"],
            },
        ]
        _write_jsonl(paths["P2"] / "assessments.jsonl", assessments)
        _write_jsonl(
            paths["P2"] / "retrievals.jsonl",
            [{"project_id": PROJECT, "retrieval_id": row["retrieval_id"]} for row in assessments],
        )
        _write_jsonl(
            paths["P2"] / "project_evidence.jsonl",
            [{"project_id": PROJECT, "evidence_id": "P2E__222222222222"}],
        )
        _write_jsonl(
            paths["P2"] / "requirements_snapshot.jsonl",
            [{"requirement_id": "DEMO-REQ-001", "is_authoritative": False}],
        )
    if "P3" not in missing:
        _write_common(
            paths["P3"],
            _project_score("quantitative_consistency_priority_score", 0),
            _document_scores("quantitative_consistency_priority_score", 0),
            [],
        )
        _write_jsonl(
            paths["P3"] / "mentions.jsonl",
            [{"project_id": PROJECT, "mention_id": "P3Q__111111111111"}],
        )
        _write_jsonl(
            paths["P3"] / "candidates.jsonl",
            [
                {
                    "project_id": PROJECT,
                    "candidate_id": "P3C__111111111111",
                    "status": "compared",
                },
                {
                    "project_id": PROJECT,
                    "candidate_id": "P3C__222222222222",
                    "status": "suppressed",
                },
            ],
        )
        _write_jsonl(
            paths["P3"] / "aggregation_checks.jsonl",
            [
                {
                    "project_id": PROJECT,
                    "check_id": "P3A__111111111111",
                    "decision": "consistent",
                    "finding_id": None,
                }
            ],
        )
        _write_jsonl(paths["P3"] / "suppressed_samples.jsonl", [])
    if "P4" not in missing:
        project = _project_score("cross_document_coherence_priority_score", 0)
        project.update(
            {
                "entity_count": 3,
                "edge_count": 2,
                "linked_document_count": 2,
                "unresolved_entity_count": 0,
                "suppressed_comparison_count": 1,
            }
        )
        _write_common(
            paths["P4"],
            project,
            _document_scores("cross_document_coherence_priority_score", 0),
            [],
        )
        _write_jsonl(
            paths["P4"] / "claims.jsonl",
            [{"project_id": PROJECT, "claim_id": f"P4C__{index:012x}"} for index in range(1, 7)],
        )
        _write_jsonl(
            paths["P4"] / "entities.jsonl",
            [{"project_id": PROJECT, "entity_id": "P4E__111111111111"}],
        )
        _write_jsonl(
            paths["P4"] / "edges.jsonl",
            [{"project_id": PROJECT, "edge_id": "P4G__111111111111"}],
        )
        _write_jsonl(
            paths["P4"] / "resolution_decisions.jsonl",
            [{"project_id": PROJECT, "decision_id": "P4R__111111111111", "decision": "merged"}],
        )
        _write_jsonl(
            paths["P4"] / "suppressed_comparisons.jsonl",
            [{"project_id": PROJECT, "suppression_id": "P4S__111111111111"}],
        )
    annotations = root / "annotations"
    annotations.mkdir()
    for pillar in ("p1", "p2", "p3", "p4"):
        _write_jsonl(
            annotations / f"{pillar}_review_template.jsonl",
            [
                {
                    "finding_id": f"{pillar.upper()}__111111111111",
                    "expert_decision": None,
                    "corrected_severity": None,
                    "expert_comment": None,
                    "reviewed_at": None,
                    "reviewer_id": None,
                }
            ],
        )
    paths["annotations"] = annotations
    return paths


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def rewrite_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    _write_jsonl(path, rows)

"""Deterministic severity, confidence and review-priority scoring for P4.

Severity and confidence are SEPARATE:

- severity reflects how strong the cross-document incompatibility is (a proven
  explicit-identifier conflict is medium; a credible value mismatch is low; a
  diagnostic about missing linkage or context is info);
- confidence reflects extraction and linkage reliability.

High severity is NEVER produced in this MVP. The review-priority score is a
transparent sum of per-finding severity points — explicitly NOT a probability,
calibrated score or final project risk. Every factor is recorded.
"""

from __future__ import annotations

from dalel.pillars.cross_document_coherence.config import (
    CONFIDENCE_MAX,
    CONFIDENCE_MIN,
    CONFIDENCE_PENALTIES,
    FINDING_CONFIDENCE,
    P4_SCORING_CONFIG_VERSION,
    SCORE_CAP,
    SEVERITY_POINTS,
)
from dalel.pillars.cross_document_coherence.schemas import (
    ConfidenceFactor,
    P4DocumentScoreRecord,
    P4FindingRecord,
    P4ProjectScoreRecord,
    P4ScoreContribution,
)

# The MVP never escalates above medium — no proven conflict here is severe
# enough (and never confident enough) to warrant a high-severity claim.
MAX_SEVERITY = "medium"
_SEVERITY_ORDER = ["info", "low", "medium", "high"]


def cap_severity(severity: str, cap: str = MAX_SEVERITY) -> str:
    return _SEVERITY_ORDER[min(_SEVERITY_ORDER.index(severity), _SEVERITY_ORDER.index(cap))]


def finding_confidence(
    finding_type: str,
    flags: list[str],
    extra_factors: list[tuple[str, float]] | None = None,
) -> tuple[float, list[ConfidenceFactor]]:
    """Rubric confidence: base per finding type minus declared penalties for the
    quality flags present, plus explicit extra factors."""
    base = FINDING_CONFIDENCE.get(finding_type, 0.5)
    factors = [ConfidenceFactor(factor=f"base:{finding_type}", delta=base)]
    value = base
    applied: set[str] = set()
    for flag in flags:
        penalty = CONFIDENCE_PENALTIES.get(flag)
        if penalty is not None and flag not in applied:
            applied.add(flag)
            value -= penalty
            factors.append(ConfidenceFactor(factor=flag, delta=-penalty))
    for name, delta in extra_factors or []:
        value += delta
        factors.append(ConfidenceFactor(factor=name, delta=delta))
    value = round(min(CONFIDENCE_MAX, max(CONFIDENCE_MIN, value)), 2)
    return value, factors


def points_for(severity: str) -> int:
    return SEVERITY_POINTS[severity]


def _contributions(findings: list[P4FindingRecord]) -> list[P4ScoreContribution]:
    return [
        P4ScoreContribution(
            finding_id=finding.finding_id,
            finding_type=finding.finding_type,
            severity=finding.severity,
            points=finding.priority_score,
        )
        for finding in findings
    ]


def score_document(
    project_id: str,
    document_id: str,
    document_type: str,
    findings: list[P4FindingRecord],
) -> P4DocumentScoreRecord:
    contributions = _contributions(findings)
    total = min(SCORE_CAP, sum(c.points for c in contributions))
    return P4DocumentScoreRecord(
        project_id=project_id,
        document_id=document_id,
        document_type=document_type,
        cross_document_coherence_priority_score=total,
        finding_count=len(findings),
        contributions=contributions,
        scoring_config_version=P4_SCORING_CONFIG_VERSION,
    )


def score_project(
    project_id: str,
    document_scores: list[P4DocumentScoreRecord],
    package_findings: list[P4FindingRecord],
    *,
    entity_count: int,
    edge_count: int,
    linked_document_count: int,
    unresolved_entity_count: int,
    suppressed_comparison_count: int,
) -> P4ProjectScoreRecord:
    contributions = _contributions(package_findings)
    package_points = sum(c.points for c in contributions)
    mean_documents = (
        sum(s.cross_document_coherence_priority_score for s in document_scores)
        / len(document_scores)
        if document_scores
        else 0.0
    )
    total = min(SCORE_CAP, round(mean_documents) + package_points)
    return P4ProjectScoreRecord(
        project_id=project_id,
        cross_document_coherence_priority_score=total,
        document_scores={
            s.document_id: s.cross_document_coherence_priority_score for s in document_scores
        },
        package_finding_count=len(package_findings),
        package_contributions=contributions,
        entity_count=entity_count,
        edge_count=edge_count,
        linked_document_count=linked_document_count,
        unresolved_entity_count=unresolved_entity_count,
        suppressed_comparison_count=suppressed_comparison_count,
        scoring_config_version=P4_SCORING_CONFIG_VERSION,
    )

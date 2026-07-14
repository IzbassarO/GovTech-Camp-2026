"""Deterministic, monotonic priority scoring.

``document_integrity_priority_score`` (0-100) is a manual-review priority for
document structure — NEVER a probability of violation. Missing data does not
automatically raise the score: only explicit findings contribute, each with a
non-negative, explainable number of points.
"""

from __future__ import annotations

from dalel.pillars.document_integrity.config import (
    SCORE_CAP,
    SCORING_CONFIG_VERSION,
)
from dalel.pillars.document_integrity.schemas import (
    DocumentScoreRecord,
    FindingRecord,
    ProjectScoreRecord,
    ScoreContribution,
)


def _contributions(findings: list[FindingRecord]) -> list[ScoreContribution]:
    return [
        ScoreContribution(
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
    findings: list[FindingRecord],
) -> DocumentScoreRecord:
    contributions = _contributions(findings)
    total = min(SCORE_CAP, sum(c.points for c in contributions))
    return DocumentScoreRecord(
        project_id=project_id,
        document_id=document_id,
        document_type=document_type,
        document_integrity_priority_score=total,
        finding_count=len(findings),
        contributions=contributions,
        scoring_config_version=SCORING_CONFIG_VERSION,
    )


def score_project(
    project_id: str,
    document_scores: list[DocumentScoreRecord],
    package_findings: list[FindingRecord],
) -> ProjectScoreRecord:
    contributions = _contributions(package_findings)
    package_points = sum(c.points for c in contributions)
    mean_documents = (
        sum(s.document_integrity_priority_score for s in document_scores) / len(document_scores)
        if document_scores
        else 0.0
    )
    total = min(SCORE_CAP, round(mean_documents) + package_points)
    return ProjectScoreRecord(
        project_id=project_id,
        document_integrity_priority_score=total,
        document_scores={
            s.document_id: s.document_integrity_priority_score for s in document_scores
        },
        package_finding_count=len(package_findings),
        package_contributions=contributions,
        scoring_config_version=SCORING_CONFIG_VERSION,
    )

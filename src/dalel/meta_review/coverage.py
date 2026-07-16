"""Evidence coverage and score-confidence calculations kept outside priority."""

from __future__ import annotations

from typing import Any

from dalel.meta_review.artifacts import PillarArtifactBundle
from dalel.meta_review.config import COVERAGE_WEIGHTS
from dalel.meta_review.schemas import CoverageAssessment, PillarId, deterministic_id


def _rows(rows: list[dict[str, Any]], project_id: str) -> list[dict[str, Any]]:
    return [row for row in rows if str(row.get("project_id")) == project_id]


def _score_row(bundle: PillarArtifactBundle, project_id: str) -> dict[str, Any]:
    return next(row for row in bundle.project_scores if row["project_id"] == project_id)


def _p1(bundle: PillarArtifactBundle, project_id: str) -> tuple[float, float]:
    score = _score_row(bundle, project_id)
    expected_ids = set(score.get("document_scores", {}))
    actual_ids = {str(row["document_id"]) for row in _rows(bundle.document_scores, project_id)}
    doc_coverage = len(actual_ids & expected_ids) / len(expected_ids) if expected_ids else 0.0
    # Absence findings legitimately have no quote. Scored-document reach is the
    # reproducible P1 coverage signal and avoids penalising correctly grounded absences.
    coverage = doc_coverage
    return coverage, coverage * 0.85


def _p2(bundle: PillarArtifactBundle, project_id: str) -> tuple[float, float]:
    score = _score_row(bundle, project_id)
    expected_ids = set(score.get("document_scores", {}))
    actual_ids = {str(row["document_id"]) for row in _rows(bundle.document_scores, project_id)}
    doc_coverage = len(actual_ids & expected_ids) / len(expected_ids) if expected_ids else 0.0
    assessments = _rows(bundle.records["assessments"], project_id)
    retrieval_ids = {
        str(row["retrieval_id"]) for row in _rows(bundle.records["retrievals"], project_id)
    }
    linked = sum(1 for row in assessments if str(row.get("retrieval_id")) in retrieval_ids)
    assessment_linkage = linked / len(assessments) if assessments else 0.0
    grounded = sum(1 for row in assessments if row.get("evidence_ids"))
    evidence_rate = grounded / len(assessments) if assessments else 0.0
    coverage = 0.4 * doc_coverage + 0.4 * assessment_linkage + 0.2 * evidence_rate
    mean_confidence = (
        sum(float(row.get("confidence", 0.0)) for row in assessments) / len(assessments)
        if assessments
        else 0.0
    )
    authoritative_ratio = (
        sum(1 for row in assessments if row.get("requirement_is_authoritative") is True)
        / len(assessments)
        if assessments
        else 0.0
    )
    source_reliability = 0.4 + 0.6 * authoritative_ratio
    return coverage, coverage * mean_confidence * source_reliability


def _p3(bundle: PillarArtifactBundle, project_id: str) -> tuple[float, float]:
    score = _score_row(bundle, project_id)
    expected_ids = set(score.get("document_scores", {}))
    actual_ids = {str(row["document_id"]) for row in _rows(bundle.document_scores, project_id)}
    doc_coverage = len(actual_ids & expected_ids) / len(expected_ids) if expected_ids else 0.0
    mentions = _rows(bundle.records["mentions"], project_id)
    candidates = _rows(bundle.records["candidates"], project_id)
    aggregations = _rows(bundle.records["aggregation_checks"], project_id)
    compared = sum(1 for row in candidates if row.get("status") == "compared")
    suppressed = sum(1 for row in candidates if row.get("status") == "suppressed")
    candidate_total = compared + suppressed
    compared_rate = compared / candidate_total if candidate_total else 0.0
    mention_presence = 1.0 if mentions else 0.0
    aggregation_reach = min(len(aggregations) / max(1, len(expected_ids)), 1.0)
    coverage = (
        0.4 * doc_coverage
        + 0.15 * mention_presence
        + 0.25 * compared_rate
        + 0.2 * aggregation_reach
    )
    consistent = sum(1 for row in aggregations if row.get("decision") == "consistent")
    aggregation_reliability = consistent / len(aggregations) if aggregations else 0.0
    reliability = 0.45 + 0.4 * compared_rate + 0.15 * aggregation_reliability
    return coverage, coverage * min(reliability, 1.0)


def _p4(bundle: PillarArtifactBundle, project_id: str) -> tuple[float, float]:
    score = _score_row(bundle, project_id)
    expected_ids = set(score.get("document_scores", {}))
    actual_ids = {str(row["document_id"]) for row in _rows(bundle.document_scores, project_id)}
    doc_coverage = len(actual_ids & expected_ids) / len(expected_ids) if expected_ids else 0.0
    linked_rate = min(float(score.get("linked_document_count", 0)) / max(1, len(expected_ids)), 1.0)
    claims = _rows(bundle.records["claims"], project_id)
    graph_evidence = min(len(claims) / max(1.0, 3.0 * len(expected_ids)), 1.0)
    coverage = 0.35 * doc_coverage + 0.45 * linked_rate + 0.2 * graph_evidence
    suppressed = _rows(bundle.records["suppressed_comparisons"], project_id)
    unresolved = int(score.get("unresolved_entity_count", 0))
    suppression_penalty = min(len(suppressed) / max(1, len(expected_ids)) * 0.2, 0.25)
    unresolved_penalty = min(unresolved / max(1, int(score.get("entity_count", 0))) * 2.0, 0.25)
    reliability = max(0.2, 0.85 - suppression_penalty - unresolved_penalty)
    return coverage, coverage * reliability


def assess_coverage(
    project_id: str, bundles: dict[str, PillarArtifactBundle]
) -> CoverageAssessment:
    calculators = {"P1": _p1, "P2": _p2, "P3": _p3, "P4": _p4}
    pillar_coverage: dict[PillarId, float] = {}
    pillar_confidence: dict[PillarId, float] = {}
    missing: list[PillarId] = []
    limitations: list[str] = []
    typed_pillars: tuple[PillarId, ...] = ("P1", "P2", "P3", "P4")
    for pillar in typed_pillars:
        bundle = bundles[pillar]
        if not bundle.available:
            pillar_coverage[pillar] = 0.0
            pillar_confidence[pillar] = 0.0
            missing.append(pillar)
            limitations.append(
                f"{pillar} недоступен: отсутствие артефакта снижает покрытие и уверенность."
            )
            continue
        coverage, confidence = calculators[pillar](bundle, project_id)
        pillar_coverage[pillar] = round(max(0.0, min(1.0, coverage)), 4)
        pillar_confidence[pillar] = round(max(0.0, min(1.0, confidence)), 4)

    evidence_coverage = round(
        sum(pillar_coverage[p] * COVERAGE_WEIGHTS[p] for p in typed_pillars), 4
    )
    assessment_confidence = round(
        sum(pillar_confidence[p] * COVERAGE_WEIGHTS[p] for p in typed_pillars), 4
    )
    if bundles["P2"].available:
        limitations.append(
            "P2 использует синтетический демонстрационный корпус, "
            "поэтому его надёжность ограничена."
        )
    if bundles["P3"].available:
        limitations.append(
            "Нулевое число противоречий P3 не означает полного количественного покрытия."
        )
    if bundles["P4"].available:
        limitations.append(
            "Нулевое число противоречий P4 не означает идеальной междокументной согласованности."
        )
    return CoverageAssessment(
        coverage_id=deterministic_id(
            "META_C", project_id, str(pillar_coverage), str(pillar_confidence)
        ),
        project_id=project_id,
        evidence_coverage=evidence_coverage,
        assessment_confidence=assessment_confidence,
        pillar_coverage=pillar_coverage,
        pillar_confidence=pillar_confidence,
        missing_pillars=missing,
        limitations=limitations,
    )

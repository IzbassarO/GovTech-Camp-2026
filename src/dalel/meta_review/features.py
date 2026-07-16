"""Traceable feature extraction from accepted pillar artifacts."""

from __future__ import annotations

from typing import Any

from dalel.meta_review.artifacts import PillarArtifactBundle
from dalel.meta_review.config import (
    FEATURE_WEIGHTS,
    NORMALIZED_PRECISION,
    P1_OCR_OR_EMPTY_TYPES,
    P1_STRUCTURAL_TYPES,
    P3_PROVEN_CONFLICT_TYPES,
    P3_UNRESOLVED_TYPES,
    P4_DIAGNOSTIC_TYPES,
    P4_PROVEN_CONFLICT_TYPES,
    SCORE_PRECISION,
)
from dalel.meta_review.schemas import MetaFeatureRecord, PillarId, deterministic_id


def _project_rows(rows: list[dict[str, Any]], project_id: str) -> list[dict[str, Any]]:
    return [row for row in rows if str(row.get("project_id")) == project_id]


def _source_id(pillar: str, artifact: str, record_id: str) -> str:
    return f"{pillar}:{artifact}:{record_id}"


def _feature(
    project_id: str,
    pillar: PillarId,
    name: str,
    raw_value: int | float,
    normalized_value: float,
    source_artifact_ids: list[str],
    source_finding_ids: list[str],
    explanation: str,
    limitations: list[str] | None = None,
) -> MetaFeatureRecord:
    normalized = round(max(0.0, min(1.0, normalized_value)), NORMALIZED_PRECISION)
    weight = FEATURE_WEIGHTS[pillar][name]
    contribution = round(normalized * weight, SCORE_PRECISION)
    artifact_ids = sorted(set(source_artifact_ids))
    finding_ids = sorted(set(source_finding_ids))
    feature_id = deterministic_id(
        "META_F",
        project_id,
        pillar,
        name,
        str(raw_value),
        str(normalized),
        str(weight),
        ",".join(artifact_ids),
        ",".join(finding_ids),
    )
    return MetaFeatureRecord(
        feature_id=feature_id,
        project_id=project_id,
        feature_name=name,
        pillar_source=pillar,
        raw_value=raw_value,
        normalized_value=normalized,
        weight=weight,
        contribution=contribution,
        source_artifact_ids=artifact_ids,
        source_finding_ids=finding_ids,
        explanation=explanation,
        limitations=limitations or [],
    )


def _p1_features(project_id: str, bundle: PillarArtifactBundle) -> list[MetaFeatureRecord]:
    score = next(row for row in bundle.project_scores if row["project_id"] == project_id)
    findings = _project_rows(bundle.findings, project_id)
    document_count = max(1, len(score.get("document_scores", {})))
    by_severity = {
        severity: [finding for finding in findings if finding.get("severity") == severity]
        for severity in ("high", "medium", "low", "info")
    }
    low_distinct = [
        finding
        for finding in by_severity["low"]
        if finding.get("finding_type") not in P1_OCR_OR_EMPTY_TYPES
    ]
    structural = [
        finding
        for finding in findings
        if finding.get("severity") == "info" and finding.get("finding_type") in P1_STRUCTURAL_TYPES
    ]
    ocr_or_empty = [
        finding for finding in findings if finding.get("finding_type") in P1_OCR_OR_EMPTY_TYPES
    ]

    def finding_ids(rows: list[dict[str, Any]]) -> list[str]:
        return [str(row["finding_id"]) for row in rows]

    score_id = _source_id("P1", "project_scores", project_id)
    return [
        _feature(
            project_id,
            "P1",
            "p1_project_priority_signal",
            int(score["document_integrity_priority_score"]),
            float(score["document_integrity_priority_score"]) / 100.0,
            [score_id],
            finding_ids(findings),
            "Принятый проектный балл P1 отражает структурные сигналы документов.",
            [
                "Это приоритет ручной проверки структуры, а не вывод о соответствии.",
                "Вес равен нулю, чтобы не учитывать повторно те же находки P1.",
            ],
        ),
        _feature(
            project_id,
            "P1",
            "p1_high_severity_findings",
            len(by_severity["high"]),
            len(by_severity["high"]) / 2.0,
            [_source_id("P1", "findings", project_id)],
            finding_ids(by_severity["high"]),
            "Количество структурных сигналов высокой важности.",
        ),
        _feature(
            project_id,
            "P1",
            "p1_medium_severity_rate",
            len(by_severity["medium"]),
            len(by_severity["medium"]) / (2.0 * document_count),
            [_source_id("P1", "findings", project_id)],
            finding_ids(by_severity["medium"]),
            "Плотность структурных сигналов средней важности на документ.",
        ),
        _feature(
            project_id,
            "P1",
            "p1_low_severity_rate",
            len(low_distinct),
            len(low_distinct) / (3.0 * document_count),
            [_source_id("P1", "findings", project_id)],
            finding_ids(low_distinct),
            "Плотность прочих структурных сигналов низкой важности на документ.",
        ),
        _feature(
            project_id,
            "P1",
            "p1_structural_anomaly_rate",
            len(structural),
            len(structural) / (8.0 * document_count),
            [_source_id("P1", "findings", project_id)],
            finding_ids(structural),
            "Ограниченная плотность повторов заголовков и иных структурных аномалий.",
            ["Вес ограничивает влияние многочисленных информационных повторов."],
        ),
        _feature(
            project_id,
            "P1",
            "p1_ocr_or_empty_page_rate",
            len(ocr_or_empty),
            len(ocr_or_empty) / (2.0 * document_count),
            [_source_id("P1", "findings", project_id)],
            finding_ids(ocr_or_empty),
            "Доля сигналов зависимости от OCR или пустых страниц.",
        ),
    ]


def _p2_features(project_id: str, bundle: PillarArtifactBundle) -> list[MetaFeatureRecord]:
    findings = _project_rows(bundle.findings, project_id)
    assessments = _project_rows(bundle.records["assessments"], project_id)
    potential = [row for row in assessments if row.get("label") == "potential_conflict"]
    insufficient = [row for row in assessments if row.get("label") == "insufficient_evidence"]
    missing = [row for row in findings if row.get("finding_type") == "missing_required_document"]
    notices = [
        row for row in findings if row.get("finding_type") == "non_authoritative_demo_requirement"
    ]
    authoritative = [row for row in assessments if row.get("requirement_is_authoritative") is True]
    mean_confidence = (
        sum(float(row.get("confidence", 0.0)) for row in assessments) / len(assessments)
        if assessments
        else 0.0
    )
    authoritative_ratio = len(authoritative) / len(assessments) if assessments else 0.0

    def assessment_ids(rows: list[dict[str, Any]]) -> list[str]:
        return [_source_id("P2", "assessments", str(row["assessment_id"])) for row in rows]

    return [
        _feature(
            project_id,
            "P2",
            "p2_potential_conflicts",
            len(potential),
            len(potential) / 4.0,
            assessment_ids(potential),
            [],
            "Оценки P2 с меткой потенциального конфликта, требующие экспертной проверки.",
            ["Нормативный корпус P2 в текущей версии синтетический и неавторитетный."],
        ),
        _feature(
            project_id,
            "P2",
            "p2_missing_document_cues",
            len(missing),
            len(missing) / 4.0,
            [_source_id("P2", "findings", project_id)],
            [str(row["finding_id"]) for row in missing],
            "Сигналы об отсутствующих типах документов по демонстрационным требованиям.",
            [
                "Сигнал основан на демонстрационном корпусе и не является правовым выводом.",
                "Вес равен нулю: сигнал уже учтён соответствующей оценкой potential_conflict.",
            ],
        ),
        _feature(
            project_id,
            "P2",
            "p2_insufficient_evidence",
            len(insufficient),
            len(insufficient) / 4.0,
            assessment_ids(insufficient),
            [
                str(row["finding_id"])
                for row in findings
                if row.get("finding_type") == "insufficient_regulatory_evidence"
            ],
            "Оценки, для которых P2 не нашёл достаточного подтверждающего контекста.",
        ),
        _feature(
            project_id,
            "P2",
            "p2_retrieval_confidence",
            round(mean_confidence, NORMALIZED_PRECISION),
            mean_confidence,
            [_source_id("P2", "assessments", project_id)],
            [],
            "Средняя детерминированная уверенность оценок P2; влияет на уверенность, не балл.",
        ),
        _feature(
            project_id,
            "P2",
            "p2_authoritative_coverage",
            round(authoritative_ratio, NORMALIZED_PRECISION),
            authoritative_ratio,
            [_source_id("P2", "assessments", project_id)],
            [],
            "Доля оценок, опирающихся на авторитетные требования.",
            ["В принятом P2 эта доля равна нулю: корпус синтетический."],
        ),
        _feature(
            project_id,
            "P2",
            "p2_synthetic_info_notices",
            len(notices),
            len(notices),
            [_source_id("P2", "findings", project_id)],
            [str(row["finding_id"]) for row in notices],
            "Информационные уведомления о демонстрационном корпусе не повышают балл.",
            ["Вес функции намеренно равен нулю."],
        ),
    ]


def _p3_features(project_id: str, bundle: PillarArtifactBundle) -> list[MetaFeatureRecord]:
    findings = _project_rows(bundle.findings, project_id)
    mentions = _project_rows(bundle.records["mentions"], project_id)
    candidates = _project_rows(bundle.records["candidates"], project_id)
    aggregations = _project_rows(bundle.records["aggregation_checks"], project_id)
    proven = [row for row in findings if row.get("finding_type") in P3_PROVEN_CONFLICT_TYPES]
    unresolved = [row for row in findings if row.get("finding_type") in P3_UNRESOLVED_TYPES]
    mismatches = [row for row in aggregations if row.get("decision") == "mismatch"]
    compared = [row for row in candidates if row.get("status") == "compared"]
    suppressed = [row for row in candidates if row.get("status") == "suppressed"]
    candidate_total = len(compared) + len(suppressed)
    compared_rate = len(compared) / candidate_total if candidate_total else 0.0
    suppressed_rate = len(suppressed) / candidate_total if candidate_total else 0.0
    high = [row for row in findings if row.get("severity") == "high"]
    medium = [row for row in findings if row.get("severity") == "medium"]

    def ids(rows: list[dict[str, Any]]) -> list[str]:
        return [str(row["finding_id"]) for row in rows]

    return [
        _feature(
            project_id,
            "P3",
            "p3_proven_conflicts",
            len(proven),
            len(proven) / 3.0,
            [_source_id("P3", "findings", project_id)],
            ids(proven),
            "Доказанные арифметические или количественные противоречия P3.",
        ),
        _feature(
            project_id,
            "P3",
            "p3_high_severity_findings",
            len(high),
            len(high) / 2.0,
            [_source_id("P3", "findings", project_id)],
            ids(high),
            "Количественные сигналы высокой важности.",
            ["Вес равен нулю, чтобы не учитывать повторно доказанный конфликт."],
        ),
        _feature(
            project_id,
            "P3",
            "p3_medium_severity_findings",
            len(medium),
            len(medium) / 3.0,
            [_source_id("P3", "findings", project_id)],
            ids(medium),
            "Количественные сигналы средней важности.",
            ["Вес равен нулю, чтобы не учитывать повторно доказанный конфликт."],
        ),
        _feature(
            project_id,
            "P3",
            "p3_aggregation_mismatches",
            len(mismatches),
            len(mismatches) / 3.0,
            [_source_id("P3", "aggregation_checks", str(row["check_id"])) for row in mismatches],
            [str(row["finding_id"]) for row in mismatches if row.get("finding_id")],
            "Проверенные несовпадения агрегированных итогов.",
            ["Вес равен нулю: несовпадение уже входит в p3_proven_conflicts."],
        ),
        _feature(
            project_id,
            "P3",
            "p3_unresolved_context_findings",
            len(unresolved),
            len(unresolved) / 2.0,
            [_source_id("P3", "findings", project_id)],
            ids(unresolved),
            "Сигналы недостаточного числового контекста.",
        ),
        _feature(
            project_id,
            "P3",
            "p3_compared_candidate_rate",
            round(compared_rate, NORMALIZED_PRECISION),
            compared_rate,
            [_source_id("P3", "candidates", project_id)],
            [],
            "Доля кандидатов, которые можно было сопоставить; влияет на покрытие.",
        ),
        _feature(
            project_id,
            "P3",
            "p3_suppressed_candidate_rate",
            round(suppressed_rate, NORMALIZED_PRECISION),
            suppressed_rate,
            [_source_id("P3", "candidates", project_id)],
            [],
            (
                "Доля подавленных сопоставлений; снижает уверенность, "
                "но не создаёт вывод о безопасности."
            ),
        ),
        _feature(
            project_id,
            "P3",
            "p3_quantitative_mentions",
            len(mentions),
            min(len(mentions) / 100.0, 1.0),
            [_source_id("P3", "mentions", project_id)],
            [],
            (
                "Объём извлечённых количественных упоминаний подтверждает "
                "наличие анализируемого материала."
            ),
        ),
    ]


def _p4_features(project_id: str, bundle: PillarArtifactBundle) -> list[MetaFeatureRecord]:
    score = next(row for row in bundle.project_scores if row["project_id"] == project_id)
    findings = _project_rows(bundle.findings, project_id)
    claims = _project_rows(bundle.records["claims"], project_id)
    suppressed = _project_rows(bundle.records["suppressed_comparisons"], project_id)
    document_count = max(1, len(score.get("document_scores", {})))
    proven = [row for row in findings if row.get("finding_type") in P4_PROVEN_CONFLICT_TYPES]
    unresolved = [
        row for row in findings if row.get("finding_type") == "unresolved_entity_identity"
    ]
    other_diagnostics = [
        row
        for row in findings
        if row.get("finding_type") in P4_DIAGNOSTIC_TYPES
        and row.get("finding_type") != "unresolved_entity_identity"
    ]
    medium = [row for row in findings if row.get("severity") == "medium"]
    linked_rate = float(score.get("linked_document_count", 0)) / document_count
    suppressed_rate = len(suppressed) / document_count
    graph_rate = len(claims) / (3.0 * document_count)

    def ids(rows: list[dict[str, Any]]) -> list[str]:
        return [str(row["finding_id"]) for row in rows]

    return [
        _feature(
            project_id,
            "P4",
            "p4_proven_conflicts",
            len(proven),
            len(proven) / 3.0,
            [_source_id("P4", "findings", project_id)],
            ids(proven),
            "Доказанные несовместимости утверждений между документами.",
        ),
        _feature(
            project_id,
            "P4",
            "p4_unresolved_identity_findings",
            len(unresolved),
            len(unresolved) / 2.0,
            [_source_id("P4", "findings", project_id)],
            ids(unresolved),
            "Неразрешённые сигналы идентичности сущностей.",
        ),
        _feature(
            project_id,
            "P4",
            "p4_other_diagnostic_findings",
            len(other_diagnostics),
            len(other_diagnostics) / 2.0,
            [_source_id("P4", "findings", project_id)],
            ids(other_diagnostics),
            "Прочие диагностические сигналы связности пакета.",
            ["Один информационный сигнал даёт не более одного балла до общих ограничений."],
        ),
        _feature(
            project_id,
            "P4",
            "p4_medium_severity_findings",
            len(medium),
            len(medium) / 3.0,
            [_source_id("P4", "findings", project_id)],
            ids(medium),
            "Междокументные сигналы средней важности.",
            ["Вес равен нулю, чтобы не учитывать повторно доказанный конфликт."],
        ),
        _feature(
            project_id,
            "P4",
            "p4_linked_document_rate",
            int(score.get("linked_document_count", 0)),
            linked_rate,
            [_source_id("P4", "project_scores", project_id)],
            [],
            "Доля документов, подтверждённо связанных графом; влияет на покрытие.",
        ),
        _feature(
            project_id,
            "P4",
            "p4_suppressed_comparison_rate",
            len(suppressed),
            suppressed_rate,
            [_source_id("P4", "suppressed_comparisons", project_id)],
            [],
            "Подавленные междокументные сопоставления снижают уверенность.",
        ),
        _feature(
            project_id,
            "P4",
            "p4_graph_evidence_rate",
            len(claims),
            graph_rate,
            [_source_id("P4", "claims", project_id)],
            [],
            "Плотность утверждений, поддерживающих граф сущностей; влияет на покрытие.",
        ),
    ]


def extract_project_features(
    project_id: str, bundles: dict[str, PillarArtifactBundle]
) -> list[MetaFeatureRecord]:
    """Extract features in fixed pillar/config order; unavailable pillars emit none."""
    extractors = {"P1": _p1_features, "P2": _p2_features, "P3": _p3_features, "P4": _p4_features}
    features: list[MetaFeatureRecord] = []
    for pillar in ("P1", "P2", "P3", "P4"):
        bundle = bundles[pillar]
        if bundle.available:
            features.extend(extractors[pillar](project_id, bundle))
    return features

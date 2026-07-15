"""Findings construction, severity policy and P2 priority scores.

Severity and confidence stay separate. Safety rules:

- HIGH requires an AUTHORITATIVE requirement, confirmed applicability,
  strong inference confidence and no quality flags;
- a demo-only requirement is hard-capped at LOW (never high, and medium is
  structurally impossible because the cap applies after the base map);
- ``supported_by_evidence`` and ``not_applicable`` assessments produce no
  findings;
- the priority score is a transparent review-priority sum, NOT a
  calibrated probability.
"""

from __future__ import annotations

from dalel.pillars.regulatory_compliance.config import (
    BASE_SEVERITY,
    DEMO_SEVERITY_CAP,
    HIGH_MIN_CONFIDENCE,
    P2_SCORING_CONFIG_VERSION,
    SCORE_CAP,
    SEVERITY_POINTS,
)
from dalel.pillars.regulatory_compliance.schemas import (
    P2Assessment,
    P2DocumentScoreRecord,
    P2Evidence,
    P2FindingRecord,
    P2ProjectScoreRecord,
    P2ScoreContribution,
    RegulatoryRequirement,
    deterministic_id,
)

_SEVERITY_ORDER = ["info", "low", "medium", "high"]


def cap_severity(severity: str, cap: str) -> str:
    return _SEVERITY_ORDER[min(_SEVERITY_ORDER.index(severity), _SEVERITY_ORDER.index(cap))]


_HIGH_PROMOTABLE_TYPES = frozenset(
    {
        "missing_required_document",
        "missing_required_section",
        "potential_regulatory_conflict",
    }
)


def severity_for(
    finding_type: str,
    requirement: RegulatoryRequirement | None,
    assessment: P2Assessment | None,
) -> str:
    severity = BASE_SEVERITY.get(finding_type, "info")
    if requirement is not None and requirement.demo_only:
        return cap_severity(severity, DEMO_SEVERITY_CAP)  # demo is never promoted
    if severity == "medium" and finding_type in _HIGH_PROMOTABLE_TYPES:
        # HIGH only with everything positively established: authoritative
        # requirement, confirmed applicability, strong inference and zero
        # quality flags (any ambiguity blocks promotion).
        eligible = (
            requirement is not None
            and requirement.is_authoritative
            and assessment is not None
            and assessment.applicability == "applicable"
            and assessment.confidence >= HIGH_MIN_CONFIDENCE
            and not assessment.quality_flags
        )
        if eligible:
            severity = "high"
    if severity == "medium" and assessment is not None and assessment.applicability != "applicable":
        severity = "low"  # unconfirmed applicability is never medium
    return severity


def _requirement_source(requirement: RegulatoryRequirement) -> str:
    bits = [requirement.document_title]
    if requirement.article:
        bits.append(f"ст./п. {requirement.article}")
    return ", ".join(bits)


_TYPE_RULES = {
    "missing_required_document": "P2-REQDOC",
    "missing_required_section": "P2-SECTION",
    "potential_regulatory_conflict": "P2-CONFLICT",
    "insufficient_regulatory_evidence": "P2-INSUF",
    "applicability_uncertain": "P2-APPL",
    "non_authoritative_demo_requirement": "P2-DEMO",
}

_INFO_CUE_OBLIGATIONS = frozenset(
    {
        "mandatory_section",
        "monitoring_requirement",
        "disclosure_requirement",
        "procedural_requirement",
        "quantitative_limit",
    }
)


def _finding_type_for(assessment: P2Assessment, requirement: RegulatoryRequirement) -> str | None:
    if assessment.label == "potential_conflict":
        if requirement.obligation_type == "required_document":
            return "missing_required_document"
        if (
            requirement.obligation_type == "mandatory_section"
            and "no_lexical_evidence" in assessment.quality_flags
        ):
            return "missing_required_section"
        return "potential_regulatory_conflict"
    if assessment.label == "insufficient_evidence":
        if "applicability_not_evaluable" in assessment.quality_flags:
            return "applicability_uncertain"
        if (
            assessment.applicability == "applicable"
            and requirement.obligation_type in _INFO_CUE_OBLIGATIONS
        ):
            return "insufficient_regulatory_evidence"
    return None  # supported / not_applicable / unimportant insufficiencies


def _finding_document_id(
    assessment: P2Assessment, requirement: RegulatoryRequirement
) -> str | None:
    if requirement.obligation_type == "required_document":
        return None  # package-level: the document is absent
    for snippet in assessment.evidence_snippets:
        if snippet.document_id is not None:
            return snippet.document_id
    return None


def _finding_title(finding_type: str, requirement: RegulatoryRequirement) -> str:
    titles = {
        "missing_required_document": f"Не найден требуемый документ: {requirement.title}",
        "missing_required_section": f"Не найден требуемый раздел: {requirement.title}",
        "potential_regulatory_conflict": f"Потенциальное противоречие: {requirement.title}",
        "insufficient_regulatory_evidence": (
            f"Недостаточно свидетельств выполнения: {requirement.title}"
        ),
        "applicability_uncertain": f"Применимость не установлена: {requirement.title}",
    }
    return titles[finding_type]


def build_findings(
    assessments: list[P2Assessment],
    requirements_by_id: dict[str, RegulatoryRequirement],
    demo_corpus: bool,
    projects_with_assessments: list[str],
) -> list[P2FindingRecord]:
    findings: list[P2FindingRecord] = []
    for assessment in assessments:
        requirement = requirements_by_id[assessment.requirement_id]
        finding_type = _finding_type_for(assessment, requirement)
        if finding_type is None:
            continue
        severity = severity_for(finding_type, requirement, assessment)
        evidence = list(assessment.evidence_snippets) or [
            P2Evidence(
                note=(
                    "Свидетельства отсутствуют — в этом и состоит наблюдение;"
                    " проверяется по куративному набору данных."
                )
            )
        ]
        pages = sorted(
            {e.page_number for e in assessment.evidence_snippets if e.page_number is not None}
        )
        findings.append(
            P2FindingRecord(
                finding_id=deterministic_id(
                    "P2",
                    assessment.assessment_id,
                    finding_type,
                ),
                project_id=assessment.project_id,
                document_id=_finding_document_id(assessment, requirement),
                finding_type=finding_type,
                severity=severity,
                priority_score=SEVERITY_POINTS[severity],
                confidence=assessment.confidence,
                confidence_factors=assessment.confidence_factors,
                rule_id=_TYPE_RULES[finding_type],
                title=_finding_title(finding_type, requirement),
                explanation=assessment.rationale,
                requirement_id=requirement.requirement_id,
                requirement_source=_requirement_source(requirement),
                requirement_is_authoritative=requirement.is_authoritative,
                requirement_demo_only=requirement.demo_only,
                assessment_id=assessment.assessment_id,
                retrieval_score=assessment.retrieval_score,
                inference_label=assessment.label,
                inference_engine=assessment.inference_engine,
                evidence=evidence,
                evidence_ids=assessment.evidence_ids,
                page_references=pages,
                limitations=assessment.limitations,
            )
        )
    if demo_corpus:
        for project_id in sorted(projects_with_assessments):
            findings.append(
                P2FindingRecord(
                    finding_id=deterministic_id("P2", project_id, "demo_corpus_notice"),
                    project_id=project_id,
                    document_id=None,
                    finding_type="non_authoritative_demo_requirement",
                    severity="info",
                    priority_score=SEVERITY_POINTS["info"],
                    confidence=None,
                    rule_id=_TYPE_RULES["non_authoritative_demo_requirement"],
                    title="Оценки выполнены по синтетическому демо-корпусу",
                    explanation=(
                        "Все регуляторные оценки этого запуска основаны на"
                        " синтетическом демонстрационном корпусе требований."
                        " Illustrative demo regulatory corpus. Not an"
                        " authoritative legal source."
                    ),
                    evidence=[P2Evidence(note="corpus: dalel-demo-regulatory-corpus")],
                    limitations=(
                        "Демонстрационный корпус не является правовой базой;"
                        " выводы о соответствии законодательству невозможны."
                    ),
                )
            )
    return sort_findings(findings)


_SEVERITY_SORT = {"high": 0, "medium": 1, "low": 2, "info": 3}


def sort_findings(findings: list[P2FindingRecord]) -> list[P2FindingRecord]:
    return sorted(
        findings,
        key=lambda f: (
            f.project_id,
            f.document_id or "~",
            _SEVERITY_SORT.get(f.severity, 9),
            f.finding_type,
            f.finding_id,
        ),
    )


def _contributions(findings: list[P2FindingRecord]) -> list[P2ScoreContribution]:
    return [
        P2ScoreContribution(
            finding_id=f.finding_id,
            finding_type=f.finding_type,
            severity=f.severity,
            points=f.priority_score,
        )
        for f in findings
    ]


def score_document(
    project_id: str,
    document_id: str,
    document_type: str,
    findings: list[P2FindingRecord],
) -> P2DocumentScoreRecord:
    contributions = _contributions(findings)
    total = min(SCORE_CAP, sum(c.points for c in contributions))
    return P2DocumentScoreRecord(
        project_id=project_id,
        document_id=document_id,
        document_type=document_type,
        regulatory_compliance_priority_score=total,
        finding_count=len(findings),
        contributions=contributions,
        scoring_config_version=P2_SCORING_CONFIG_VERSION,
    )


def score_project(
    project_id: str,
    document_scores: list[P2DocumentScoreRecord],
    package_findings: list[P2FindingRecord],
) -> P2ProjectScoreRecord:
    contributions = _contributions(package_findings)
    package_points = sum(c.points for c in contributions)
    mean_documents = (
        sum(s.regulatory_compliance_priority_score for s in document_scores) / len(document_scores)
        if document_scores
        else 0.0
    )
    total = min(SCORE_CAP, round(mean_documents) + package_points)
    return P2ProjectScoreRecord(
        project_id=project_id,
        regulatory_compliance_priority_score=total,
        document_scores={
            s.document_id: s.regulatory_compliance_priority_score for s in document_scores
        },
        package_finding_count=len(package_findings),
        package_contributions=contributions,
        scoring_config_version=P2_SCORING_CONFIG_VERSION,
    )

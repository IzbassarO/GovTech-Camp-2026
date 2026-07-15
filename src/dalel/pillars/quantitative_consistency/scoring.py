"""Deterministic severity, confidence and priority scoring for P3.

Severity and confidence are SEPARATE:

- severity reflects the material size of the discrepancy (relative gap,
  materiality floor per dimension) — it answers "how bad if true";
- confidence reflects extraction and context reliability — it answers
  "how sure the comparison is about the same thing".

Low confidence CAPS severity (a huge relative gap on shaky context must not
scream), and both are recorded with their contributing factors.
"""

from __future__ import annotations

from decimal import Decimal

from dalel.pillars.quantitative_consistency.config import (
    CONFIDENCE_BASE,
    CONFIDENCE_MAX,
    CONFIDENCE_MIN,
    CONFIDENCE_PENALTIES,
    MATERIALITY_FLOOR,
    P3_SCORING_CONFIG_VERSION,
    SCORE_CAP,
    SEVERITY_CONFIDENCE_GATE,
    SEVERITY_POINTS,
    SEVERITY_REL_HIGH,
    SEVERITY_REL_MEDIUM,
)
from dalel.pillars.quantitative_consistency.schemas import (
    ConfidenceFactor,
    P3DocumentScoreRecord,
    P3FindingRecord,
    P3ProjectScoreRecord,
    P3ScoreContribution,
    QuantMention,
)

# mention flag -> finding-level penalty key
_FLAG_PENALTIES: dict[str, str] = {
    "ocr_source": "ocr_source",
    "ambiguous_decimal_grouping": "ambiguous_number",
    "approximate": "approximate_value",
    "column_header_unit": "header_unit_inherited",
    "multi_number_cell": "multi_number_cell",
    "possible_table_echo": "possible_table_echo",
    "context_from_section_title": "context_from_section_title",
}


def finding_confidence(
    finding_type: str,
    mentions: list[QuantMention],
    extra_factors: list[tuple[str, float]] | None = None,
) -> tuple[float, list[ConfidenceFactor]]:
    """Rubric confidence: base per finding type minus declared penalties.

    Each penalty applies at most once (if ANY participating mention carries
    the flag); extra factors come from candidate-level context evaluation.
    """
    base = CONFIDENCE_BASE.get(finding_type, 0.5)
    factors = [ConfidenceFactor(factor=f"base:{finding_type}", delta=base)]
    value = base
    applied: set[str] = set()
    for mention in mentions:
        for flag in mention.flags:
            penalty_key = _FLAG_PENALTIES.get(flag)
            if penalty_key and penalty_key not in applied:
                applied.add(penalty_key)
                penalty = CONFIDENCE_PENALTIES[penalty_key]
                value -= penalty
                factors.append(ConfidenceFactor(factor=penalty_key, delta=-penalty))
    for name, delta in extra_factors or []:
        if delta < 0:  # positive candidate factors are informational only
            value += delta
            factors.append(ConfidenceFactor(factor=name, delta=delta))
    value = round(min(CONFIDENCE_MAX, max(CONFIDENCE_MIN, value)), 2)
    return value, factors


def severity_for_conflict(
    rel_diff: Decimal | None,
    max_abs_value: Decimal,
    dimension_kind: str,
    confidence: float,
) -> str:
    """Severity of a value conflict from relative gap + materiality +
    confidence gate."""
    if rel_diff is None:
        severity = "medium"  # one side is zero: material by construction
    elif rel_diff >= SEVERITY_REL_HIGH:
        severity = "high"
    elif rel_diff >= SEVERITY_REL_MEDIUM:
        severity = "medium"
    else:
        severity = "low"
    floor = MATERIALITY_FLOOR.get(dimension_kind)
    if floor is not None and max_abs_value < floor and severity in ("high", "medium"):
        severity = "low"
    if confidence < SEVERITY_CONFIDENCE_GATE and severity in ("high", "medium"):
        severity = "low"
    return severity


def cap_severity(severity: str, cap: str) -> str:
    order = ["info", "low", "medium", "high"]
    return order[min(order.index(severity), order.index(cap))]


# Flags that mean extraction or interpretation ambiguity materially affects
# the value — such findings can never be high severity.
HIGH_BLOCKING_FLAGS = frozenset(
    {
        "ocr_source",
        "ambiguous_decimal_grouping",
        "thousands_from_document_style",
        "multi_number_cell",
        "possible_table_echo",
        "leading_separator",
        "range_inversion",
    }
)
HIGH_MIN_EXTRACTION_CONFIDENCE = 0.8


def high_severity_eligible(dimension_states: dict[str, str], mentions: list[QuantMention]) -> bool:
    """High severity requires POSITIVELY ESTABLISHED sameness: every
    tri-state semantic dimension must be an explicit MATCH (two unknown
    periods or two empty qualifier sets are UNKNOWN, never a match), the
    extraction must be reliable on both sides, units fully resolved, and no
    material ambiguity flags present."""
    if not dimension_states:
        return False
    if any(state != "match" for state in dimension_states.values()):
        return False
    for mention in mentions:
        if mention.extraction_confidence < HIGH_MIN_EXTRACTION_CONFIDENCE:
            return False
        if HIGH_BLOCKING_FLAGS & set(mention.flags):
            return False
        if mention.modifier == "approximate":
            return False
        if mention.unit_canonical is None or mention.dimension is None:
            return False
    return True


def points_for(severity: str) -> int:
    return SEVERITY_POINTS[severity]


def _contributions(findings: list[P3FindingRecord]) -> list[P3ScoreContribution]:
    return [
        P3ScoreContribution(
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
    findings: list[P3FindingRecord],
) -> P3DocumentScoreRecord:
    contributions = _contributions(findings)
    total = min(SCORE_CAP, sum(c.points for c in contributions))
    return P3DocumentScoreRecord(
        project_id=project_id,
        document_id=document_id,
        document_type=document_type,
        quantitative_consistency_priority_score=total,
        finding_count=len(findings),
        contributions=contributions,
        scoring_config_version=P3_SCORING_CONFIG_VERSION,
    )


def score_project(
    project_id: str,
    document_scores: list[P3DocumentScoreRecord],
    package_findings: list[P3FindingRecord],
) -> P3ProjectScoreRecord:
    contributions = _contributions(package_findings)
    package_points = sum(c.points for c in contributions)
    mean_documents = (
        sum(s.quantitative_consistency_priority_score for s in document_scores)
        / len(document_scores)
        if document_scores
        else 0.0
    )
    total = min(SCORE_CAP, round(mean_documents) + package_points)
    return P3ProjectScoreRecord(
        project_id=project_id,
        quantitative_consistency_priority_score=total,
        document_scores={
            s.document_id: s.quantitative_consistency_priority_score for s in document_scores
        },
        package_finding_count=len(package_findings),
        package_contributions=contributions,
        scoring_config_version=P3_SCORING_CONFIG_VERSION,
    )

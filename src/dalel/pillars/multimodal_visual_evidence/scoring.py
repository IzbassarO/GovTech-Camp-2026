"""P5 scoring: Visual Evidence Review Priority, coverage and confidence.

The score («Приоритет проверки визуальных доказательств») is a transparent
sum of per-finding severity points with a cap — a manual-review queue signal,
never an environmental-harm probability, a legal-compliance probability or an
authenticity certification. Duplicates and excluded assets cannot inflate it:
checks operate on cluster representatives only.

All quantities are deterministic given the serialized model outputs, and the
validator recomputes every one of them from the artifacts.
"""

from __future__ import annotations

from dalel.pillars.multimodal_visual_evidence.config import (
    ASSESSMENT_CONFIDENCE_MAX,
    ASSESSMENT_CONFIDENCE_MIN,
    ASSESSMENT_CONFIDENCE_WEIGHTS,
    DOCUMENT_SCORE_NOTE,
    META_INTEGRATION_STATUS,
    P5_SCORING_CONFIG_VERSION,
    PROJECT_SCORE_NOTE,
    SCORE_CAP,
)
from dalel.pillars.multimodal_visual_evidence.schemas import (
    P5AssetContext,
    P5AssetRecord,
    P5Classification,
    P5DocumentScoreRecord,
    P5DuplicateCluster,
    P5FindingRecord,
    P5ProjectScoreRecord,
    P5ScoreContribution,
)


def _contributions(findings: list[P5FindingRecord]) -> list[P5ScoreContribution]:
    return [
        P5ScoreContribution(
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
    document_type: str | None,
    findings: list[P5FindingRecord],
    *,
    asset_count: int,
    analyzed_count: int,
    excluded_duplicate_count: int,
) -> P5DocumentScoreRecord:
    contributions = _contributions(findings)
    total = min(SCORE_CAP, sum(c.points for c in contributions))
    return P5DocumentScoreRecord(
        project_id=project_id,
        document_id=document_id,
        document_type=document_type,
        visual_evidence_review_priority_score=total,
        finding_count=len(findings),
        asset_count=asset_count,
        analyzed_representative_count=analyzed_count,
        excluded_duplicate_count=excluded_duplicate_count,
        contributions=contributions,
        scoring_config_version=P5_SCORING_CONFIG_VERSION,
        note=DOCUMENT_SCORE_NOTE,
    )


def compute_assessment_confidence(
    *,
    model_available: bool,
    classifications: list[P5Classification],
    contexts: list[P5AssetContext],
) -> tuple[float, dict[str, float]]:
    """Deterministic blend of availability/decisiveness/OCR/context components."""
    decisive_paths = {"model_zero_shot", "deterministic_supporting"}
    if classifications:
        decisiveness = sum(1 for c in classifications if c.decision_path in decisive_paths) / len(
            classifications
        )
    else:
        decisiveness = 0.0
    ocr_attempted = [c for c in contexts if c.ocr_status not in {"not_run", "unavailable"}]
    ocr_success = sum(1 for c in ocr_attempted if c.ocr_status == "completed")
    ocr_share = ocr_success / len(ocr_attempted) if ocr_attempted else 0.0
    linked = sum(
        1
        for c in contexts
        if c.caption is not None or c.nearest_heading is not None or c.entity_terms_matched
    )
    context_share = linked / len(contexts) if contexts else 0.0
    components = {
        "model_available": 1.0 if model_available else 0.0,
        "classification_decisiveness": round(decisiveness, 4),
        "ocr_success_share": round(ocr_share, 4),
        "context_link_share": round(context_share, 4),
    }
    blended = sum(ASSESSMENT_CONFIDENCE_WEIGHTS[name] * value for name, value in components.items())
    value = round(min(ASSESSMENT_CONFIDENCE_MAX, max(ASSESSMENT_CONFIDENCE_MIN, blended)), 2)
    return value, components


def score_project(
    project_id: str,
    document_scores: list[P5DocumentScoreRecord],
    package_findings: list[P5FindingRecord],
    *,
    assets: list[P5AssetRecord],
    clusters: list[P5DuplicateCluster],
    classifications: list[P5Classification],
    contexts: list[P5AssetContext],
    model_available: bool,
) -> P5ProjectScoreRecord:
    contributions = _contributions(package_findings)
    package_points = sum(c.points for c in contributions)
    mean_documents = (
        sum(s.visual_evidence_review_priority_score for s in document_scores) / len(document_scores)
        if document_scores
        else 0.0
    )
    total = min(SCORE_CAP, round(mean_documents) + package_points)

    with_bytes = [a for a in assets if a.file_sha256 is not None]
    analyzed = [a for a in assets if a.triage_status == "analyzed_representative"]
    eligible = [a for a in assets if a.eligible_for_analysis]
    duplicates = [a for a in assets if a.triage_status == "excluded_duplicate"]
    low_information = [a for a in assets if a.triage_status == "excluded_low_information"]
    header_logo = [
        a
        for a in assets
        if a.triage_status in {"excluded_repeated_header", "excluded_logo_or_branding"}
    ]
    unsupported = [a for a in assets if a.triage_status == "unsupported"]
    procedural = [a for a in assets if a.procedural_supporting_evidence]

    # Coverage means SEMANTIC coverage: without the model, representatives
    # were inventoried but not semantically analyzed — honestly zero.
    if not eligible:
        coverage = None
    elif not model_available:
        coverage = 0.0
    else:
        coverage = round(len(analyzed) / len(eligible), 3)
    confidence, components = compute_assessment_confidence(
        model_available=model_available,
        classifications=classifications,
        contexts=contexts,
    )
    return P5ProjectScoreRecord(
        project_id=project_id,
        visual_evidence_review_priority_score=total,
        document_scores={
            s.document_id: s.visual_evidence_review_priority_score for s in document_scores
        },
        package_finding_count=len(package_findings),
        package_contributions=contributions,
        total_asset_count=len(assets),
        assets_with_bytes_count=len(with_bytes),
        eligible_asset_count=len(eligible),
        analyzed_representative_count=len(analyzed),
        excluded_duplicate_count=len(duplicates),
        excluded_low_information_count=len(low_information),
        excluded_header_or_logo_count=len(header_logo),
        unsupported_asset_count=len(unsupported),
        procedural_asset_count=len(procedural),
        duplicate_cluster_count=len(clusters),
        visual_coverage=coverage,
        assessment_confidence=confidence,
        confidence_components=components,
        model_status="available" if model_available else "unavailable",
        meta_integration_status=META_INTEGRATION_STATUS,
        scoring_config_version=P5_SCORING_CONFIG_VERSION,
        note=PROJECT_SCORE_NOTE,
    )

"""Deterministic additive Meta score with exact caps and discounts."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from dalel.meta_review import META_SCORING_CONFIG_VERSION, META_VERSION
from dalel.meta_review.artifacts import PillarArtifactBundle
from dalel.meta_review.config import (
    P2_SYNTHETIC_CAP,
    P2_SYNTHETIC_DISCOUNT,
    PILLAR_CAPS,
    SCORE_CAP,
)
from dalel.meta_review.explainability import (
    COUNTERFACTUAL,
    integrated_limitations,
    top_positive_factors,
)
from dalel.meta_review.schemas import (
    CalibrationMetadata,
    CoverageAssessment,
    FeatureContribution,
    MetaFeatureRecord,
    ModelMetadata,
    PillarContribution,
    PillarId,
    PriorityLevel,
    ProjectMetaAssessment,
    ScoreAdjustment,
    deterministic_id,
)

_CENT = Decimal("0.01")


def _money(value: float | Decimal) -> float:
    return float(Decimal(str(value)).quantize(_CENT, rounding=ROUND_HALF_UP))


def priority_level(score: float) -> PriorityLevel:
    if score < 25.0:
        return "low"
    if score < 50.0:
        return "moderate"
    if score < 75.0:
        return "elevated"
    return "high"


def _p2_authoritative_ratio(features: list[MetaFeatureRecord]) -> float:
    feature = next(
        (item for item in features if item.feature_name == "p2_authoritative_coverage"), None
    )
    return feature.normalized_value if feature is not None else 0.0


def _allocate_applied(
    features: list[MetaFeatureRecord], target: float, adjustment_labels: list[str]
) -> list[FeatureContribution]:
    positive = [item for item in features if item.contribution > 0]
    raw_total = _money(sum(item.contribution for item in features))
    target_decimal = Decimal(str(_money(target)))
    allocated: dict[str, float] = {item.feature_id: 0.0 for item in features}
    if positive and raw_total > 0:
        scale = target_decimal / Decimal(str(raw_total))
        running = Decimal("0")
        for item in positive[:-1]:
            value = (Decimal(str(item.contribution)) * scale).quantize(
                _CENT, rounding=ROUND_HALF_UP
            )
            allocated[item.feature_id] = float(value)
            running += value
        allocated[positive[-1].feature_id] = float(target_decimal - running)

    result: list[FeatureContribution] = []
    for item in features:
        applied = _money(max(0.0, allocated[item.feature_id]))
        result.append(
            FeatureContribution(
                contribution_id=deterministic_id(
                    "META_FC", item.feature_id, str(item.contribution), str(applied)
                ),
                feature_id=item.feature_id,
                project_id=item.project_id,
                feature_name=item.feature_name,
                pillar_source=item.pillar_source,
                raw_value=item.raw_value,
                normalized_value=item.normalized_value,
                weight=item.weight,
                raw_contribution=item.contribution,
                contribution=applied,
                source_artifact_ids=item.source_artifact_ids,
                source_finding_ids=item.source_finding_ids,
                explanation=item.explanation,
                limitations=item.limitations,
                adjustments=adjustment_labels if item.contribution > 0 else [],
            )
        )
    return result


def _score_pillar(
    project_id: str,
    pillar: PillarId,
    features: list[MetaFeatureRecord],
    coverage: CoverageAssessment,
    available: bool,
) -> tuple[PillarContribution, list[FeatureContribution]]:
    pillar_features = [item for item in features if item.pillar_source == pillar]
    raw_subtotal = _money(sum(item.contribution for item in pillar_features))
    discount_factor = 1.0
    cap = PILLAR_CAPS[pillar]
    discount_reason = "No source discount applies to this pillar."
    if pillar == "P2" and available:
        authoritative_ratio = _p2_authoritative_ratio(pillar_features)
        discount_factor = round(
            P2_SYNTHETIC_DISCOUNT + (1.0 - P2_SYNTHETIC_DISCOUNT) * authoritative_ratio,
            6,
        )
        cap = _money(
            P2_SYNTHETIC_CAP + (PILLAR_CAPS["P2"] - P2_SYNTHETIC_CAP) * authoritative_ratio
        )
        discount_reason = (
            "P2 contribution is discounted in proportion to non-authoritative synthetic coverage."
        )
    discounted = _money(raw_subtotal * discount_factor)
    discount_amount = _money(discounted - raw_subtotal)
    subtotal = _money(min(discounted, cap))
    cap_adjustment = _money(subtotal - discounted)

    discount_records: list[ScoreAdjustment] = []
    adjustments: list[str] = []
    if pillar == "P2" and available:
        discount_records.append(
            ScoreAdjustment(
                adjustment_id=deterministic_id(
                    "META_A",
                    project_id,
                    pillar,
                    "discount",
                    str(discount_factor),
                    str(discount_amount),
                ),
                adjustment_type="discount",
                pillar_source=pillar,
                amount=discount_amount,
                applied=discount_amount < 0,
                reason=discount_reason,
                config_key="p2_synthetic_discount",
            )
        )
        if discount_amount < 0:
            adjustments.append(f"P2 synthetic-source discount ×{discount_factor:g}")
    cap_record = ScoreAdjustment(
        adjustment_id=deterministic_id(
            "META_A", project_id, pillar, "cap", str(cap), str(cap_adjustment)
        ),
        adjustment_type="cap",
        pillar_source=pillar,
        amount=cap_adjustment,
        applied=cap_adjustment < 0,
        reason=(
            "Synthetic P2 safeguard cap prevents the demo corpus from dominating."
            if pillar == "P2"
            else f"{pillar} subtotal is bounded to prevent single-pillar dominance."
        ),
        config_key="p2_synthetic_cap" if pillar == "P2" else f"pillar_caps.{pillar}",
    )
    if cap_adjustment < 0:
        adjustments.append(f"{pillar} cap {cap:g}")
    contributions = _allocate_applied(pillar_features, subtotal, adjustments)
    limitations: list[str] = []
    if not available:
        limitations.append(
            f"{pillar} artifacts are unavailable; the pillar contributes no score "
            "and is not treated as passed."
        )
    if pillar == "P2" and available:
        limitations.append(
            "P2 uses a synthetic non-authoritative corpus; "
            "its contribution is visibly discounted and capped."
        )
    pillar_record = PillarContribution(
        contribution_id=deterministic_id(
            "META_PC",
            project_id,
            pillar,
            str(raw_subtotal),
            str(subtotal),
            str(available),
            ",".join(item.contribution_id for item in contributions),
        ),
        project_id=project_id,
        pillar_id=pillar,
        available=available,
        raw_subtotal=raw_subtotal,
        discount_factor=discount_factor,
        discount_amount=discount_amount,
        cap=cap,
        cap_adjustment=cap_adjustment,
        subtotal=subtotal,
        evidence_coverage=coverage.pillar_coverage[pillar],
        assessment_confidence=coverage.pillar_confidence[pillar],
        caps_applied=[cap_record],
        discounts_applied=discount_records,
        feature_contribution_ids=[item.contribution_id for item in contributions],
        limitations=limitations,
    )
    return pillar_record, contributions


def score_project(
    project_id: str,
    features: list[MetaFeatureRecord],
    coverage: CoverageAssessment,
    bundles: dict[str, PillarArtifactBundle],
    calibration: CalibrationMetadata,
    model: ModelMetadata,
) -> ProjectMetaAssessment:
    pillar_records: list[PillarContribution] = []
    feature_records: list[FeatureContribution] = []
    for raw_pillar in ("P1", "P2", "P3", "P4"):
        pillar: PillarId = raw_pillar  # type: ignore[assignment]
        record, applied = _score_pillar(
            project_id, pillar, features, coverage, bundles[pillar].available
        )
        pillar_records.append(record)
        feature_records.extend(applied)

    base_score = 0.0
    uncertainty_adjustment = 0.0
    subtotal = _money(base_score + sum(item.subtotal for item in pillar_records))
    global_cap_adjustment = _money(min(subtotal, SCORE_CAP) - subtotal)
    final_score = _money(subtotal + global_cap_adjustment + uncertainty_adjustment)
    uncertainty_record = ScoreAdjustment(
        adjustment_id=deterministic_id("META_A", project_id, "uncertainty", "0"),
        adjustment_type="uncertainty",
        pillar_source=None,
        amount=0.0,
        applied=False,
        reason=(
            "Coverage and uncertainty change assessment confidence, not review priority; "
            "no hidden score reduction is applied."
        ),
        config_key="safeguards.missing_pillars_reduce_confidence_only",
    )
    cap_records = [record for pillar in pillar_records for record in pillar.caps_applied]
    discount_records = [record for pillar in pillar_records for record in pillar.discounts_applied]
    limitations = (
        integrated_limitations(list(coverage.missing_pillars), bundles["P2"].available)
        + coverage.limitations
    )
    assessment_id = deterministic_id(
        "META",
        project_id,
        str(final_score),
        str(coverage.evidence_coverage),
        str(coverage.assessment_confidence),
        META_SCORING_CONFIG_VERSION,
        ",".join(item.contribution_id for item in pillar_records),
        calibration.calibration_status,
    )
    return ProjectMetaAssessment(
        assessment_id=assessment_id,
        project_id=project_id,
        meta_version=META_VERSION,
        scoring_config_version=META_SCORING_CONFIG_VERSION,
        base_score=base_score,
        raw_feature_total=_money(sum(item.contribution for item in features)),
        uncertainty_adjustment=uncertainty_adjustment,
        global_cap_adjustment=global_cap_adjustment,
        review_priority_score=final_score,
        review_priority_level=priority_level(final_score),
        evidence_coverage=coverage.evidence_coverage,
        assessment_confidence=coverage.assessment_confidence,
        pillar_contributions=pillar_records,
        feature_contributions=feature_records,
        top_positive_factors=top_positive_factors(feature_records),
        caps_applied=cap_records,
        discounts_applied=discount_records,
        uncertainty_adjustments=[uncertainty_record],
        limitations=list(dict.fromkeys(limitations)),
        counterfactual_explanation=COUNTERFACTUAL,
        calibration_status=calibration.calibration_status,
        calibrated_probability=None,
        shap_contributions=None,
        calibration_metadata=calibration,
        model_metadata=model,
    )

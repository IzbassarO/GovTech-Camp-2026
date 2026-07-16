"""Versioned configuration for deterministic Meta review-priority scoring."""

from __future__ import annotations

from typing import Any

from dalel.meta_review import META_SCORING_CONFIG_VERSION, META_VERSION

PILLARS = ("P1", "P2", "P3", "P4")

# Feature weights are review-priority points, not learned coefficients.
FEATURE_WEIGHTS: dict[str, dict[str, float]] = {
    "P1": {
        # The accepted project score is exposed as context but not added again:
        # the traceable finding-derived features below already contain its signal.
        "p1_project_priority_signal": 0.0,
        "p1_high_severity_findings": 10.0,
        "p1_medium_severity_rate": 12.0,
        "p1_low_severity_rate": 4.0,
        "p1_structural_anomaly_rate": 9.0,
        "p1_ocr_or_empty_page_rate": 4.0,
    },
    "P2": {
        "p2_potential_conflicts": 16.0,
        # Missing-document findings are the explainable subtype of the same
        # potential-conflict assessments and therefore are not added twice.
        "p2_missing_document_cues": 0.0,
        "p2_insufficient_evidence": 4.0,
        "p2_retrieval_confidence": 0.0,
        "p2_authoritative_coverage": 0.0,
        "p2_synthetic_info_notices": 0.0,
    },
    "P3": {
        "p3_proven_conflicts": 18.0,
        "p3_high_severity_findings": 0.0,
        "p3_medium_severity_findings": 0.0,
        "p3_aggregation_mismatches": 0.0,
        "p3_unresolved_context_findings": 2.0,
        "p3_compared_candidate_rate": 0.0,
        "p3_suppressed_candidate_rate": 0.0,
        "p3_quantitative_mentions": 0.0,
    },
    "P4": {
        "p4_proven_conflicts": 20.0,
        "p4_unresolved_identity_findings": 5.0,
        "p4_other_diagnostic_findings": 2.0,
        "p4_medium_severity_findings": 0.0,
        "p4_linked_document_rate": 0.0,
        "p4_suppressed_comparison_rate": 0.0,
        "p4_graph_evidence_rate": 0.0,
    },
}

PILLAR_CAPS = {"P1": 35.0, "P2": 15.0, "P3": 25.0, "P4": 25.0}
P2_SYNTHETIC_DISCOUNT = 0.35
P2_SYNTHETIC_CAP = 8.0
SCORE_CAP = 100.0
SCORE_PRECISION = 2
NORMALIZED_PRECISION = 6

LEVEL_THRESHOLDS = {
    "low": [0.0, 24.99],
    "moderate": [25.0, 49.99],
    "elevated": [50.0, 74.99],
    "high": [75.0, 100.0],
}

COVERAGE_WEIGHTS = {"P1": 0.25, "P2": 0.25, "P3": 0.25, "P4": 0.25}
PILLAR_RELIABILITY_BASE = {"P1": 0.85, "P2": 1.0, "P3": 1.0, "P4": 0.85}
MIN_EXPERT_LABELS = 40

P1_STRUCTURAL_TYPES = frozenset(
    {
        "duplicate_heading",
        "structural_anomaly",
        "suspicious_document_length",
        "low_text_coverage",
        "missing_expected_section",
        "missing_expected_tables",
    }
)
P1_OCR_OR_EMPTY_TYPES = frozenset({"high_ocr_dependency", "empty_page"})
P3_PROVEN_CONFLICT_TYPES = frozenset(
    {
        "aggregate_total_mismatch",
        "bound_violation",
        "direct_value_conflict",
        "equivalent_unit_conflict",
        "impossible_value",
        "percentage_mismatch",
        "range_inversion",
        "temporal_scope_conflict",
    }
)
P3_UNRESOLVED_TYPES = frozenset(
    {"ambiguous_numeric_format", "insufficient_context", "unsupported_conversion"}
)
P4_PROVEN_CONFLICT_TYPES = frozenset(
    {
        "conflicting_project_identity",
        "conflicting_facility_identity",
        "conflicting_location",
        "conflicting_activity_or_category",
        "conflicting_reporting_period",
        "conflicting_operator",
    }
)
P4_DIAGNOSTIC_TYPES = frozenset(
    {
        "unresolved_entity_identity",
        "insufficient_cross_document_context",
        "orphan_document_reference",
    }
)


def config_snapshot() -> dict[str, Any]:
    """Return the complete stable configuration serialized with every run."""
    return {
        "meta_version": META_VERSION,
        "scoring_config_version": META_SCORING_CONFIG_VERSION,
        "primary_label": "Integrated Review Priority Score",
        "score_cap": SCORE_CAP,
        "score_precision": SCORE_PRECISION,
        "normalized_precision": NORMALIZED_PRECISION,
        "level_thresholds": LEVEL_THRESHOLDS,
        "feature_weights": FEATURE_WEIGHTS,
        "pillar_caps": PILLAR_CAPS,
        "p2_synthetic_discount": P2_SYNTHETIC_DISCOUNT,
        "p2_synthetic_cap": P2_SYNTHETIC_CAP,
        "coverage_weights": COVERAGE_WEIGHTS,
        "pillar_reliability_base": PILLAR_RELIABILITY_BASE,
        "minimum_expert_labels": MIN_EXPERT_LABELS,
        "safeguards": [
            "P2 synthetic evidence is discounted and capped",
            "missing pillars reduce coverage and confidence, not priority",
            "zero P3/P4 findings provide no safe bonus",
            "information findings have bounded feature weights",
            "all project arithmetic is deterministic and capped at 100",
        ],
    }

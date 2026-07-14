"""Versioned deterministic configuration for P1."""

from __future__ import annotations

from typing import Any

SCORING_CONFIG_VERSION = "1.0.0"

# Contribution points per finding severity. Deterministic and monotonic:
# every finding adds a non-negative contribution; the score is capped at 100.
SEVERITY_POINTS: dict[str, int] = {
    "high": 25,
    "medium": 12,
    "low": 5,
    "info": 2,
}

SCORE_CAP = 100

# Package score aggregation: mean of document scores plus package-level
# finding points, capped. Monotonic in both components.
PACKAGE_DOC_WEIGHT = 1.0

# Quality thresholds (deterministic, documented; not legal rules).
MIN_USABLE_CHARS_PER_PAGE = 32  # mirrors ingestion analysis threshold
LOW_TEXT_COVERAGE_RATIO = 0.20  # share of pages under threshold
HIGH_OCR_DEPENDENCY_RATIO = 0.30  # ocr pages / total pages
DUPLICATE_HEADING_MIN_OCCURRENCES = 3  # ToC + body naturally yields 2

# Suspiciously short documents, pages per document_type. These are expected
# structural sizes observed for permit documentation, not legal minimums.
MIN_EXPECTED_PAGES: dict[str, int] = {
    "ndv": 10,
    "pek": 5,
    "puo": 5,
    "ovvos": 10,
    "roos": 10,
    "action_plan": 1,
    "nontechnical_summary": 2,
    "explanatory_note": 3,
    "working_project_note": 10,
}

# Document types where at least one extracted table is structurally expected.
TABLE_EXPECTED_TYPES = frozenset(
    {"ndv", "pek", "puo", "ovvos", "roos", "action_plan", "working_project_note"}
)

# Section matching thresholds.
TOKEN_OVERLAP_THRESHOLD = 0.6
FUZZY_RATIO_THRESHOLD = 0.82
# A fuzzy candidate must additionally share discriminative (non-generic)
# token evidence: an exact shared non-generic token, or a pair of non-generic
# tokens whose similarity reaches this per-token ratio.
FUZZY_TOKEN_RATIO_THRESHOLD = 0.85

# Generic structural tokens that occur across unrelated headings; they must
# never be the sole evidence for a fuzzy match (e.g. «шумовое воздействие» vs
# «Тепловое воздействие» share only «воздействие» and must NOT match).
GENERIC_TOKENS: frozenset[str] = frozenset(
    {
        "воздействие",
        "воздействия",
        "раздел",
        "разделы",
        "мероприятия",
        "мероприятий",
        "охрана",
        "охране",
        "оценка",
        "оценки",
        "общие",
        "общая",
        "сведения",
        "характеристика",
        "часть",
        "глава",
        "программа",
        "проект",
        "контроль",
        "окружающей",
        "среды",
        "среда",
    }
)

# Date-range extraction: plausible permit validity years.
DATE_RANGE_MIN_YEAR = 2015
DATE_RANGE_MAX_YEAR = 2045


def config_snapshot() -> dict[str, Any]:
    """Serializable snapshot of every deterministic knob used by a run."""
    from dalel.pillars.document_integrity import P1_VERSION
    from dalel.pillars.document_integrity.taxonomy import TAXONOMY_VERSION

    return {
        "p1_version": P1_VERSION,
        "taxonomy_version": TAXONOMY_VERSION,
        "scoring_config_version": SCORING_CONFIG_VERSION,
        "severity_points": dict(SEVERITY_POINTS),
        "score_cap": SCORE_CAP,
        "min_usable_chars_per_page": MIN_USABLE_CHARS_PER_PAGE,
        "low_text_coverage_ratio": LOW_TEXT_COVERAGE_RATIO,
        "high_ocr_dependency_ratio": HIGH_OCR_DEPENDENCY_RATIO,
        "duplicate_heading_min_occurrences": DUPLICATE_HEADING_MIN_OCCURRENCES,
        "min_expected_pages": dict(MIN_EXPECTED_PAGES),
        "table_expected_types": sorted(TABLE_EXPECTED_TYPES),
        "token_overlap_threshold": TOKEN_OVERLAP_THRESHOLD,
        "fuzzy_ratio_threshold": FUZZY_RATIO_THRESHOLD,
        "fuzzy_token_ratio_threshold": FUZZY_TOKEN_RATIO_THRESHOLD,
        "generic_tokens": sorted(GENERIC_TOKENS),
        "matching_methods": [
            "exact_equality",
            "normalized_substring",
            "token_overlap",
            "fuzzy",
        ],
        "llm_used": False,
        "embeddings_used": False,
    }

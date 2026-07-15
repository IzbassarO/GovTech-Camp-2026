"""Versioned deterministic configuration for P3.

Every knob is a module constant captured verbatim into
``config_snapshot.json``; there is no config file and no environment
dependence. Tolerances follow the documented mismatch condition::

    mismatch  <=>  abs_diff > max(absolute_tolerance, rounding_tolerance)
               AND rel_diff > relative_tolerance

where ``rel_diff = abs_diff / max(|a|, |b|)`` (symmetric; defined for the
one-value-zero case, where it equals 1) and ``rounding_tolerance`` is the
worst-case display-rounding error of the participating operands
(``0.5 * 10^-decimals`` per operand, converted to canonical units).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

P3_SCORING_CONFIG_VERSION = "1.0.0"

# Contribution points per finding severity (mirrors P1's scale).
SEVERITY_POINTS: dict[str, int] = {
    "high": 25,
    "medium": 12,
    "low": 5,
    "info": 2,
}

SCORE_CAP = 100

# --- comparison tolerances ---------------------------------------------------
# Relative tolerance for direct value comparisons: differences up to 2% are
# treated as presentation noise (rounding chains, unit re-derivation).
DIRECT_REL_TOLERANCE = Decimal("0.02")
# Absolute tolerance floor in CANONICAL units per dimension. Canonical units
# are intentionally small (g, mg/m3), so the floors are conservative.
DIRECT_ABS_TOLERANCE: dict[str, Decimal] = {
    "mass": Decimal("0.5"),  # 0.5 g
    "mass_rate": Decimal("0.0000005"),  # 0.0000005 g per basis-unit of time
    "volume": Decimal("0.0005"),  # 0.0005 m3
    "volume_rate": Decimal("0.0005"),
    "concentration": Decimal("0.00005"),  # mg/m3
    "concentration_normal": Decimal("0.00005"),
    "density": Decimal("0.0005"),  # kg/m3
    "mass_fraction": Decimal("0.00005"),  # mg/kg
    "area": Decimal("0.05"),  # m2
    "percent": Decimal("0.05"),  # percentage points
    "percent_points": Decimal("0.05"),
    "power": Decimal("0.05"),  # W
    "temperature": Decimal("0.05"),
    "velocity": Decimal("0.005"),
    "length": Decimal("0.005"),
}
DEFAULT_ABS_TOLERANCE = Decimal("0.0000005")

# When the expected/reference value is exactly zero, relative difference is
# undefined; a mismatch then requires abs_diff > ZERO_CASE_ABS_TOLERANCE
# in canonical units (stricter gate, because tiny absolute noise around
# zero must not produce contradictions).
ZERO_CASE_ABS_MULTIPLIER = Decimal("10")

# Approximate values («около», «примерно», «~») widen the relative tolerance.
APPROX_REL_MULTIPLIER = Decimal("5")

# --- aggregation -------------------------------------------------------------
AGGREGATE_REL_TOLERANCE = Decimal("0.02")
# Minimum number of parseable component rows for a total check.
AGGREGATE_MIN_COMPONENTS = 2
# A column is numeric when at least this share of its non-empty body cells
# parse as single numbers.
NUMERIC_COLUMN_MIN_SHARE = Decimal("0.6")
# At most this many leading rows are treated as table header.
MAX_HEADER_ROWS = 3

# --- percentages -------------------------------------------------------------
# Percentage recomputation tolerance in percentage points (on top of the
# display-rounding quantum of the stated percentage).
PERCENT_ABS_TOLERANCE_PP = Decimal("0.5")
# A percent column total is treated as a 100%-share column when the stated
# total is within this many points of 100.
PERCENT_TOTAL_100_WINDOW = Decimal("2")
# Share values outside [0 - eps, 100 + eps] are impossible for true shares.
PERCENT_SHARE_EPSILON = Decimal("0.5")

# --- extraction --------------------------------------------------------------
# Character window before a number in which bound/approx markers are sought.
MARKER_WINDOW_CHARS = 32
# Character window after a number in which a unit is sought.
UNIT_WINDOW_CHARS = 24
# Numbers with more total digits than this are identifier-like (BIN, phone).
MAX_QUANTITY_DIGITS = 9
# Years treated as calendar identifiers when bare.
YEAR_MIN = 1900
YEAR_MAX = 2100

# --- confidence rubric (deterministic, explainable) ---------------------------
CONFIDENCE_BASE: dict[str, float] = {
    "direct_value_conflict": 0.8,
    "equivalent_unit_conflict": 0.8,
    "aggregate_total_mismatch": 0.75,
    "percentage_mismatch": 0.7,
    "bound_violation": 0.7,
    "range_inversion": 0.85,
    "impossible_value": 0.85,
    "temporal_scope_conflict": 0.6,
    "ambiguous_numeric_format": 0.3,
    "insufficient_context": 0.3,
    "unsupported_conversion": 0.4,
    "dimension_or_unit_conflict": 0.5,
}
CONFIDENCE_PENALTIES: dict[str, float] = {
    "ocr_source": 0.15,
    "ambiguous_number": 0.25,
    "approximate_value": 0.1,
    "header_unit_inherited": 0.05,
    "partial_extraction": 0.05,
    "aggregation_direction_after": 0.1,
    "aggregation_from_subtotals": 0.1,
    "context_from_section_title": 0.05,
    "multi_number_cell": 0.2,
    "possible_table_echo": 0.2,
}
CONFIDENCE_MIN = 0.05
CONFIDENCE_MAX = 0.95

# Mention-level extraction confidence: 1.0 minus applicable penalties,
# floored at MENTION_CONFIDENCE_MIN. Factors are recorded as mention flags.
MENTION_CONFIDENCE_PENALTIES: dict[str, float] = {
    "ambiguous_decimal_grouping": 0.3,
    "ocr_source": 0.2,
    "approximate": 0.1,
    "multi_number_cell": 0.2,
    "unitless": 0.3,
    "column_header_unit": 0.05,
    "possible_table_echo": 0.2,
    "power_notation": 0.05,
    "range_inversion": 0.2,
    "context_from_section_title": 0.05,
    "grouped_thousands": 0.0,
    "leading_separator": 0.05,
    "decimal_comma": 0.0,
}
MENTION_CONFIDENCE_MIN = 0.05

# --- severity rubric ----------------------------------------------------------
# Relative difference thresholds for escalation (after tolerance is exceeded).
SEVERITY_REL_HIGH = Decimal("0.5")
SEVERITY_REL_MEDIUM = Decimal("0.1")
# Findings whose confidence falls below this are capped at severity low.
SEVERITY_CONFIDENCE_GATE = 0.5
# Materiality floors per dimension (canonical units): if BOTH values are
# below the floor, severity is capped at low even for large relative gaps.
MATERIALITY_FLOOR: dict[str, Decimal] = {
    "mass": Decimal("1000"),  # 1 kg
    "mass_rate": Decimal("0.01"),
    "volume": Decimal("1"),
    "volume_rate": Decimal("0.1"),
    "concentration": Decimal("0.01"),
    "concentration_normal": Decimal("0.01"),
    "density": Decimal("1"),
    "mass_fraction": Decimal("0.1"),
    "area": Decimal("1"),
    "percent": Decimal("0.5"),
    "percent_points": Decimal("0.5"),
    "power": Decimal("10"),
    "temperature": Decimal("1"),
    "velocity": Decimal("0.1"),
    "length": Decimal("0.1"),
}


def config_snapshot() -> dict[str, Any]:
    """Serializable snapshot of every deterministic knob used by a run."""
    from dalel.pillars.quantitative_consistency import P3_VERSION
    from dalel.pillars.quantitative_consistency.units import registry_snapshot

    return {
        "p3_version": P3_VERSION,
        "scoring_config_version": P3_SCORING_CONFIG_VERSION,
        "severity_points": dict(SEVERITY_POINTS),
        "score_cap": SCORE_CAP,
        "direct_rel_tolerance": str(DIRECT_REL_TOLERANCE),
        "direct_abs_tolerance": {k: str(v) for k, v in sorted(DIRECT_ABS_TOLERANCE.items())},
        "default_abs_tolerance": str(DEFAULT_ABS_TOLERANCE),
        "zero_case_abs_multiplier": str(ZERO_CASE_ABS_MULTIPLIER),
        "approx_rel_multiplier": str(APPROX_REL_MULTIPLIER),
        "aggregate_rel_tolerance": str(AGGREGATE_REL_TOLERANCE),
        "aggregate_min_components": AGGREGATE_MIN_COMPONENTS,
        "numeric_column_min_share": str(NUMERIC_COLUMN_MIN_SHARE),
        "max_header_rows": MAX_HEADER_ROWS,
        "percent_abs_tolerance_pp": str(PERCENT_ABS_TOLERANCE_PP),
        "percent_total_100_window": str(PERCENT_TOTAL_100_WINDOW),
        "percent_share_epsilon": str(PERCENT_SHARE_EPSILON),
        "marker_window_chars": MARKER_WINDOW_CHARS,
        "unit_window_chars": UNIT_WINDOW_CHARS,
        "max_quantity_digits": MAX_QUANTITY_DIGITS,
        "year_range_suppressed": [YEAR_MIN, YEAR_MAX],
        "confidence_base": dict(sorted(CONFIDENCE_BASE.items())),
        "confidence_penalties": dict(sorted(CONFIDENCE_PENALTIES.items())),
        "confidence_bounds": [CONFIDENCE_MIN, CONFIDENCE_MAX],
        "mention_confidence_penalties": dict(sorted(MENTION_CONFIDENCE_PENALTIES.items())),
        "mention_confidence_min": MENTION_CONFIDENCE_MIN,
        "severity_rel_high": str(SEVERITY_REL_HIGH),
        "severity_rel_medium": str(SEVERITY_REL_MEDIUM),
        "severity_confidence_gate": SEVERITY_CONFIDENCE_GATE,
        "materiality_floor": {k: str(v) for k, v in sorted(MATERIALITY_FLOOR.items())},
        "mismatch_condition": (
            "abs_diff > max(absolute_tolerance, rounding_tolerance)"
            " AND rel_diff > relative_tolerance;"
            " rel_diff = abs_diff / max(|a|, |b|)"
        ),
        "unit_registry": registry_snapshot(),
        "llm_used": False,
        "embeddings_used": False,
        "ocr_used_by_p3": False,
    }

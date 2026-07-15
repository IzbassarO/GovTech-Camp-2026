"""P3 record schemas: quantitative mentions, candidates, findings, scores.

Conventions mirror P1 (``FindingRecord`` field names, severity vocabulary,
``review_status``), extended with the comparison evidence P3 must carry.
Every numeric value that participates in normalization or comparison is
serialized as a canonical decimal STRING (no binary floats in artifacts);
``confidence`` differs from P1 deliberately: P3 findings carry a
deterministic rubric-based confidence with its factors recorded.
"""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

P3_FINDING_TYPES = frozenset(
    {
        "direct_value_conflict",
        "equivalent_unit_conflict",
        "aggregate_total_mismatch",
        "percentage_mismatch",
        "bound_violation",
        "range_inversion",
        "impossible_value",
        "ambiguous_numeric_format",
        "insufficient_context",
        "unsupported_conversion",
    }
)

SEVERITIES = ("high", "medium", "low", "info")


def deterministic_id(prefix: str, *parts: str) -> str:
    """Content-derived stable id: ``{prefix}__{sha256[:12]}``.

    Never uses Python's randomized ``hash()``; the basis is the canonical
    ``|``-joined UTF-8 byte string of the parts.
    """
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:12]
    return f"{prefix}__{digest}"


class MentionLocation(BaseModel):
    """Where a quantitative mention physically lives in the curated dataset."""

    model_config = ConfigDict(extra="forbid")

    source_kind: Literal["table_cell", "section_text"]
    section_id: str | None = None
    section_title: str | None = None
    table_id: str | None = None
    row: int | None = Field(default=None, ge=0)
    col: int | None = Field(default=None, ge=0)
    page_number: int | None = None
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)


class QuantMention(BaseModel):
    """One normalized quantitative mention with full provenance."""

    model_config = ConfigDict(extra="forbid")

    mention_id: str  # P3Q__<12hex>, content-derived
    project_id: str
    document_id: str
    location: MentionLocation
    raw_text: str  # evidence window (normalized text) around the number
    raw_number: str  # verbatim numeric construct
    kind: Literal["scalar", "range"]
    modifier: Literal["none", "approximate", "upper_bound", "lower_bound"]
    bound_inclusive: bool | None = None
    # Values in the ORIGINAL unit, canonical decimal strings.
    value: str | None = None
    value_low: str | None = None
    value_high: str | None = None
    unit_raw: str | None = None
    unit_canonical: str | None = None  # canonical spelling of the parsed unit
    unit_source: Literal["inline", "column_header", "none"]
    dimension: str | None = None  # e.g. "mass_rate/year"
    # Values converted to the dimension's canonical unit.
    canonical_unit: str | None = None
    canonical_value: str | None = None
    canonical_low: str | None = None
    canonical_high: str | None = None
    conversion_factor: str | None = None
    display_quantum: str  # 10^-decimals of the displayed number
    canonical_quantum: str | None = None
    # Semantic context (deterministic lexicons; None = not identified).
    metric_group: str | None = None
    metric_label: str | None = None
    substance: str | None = None
    source_key: str | None = None
    period_key: str | None = None
    qualifiers: list[str] = Field(default_factory=list)  # sorted tags
    scope: Literal["item", "total"] = "item"
    # Facility-level aggregation scope: "source" = one emission source
    # (positively attributed), "enterprise" = whole-object inventory,
    # "unknown" = attribution could not be established (stays unknown).
    aggregation_scope: Literal["source", "enterprise", "unknown"] = "unknown"
    # Sub-entity identity INSIDE a source: release point («источник
    # выделения N 6001 05»), operation («расчет выбросов от сварки») or
    # equipment. One source number is NOT proof that its quantities belong
    # to one real-world sub-entity; None = unknown.
    sub_entity: str | None = None
    extraction_confidence: float
    flags: list[str] = Field(default_factory=list)  # sorted quality flags


class ComparisonCandidate(BaseModel):
    """Why two or more mentions were (or were not) compared."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: str  # P3C__<12hex>
    rule: str  # comparison rule that produced/examined the candidate
    project_id: str
    document_ids: list[str]  # sorted unique
    mention_ids: list[str]  # sorted
    # Explicit semantic alignment record: aspect -> matched value / flag.
    compatibility: dict[str, str]
    # Tri-state compatibility per semantic dimension: match/conflict/unknown.
    dimension_states: dict[str, str] = Field(default_factory=dict)
    relationship: Literal[
        "same_table",
        "same_document",
        "cross_document",
    ]
    confidence: float
    status: Literal["compared", "suppressed"]
    suppression_reason: str | None = None  # primary reason (first)
    suppression_reasons: list[str] = Field(default_factory=list)  # ALL reasons


class P3Evidence(BaseModel):
    """Same shape as P1 evidence for review-tooling compatibility."""

    model_config = ConfigDict(extra="forbid")

    document_id: str | None = None
    page_number: int | None = None
    quote: str | None = None
    note: str | None = None


class ConversionDetail(BaseModel):
    """One mention's reproducible unit conversion inside a finding."""

    model_config = ConfigDict(extra="forbid")

    mention_id: str
    raw: str  # e.g. «1,2 т/год»
    parsed_value: str  # canonical decimal string in original unit
    unit: str | None
    conversion_factor: str | None  # multiplier to canonical unit
    canonical_value: str | None
    canonical_unit: str | None


class AggregationComponent(BaseModel):
    """One row's inclusion/exclusion decision inside an aggregation check."""

    model_config = ConfigDict(extra="forbid")

    row: int
    label: str | None = None
    included: bool
    reason: str  # component | subset_enumeration | category_header | overlap_child:N | ...
    value: str | None = None  # display units
    canonical_value: str | None = None
    conversion_factor: str | None = None
    overlaps_row: int | None = None


class AggregationDetail(BaseModel):
    """Explicit aggregation structure so the sum is independently
    recomputable from the raw table cells."""

    model_config = ConfigDict(extra="forbid")

    table_id: str
    column: int
    total_row: int
    direction: str  # above | below | subtotals
    table_fingerprint: str  # structural fingerprint (detects copies)
    identical_copies: list[str] = Field(default_factory=list)  # other table_ids
    components: list[AggregationComponent] = Field(default_factory=list)


class ComparisonDetail(BaseModel):
    """The exact mathematical rule evaluated, fully recomputable."""

    model_config = ConfigDict(extra="forbid")

    formula: str
    expected_value: str | None = None
    observed_value: str | None = None
    abs_diff: str | None = None
    rel_diff: str | None = None  # None when undefined (reference is zero)
    tolerance_abs: str | None = None
    tolerance_rel: str | None = None
    rounding_tolerance: str | None = None
    canonical_unit: str | None = None
    conversions: list[ConversionDetail] = Field(default_factory=list)
    aggregation: AggregationDetail | None = None


class P3AggregationCheck(BaseModel):
    """One evaluated aggregation check — serialized for EVERY check
    (consistent and mismatched) so the validator can replay all of them."""

    model_config = ConfigDict(extra="forbid")

    check_id: str  # P3A__<12hex>, content-derived
    project_id: str
    document_id: str
    table_id: str
    page_number: int | None = None
    column: int
    column_header: str = ""
    unit: str | None = None  # canonical column unit spelling
    conversion_factor: str | None = None
    canonical_unit: str | None = None
    total_row: int
    total_label: str | None = None
    direction: str  # above | below | including | mixed_chain | subtotals
    doc_decimal_style: str | None = None
    grouping_styles: list[str] = Field(default_factory=list)
    components: list[AggregationComponent] = Field(default_factory=list)
    expected_total: str  # sum of included components (display units)
    observed_total: str  # stated total (display units)
    abs_diff: str
    rel_diff: str | None = None
    rounding_tolerance: str
    rel_tolerance: str
    decision: Literal["consistent", "mismatch"]
    table_fingerprint: str
    identical_copies: list[str] = Field(default_factory=list)
    finding_id: str | None = None  # set when decision == mismatch


class P3SuppressedSample(BaseModel):
    """Provenance-bearing sample of one suppressed numeric candidate."""

    model_config = ConfigDict(extra="forbid")

    sample_id: str  # P3S__<12hex>, content-derived
    reason: str
    project_id: str
    document_id: str
    source_kind: Literal["section_text", "table_cell"]
    section_id: str | None = None
    table_id: str | None = None
    page_number: int | None = None
    row: int | None = None
    col: int | None = None
    char_start: int | None = None
    raw: str
    context: str  # surrounding normalized text
    detected_unit: str | None = None
    # Parser state at suppression time (decimal style, grouping evidence).
    parser_state: str | None = None
    secondary_reasons: list[str] = Field(default_factory=list)
    extraction_mode: Literal["narrative", "table"] | None = None


class ConfidenceFactor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    factor: str
    delta: float


class P3FindingRecord(BaseModel):
    """P3 finding; field layout mirrors P1's FindingRecord plus comparison
    evidence. Every finding is a POTENTIAL inconsistency for expert review."""

    model_config = ConfigDict(extra="forbid")

    finding_id: str  # P3__<12hex>, content-derived
    pillar_id: str = "P3"
    project_id: str
    document_id: str | None = None  # null => cross-document (package) finding
    finding_type: str
    severity: str  # high | medium | low | info
    priority_score: int = Field(ge=0)
    confidence: float | None = None  # deterministic rubric (see factors)
    confidence_factors: list[ConfidenceFactor] = Field(default_factory=list)
    rule_id: str
    title: str
    explanation: str
    evidence: list[P3Evidence] = Field(default_factory=list)
    page_references: list[int] = Field(default_factory=list)
    mention_ids: list[str] = Field(default_factory=list)
    candidate_id: str | None = None
    comparison: ComparisonDetail | None = None
    semantic_rationale: str = ""
    observed_value: str | None = None
    expected_value: str | None = None
    quality_flags: list[str] = Field(default_factory=list)
    limitations: str
    review_status: str = "pending"


class P3ScoreContribution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: str
    finding_type: str
    severity: str
    points: int


class P3DocumentScoreRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    document_id: str
    document_type: str
    quantitative_consistency_priority_score: int = Field(ge=0, le=100)
    finding_count: int
    contributions: list[P3ScoreContribution] = Field(default_factory=list)
    scoring_config_version: str
    note: str = (
        "Score is a manual-review priority for quantitative consistency;"
        " it is NOT a probability of violation."
    )


class P3ProjectScoreRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    quantitative_consistency_priority_score: int = Field(ge=0, le=100)
    document_scores: dict[str, int] = Field(default_factory=dict)
    package_finding_count: int
    package_contributions: list[P3ScoreContribution] = Field(default_factory=list)
    scoring_config_version: str
    note: str = (
        "Aggregated from document scores plus cross-document findings;"
        " a manual-review priority, NOT a probability of violation."
    )

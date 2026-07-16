"""P4 record schemas: entities, claims, edges, resolution decisions, findings.

Conventions mirror P1/P3 (``FindingRecord`` field names, severity vocabulary,
``review_status``, content-derived IDs), extended with the entity-graph and
provenance structures P4 must carry. Every ID is content-derived and stable;
nothing is serialized with a binary float that participates in an identity.
"""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# --- taxonomies --------------------------------------------------------------
P4_FINDING_TYPES = frozenset(
    {
        "conflicting_project_identity",
        "conflicting_facility_identity",
        "conflicting_location",
        "conflicting_activity_or_category",
        "conflicting_reporting_period",
        "conflicting_operator",
        "unresolved_entity_identity",
        "insufficient_cross_document_context",
        "orphan_document_reference",
    }
)

# Finding types that assert a PROVEN cross-document incompatibility (as opposed
# to a diagnostic about missing linkage / context). Drives the honest
# "no proven contradictions" empty state.
CONFLICT_FINDING_TYPES = frozenset(
    {
        "conflicting_project_identity",
        "conflicting_facility_identity",
        "conflicting_location",
        "conflicting_activity_or_category",
        "conflicting_reporting_period",
        "conflicting_operator",
    }
)

DIAGNOSTIC_FINDING_TYPES = frozenset(
    {
        "unresolved_entity_identity",
        "insufficient_cross_document_context",
        "orphan_document_reference",
    }
)

SEVERITIES = ("high", "medium", "low", "info")

RESOLUTION_DECISIONS = ("merged", "separate", "unresolved", "suppressed")


def deterministic_id(prefix: str, *parts: str) -> str:
    """Content-derived stable id: ``{prefix}__{sha256[:12]}``.

    Never uses Python's randomized ``hash()``; the basis is the canonical
    ``|``-joined UTF-8 byte string of the parts.
    """
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:12]
    return f"{prefix}__{digest}"


class ClaimProvenance(BaseModel):
    """Where an entity claim physically lives in the curated dataset.

    ``document_id``/``document_type`` are ``None`` only for
    ``project_metadata`` claims (grounded in ``projects.jsonl`` rather than in
    a document body)."""

    model_config = ConfigDict(extra="forbid")

    document_id: str | None = None
    document_type: str | None = None
    source_kind: Literal["section_text", "table_cell", "document_metadata", "project_metadata"]
    section_id: str | None = None
    table_id: str | None = None
    page_number: int | None = None
    row: int | None = Field(default=None, ge=0)
    col: int | None = Field(default=None, ge=0)
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)


class EntityClaim(BaseModel):
    """One grounded attribute claim extracted from one document.

    A claim is the atomic evidence unit: it names an attribute of a candidate
    entity, its raw and normalized value, exact provenance and confidence.
    """

    model_config = ConfigDict(extra="forbid")

    claim_id: str  # P4C__<12hex>, content-derived
    project_id: str
    candidate_entity_type: str
    attribute: str  # e.g. name | bin | reporting_period | region | address
    raw_value: str
    normalized_value: str
    provenance: ClaimProvenance
    extraction_method: str  # lexicon rule id that produced the claim
    confidence: float
    scope: str = "package"  # package | document | facility | ...
    qualifiers: list[str] = Field(default_factory=list)  # sorted tags (role, ...)
    quality_flags: list[str] = Field(default_factory=list)  # sorted


class Entity(BaseModel):
    """A resolved (or unresolved) entity with all supporting claims."""

    model_config = ConfigDict(extra="forbid")

    entity_id: str  # P4E__<12hex>, content-derived
    project_id: str
    entity_type: str
    canonical_label: str
    normalized_label: str
    aliases: list[str] = Field(default_factory=list)  # sorted, distinct surface forms
    identifiers: list[str] = Field(default_factory=list)  # sorted explicit identifiers (BIN)
    role: str | None = None  # organization role: operator | designer | unknown
    confidence: float
    claim_ids: list[str] = Field(default_factory=list)  # sorted supporting claims
    source_document_ids: list[str] = Field(default_factory=list)  # sorted
    quality_flags: list[str] = Field(default_factory=list)  # sorted
    limitations: str = ""


class Edge(BaseModel):
    """A lightweight graph edge; JSON only, no external graph database."""

    model_config = ConfigDict(extra="forbid")

    edge_id: str  # P4G__<12hex>, content-derived
    project_id: str
    source_entity_id: str
    target_entity_id: str
    relation: str
    claim_ids: list[str] = Field(default_factory=list)  # supporting claims (sorted)
    confidence: float
    source_document_ids: list[str] = Field(default_factory=list)  # sorted
    limitations: str = ""


class ResolutionDecision(BaseModel):
    """One recorded entity-resolution decision (merge / separate / unresolved /
    suppressed). Every merge carries a reason and the signal that justified it."""

    model_config = ConfigDict(extra="forbid")

    decision_id: str  # P4R__<12hex>, content-derived
    project_id: str
    entity_type: str
    decision: Literal["merged", "separate", "unresolved", "suppressed"]
    entity_ids: list[str] = Field(default_factory=list)  # sorted entities involved
    claim_ids: list[str] = Field(default_factory=list)  # sorted claims involved
    signal: str  # resolution signal (shared_identifier | normalized_name_match | ...)
    reason: str
    confidence: float


class SuppressedComparison(BaseModel):
    """A cross-document comparison deliberately NOT made (identity or scope
    uncertain). Serialized so the honest exclusion is auditable."""

    model_config = ConfigDict(extra="forbid")

    suppression_id: str  # P4S__<12hex>, content-derived
    project_id: str
    check: str  # which cross-document check considered it
    attribute: str
    reason: str
    entity_ids: list[str] = Field(default_factory=list)  # sorted
    claim_ids: list[str] = Field(default_factory=list)  # sorted
    detail: str = ""


class P4Evidence(BaseModel):
    """Same shape as P1/P3 evidence for review-tooling compatibility."""

    model_config = ConfigDict(extra="forbid")

    document_id: str | None = None
    document_type: str | None = None
    page_number: int | None = None
    section_id: str | None = None
    quote: str | None = None
    note: str | None = None


class ConfidenceFactor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    factor: str
    delta: float


class ConflictingClaim(BaseModel):
    """One side of an evidence-backed cross-document mismatch, so the finding is
    independently recomputable from the claims it references."""

    model_config = ConfigDict(extra="forbid")

    claim_id: str
    document_id: str
    attribute: str
    raw_value: str
    normalized_value: str


class PackageCheck(BaseModel):
    """Structured, recomputable package-level check backing an absence/diagnostic
    finding (e.g. operator identity could not be established). It records the
    documents actually inspected, the attributes checked, and how many
    qualifying claims were found — so the finding is auditable from structured
    fields, NOT from a free-text quote that could be fabricated."""

    model_config = ConfigDict(extra="forbid")

    check: str  # e.g. "operator_identity"
    entity_type: str  # e.g. "organization"
    role: str  # e.g. "operator"
    checked_attributes: list[str]  # sorted, e.g. ["bin", "operator_name"]
    inspected_document_ids: list[str]  # sorted, the package documents examined
    qualifying_claims_found: int = Field(ge=0)


class P4FindingRecord(BaseModel):
    """P4 finding; field layout mirrors P1/P3 plus entity-graph references.
    Every finding is a POTENTIAL inconsistency (or diagnostic) for expert
    review — never a legal or administrative conclusion."""

    model_config = ConfigDict(extra="forbid")

    finding_id: str  # P4__<12hex>, content-derived
    pillar_id: str = "P4"
    project_id: str
    document_id: str | None = None  # null => cross-document (package) finding
    finding_type: str
    severity: str  # medium | low | info (never high in this MVP)
    priority_score: int = Field(ge=0)
    confidence: float | None = None  # deterministic rubric (see factors)
    confidence_factors: list[ConfidenceFactor] = Field(default_factory=list)
    rule_id: str
    title: str
    explanation: str
    evidence: list[P4Evidence] = Field(default_factory=list)
    page_references: list[int] = Field(default_factory=list)
    entity_ids: list[str] = Field(default_factory=list)  # sorted
    claim_ids: list[str] = Field(default_factory=list)  # sorted
    edge_ids: list[str] = Field(default_factory=list)  # sorted
    conflicting_claims: list[ConflictingClaim] = Field(default_factory=list)
    package_check: PackageCheck | None = None
    observed_value: str | None = None
    expected_value: str | None = None
    quality_flags: list[str] = Field(default_factory=list)
    limitations: str
    review_status: str = "pending"


class P4ScoreContribution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: str
    finding_type: str
    severity: str
    points: int


class P4DocumentScoreRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    document_id: str
    document_type: str
    cross_document_coherence_priority_score: int = Field(ge=0, le=100)
    finding_count: int
    contributions: list[P4ScoreContribution] = Field(default_factory=list)
    scoring_config_version: str
    note: str = (
        "Score is a manual-review priority for cross-document coherence;"
        " it is NOT a probability of violation, risk or non-compliance."
    )


class P4ProjectScoreRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    cross_document_coherence_priority_score: int = Field(ge=0, le=100)
    document_scores: dict[str, int] = Field(default_factory=dict)
    package_finding_count: int
    package_contributions: list[P4ScoreContribution] = Field(default_factory=list)
    entity_count: int = 0
    edge_count: int = 0
    linked_document_count: int = 0
    unresolved_entity_count: int = 0
    suppressed_comparison_count: int = 0
    scoring_config_version: str
    note: str = (
        "Aggregated from document scores plus cross-document findings;"
        " a manual-review priority, NOT a probability of violation or risk."
    )

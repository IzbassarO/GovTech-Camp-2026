"""P2 record schemas: requirements, evidence, retrievals, assessments,
findings and scores.

Conventions mirror P1/P3 (field names, severity vocabulary,
``review_status``, content-derived IDs). Every P2 output is expert-support
material: labels are cautious (``supported_by_evidence``,
``potential_conflict``, ``insufficient_evidence``, ``not_applicable``) and
never a legal conclusion.
"""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

OBLIGATION_TYPES = (
    "required_document",
    "mandatory_section",
    "quantitative_limit",
    "disclosure_requirement",
    "procedural_requirement",
    "monitoring_requirement",
    "permit_requirement",
    "prohibition",
    "applicability_condition",
    "other",
)

INFERENCE_LABELS = (
    "supported_by_evidence",
    "potential_conflict",
    "insufficient_evidence",
    "not_applicable",
)

APPLICABILITY_STATES = ("applicable", "not_applicable", "unknown")

P2_FINDING_TYPES = frozenset(
    {
        "missing_required_document",
        "missing_required_section",
        "potential_regulatory_conflict",
        "insufficient_regulatory_evidence",
        "applicability_uncertain",
        "outdated_or_unknown_regulation_version",
        "non_authoritative_demo_requirement",
        "malformed_regulatory_source",
    }
)

SEVERITIES = ("high", "medium", "low", "info")


def deterministic_id(prefix: str, *parts: str) -> str:
    """Content-derived stable id: ``{prefix}__{sha256[:12]}`` (P1/P3
    convention; never Python's randomized ``hash()``)."""
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:12]
    return f"{prefix}__{digest}"


def requirement_text_hash(text: str) -> str:
    """Source hash of the exact requirement text (validator replays it)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class RegulatoryRequirement(BaseModel):
    """One requirement-level regulatory record.

    Metadata that is genuinely unknown stays ``None`` — the loader never
    invents document numbers, dates or URLs.
    """

    model_config = ConfigDict(extra="forbid")

    requirement_id: str
    corpus_id: str
    corpus_version: str
    jurisdiction: str
    authority: str
    document_title: str
    document_number: str | None = None
    article: str | None = None
    requirement_text: str
    title: str  # short normalized requirement title
    obligation_type: Literal[
        "required_document",
        "mandatory_section",
        "quantitative_limit",
        "disclosure_requirement",
        "procedural_requirement",
        "monitoring_requirement",
        "permit_requirement",
        "prohibition",
        "applicability_condition",
        "other",
    ]
    # Structured "key:value" applicability tags, e.g. "document_type:ndv",
    # "industry:any", "category:I".
    applicability_tags: list[str] = Field(default_factory=list)
    environmental_topics: list[str] = Field(default_factory=list)
    regulated_activities: list[str] = Field(default_factory=list)
    # Machine-actionable hints for the deterministic baseline:
    # the package document type a required_document demands, and the
    # concept aliases a section/monitoring requirement is matched by.
    required_document_type: str | None = None
    required_concepts: list[str] = Field(default_factory=list)
    effective_from: str | None = None  # ISO date when known
    effective_to: str | None = None
    source_url: str | None = None
    source_file: str | None = None
    source_hash: str  # sha256 of requirement_text (exact preservation)
    is_authoritative: bool
    demo_only: bool
    language: Literal["ru", "kk", "en"]
    notes: str | None = None
    limitations: str | None = None


class ProjectEvidence(BaseModel):
    """One addressable unit of project evidence with provenance."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: str  # P2E__<12hex>, content-derived
    project_id: str
    kind: Literal[
        "document_present",
        "section_heading",
        "text_snippet",
        "project_context",
    ]
    document_id: str | None = None
    document_type: str | None = None
    section_id: str | None = None
    page_number: int | None = None
    text: str  # normalized evidence text (quotes must be substrings)


class RetrievalRecord(BaseModel):
    """One (query, requirement) retrieval decision, fully replayable."""

    model_config = ConfigDict(extra="forbid")

    retrieval_id: str  # P2R__<12hex>
    project_id: str
    query_id: str  # P2Q__<12hex>
    query_kind: Literal["document", "package"]
    query_document_id: str | None = None
    query_text: str
    query_hash: str  # sha256 of the exact query text
    requirement_id: str
    rank: int = Field(ge=1)
    lexical_score: float  # TF-IDF component
    boosts: dict[str, float] = Field(default_factory=dict)
    score: float  # lexical + boosts, rounded
    matched_terms: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    rationale: str


class ConfidenceFactor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    factor: str
    delta: float


class P2Evidence(BaseModel):
    """Same shape as P1/P3 evidence for review-tooling compatibility."""

    model_config = ConfigDict(extra="forbid")

    document_id: str | None = None
    page_number: int | None = None
    quote: str | None = None
    note: str | None = None


class LLMAssessmentResponse(BaseModel):
    """Strict structured response contract for the optional LLM assessor."""

    model_config = ConfigDict(extra="forbid")

    label: Literal[
        "supported_by_evidence",
        "potential_conflict",
        "insufficient_evidence",
        "not_applicable",
    ]
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    evidence_ids: list[str] = Field(default_factory=list)
    evidence_quotes: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    applicability_reasoning: str | None = None
    limitations: str | None = None


class P2Assessment(BaseModel):
    """One (project, requirement) assessment with full provenance."""

    model_config = ConfigDict(extra="forbid")

    assessment_id: str  # P2A__<12hex>, content-derived
    project_id: str
    requirement_id: str
    corpus_id: str
    corpus_version: str
    requirement_is_authoritative: bool
    requirement_demo_only: bool
    retrieval_id: str
    retrieval_score: float
    retrieval_rank: int
    applicability: Literal["applicable", "not_applicable", "unknown"]
    applicability_reasons: list[str] = Field(default_factory=list)
    label: Literal[
        "supported_by_evidence",
        "potential_conflict",
        "insufficient_evidence",
        "not_applicable",
    ]
    confidence: float
    confidence_factors: list[ConfidenceFactor] = Field(default_factory=list)
    inference_engine: Literal["deterministic", "llm", "hybrid"]
    provider_name: str | None = None
    model_name: str | None = None
    prompt_hash: str | None = None
    cached_response_hash: str | None = None
    deterministic_label: str  # baseline label, kept even in hybrid mode
    evidence_ids: list[str] = Field(default_factory=list)
    evidence_snippets: list[P2Evidence] = Field(default_factory=list)
    rationale: str
    missing_information: list[str] = Field(default_factory=list)
    quality_flags: list[str] = Field(default_factory=list)  # sorted
    limitations: str


class P2FindingRecord(BaseModel):
    """P2 finding; layout mirrors P1/P3. Every finding is a REVIEW
    CANDIDATE for a human expert, never a legal conclusion."""

    model_config = ConfigDict(extra="forbid")

    finding_id: str  # P2__<12hex>, content-derived
    pillar_id: str = "P2"
    project_id: str
    document_id: str | None = None  # null => package-level finding
    finding_type: str
    severity: str  # high | medium | low | info
    priority_score: int = Field(ge=0)
    confidence: float | None = None
    confidence_factors: list[ConfidenceFactor] = Field(default_factory=list)
    rule_id: str
    title: str
    explanation: str
    requirement_id: str | None = None
    requirement_source: str | None = None  # document title + article
    requirement_is_authoritative: bool | None = None
    requirement_demo_only: bool | None = None
    assessment_id: str | None = None
    retrieval_score: float | None = None
    inference_label: str | None = None
    inference_engine: str | None = None
    evidence: list[P2Evidence] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    page_references: list[int] = Field(default_factory=list)
    limitations: str
    review_status: str = "pending"


class P2ScoreContribution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: str
    finding_type: str
    severity: str
    points: int


class P2DocumentScoreRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    document_id: str
    document_type: str
    regulatory_compliance_priority_score: int = Field(ge=0, le=100)
    finding_count: int
    contributions: list[P2ScoreContribution] = Field(default_factory=list)
    scoring_config_version: str
    note: str = (
        "Score is a manual-review priority for regulatory evidence;"
        " it is NOT a probability of violation and NOT a legal conclusion."
    )


class P2ProjectScoreRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    regulatory_compliance_priority_score: int = Field(ge=0, le=100)
    document_scores: dict[str, int] = Field(default_factory=dict)
    package_finding_count: int
    package_contributions: list[P2ScoreContribution] = Field(default_factory=list)
    scoring_config_version: str
    note: str = (
        "Aggregated from document scores plus package-level findings;"
        " a manual-review priority, NOT a probability of violation."
    )

"""P5 record schemas: assets, contexts, classifications, clusters, findings.

Conventions mirror P1/P3/P4 (severity vocabulary, content-derived IDs,
``review_status``, required ``limitations``), extended with the visual
provenance and cross-modal structures P5 must carry. Every finding hard-codes
``legal_conclusion = False``: P5 output is review prioritization, never a
legal, administrative or authenticity conclusion.
"""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SEVERITIES = ("high", "medium", "low", "info")

TriageStatus = Literal[
    "analyzed_representative",
    "excluded_duplicate",
    "excluded_low_information",
    "excluded_repeated_header",
    "excluded_logo_or_branding",
    "unsupported",
]

ClusterKind = Literal[
    "exact_duplicate",
    "near_duplicate",
    "repeated_text_header",
    "logo_or_branding",
]

OcrStatus = Literal["completed", "empty", "low_confidence", "failed", "not_run", "unavailable"]

ModelStatus = Literal["available", "unavailable"]

DecisionPath = Literal[
    "deterministic_exclusion",
    "duplicate_resolution",
    "model_zero_shot",
    "context_adjusted",
    "deterministic_supporting",
    "unknown_fallback",
]


def deterministic_id(prefix: str, *parts: str) -> str:
    """Content-derived stable id: ``{prefix}__{sha256[:12]}``."""
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:12]
    return f"{prefix}__{digest}"


class ImageSourceRef(BaseModel):
    """Relative, root-keyed pointer to servable image bytes.

    ``root`` names a directory the consumer resolves safely at serve time
    (``curated`` = the dataset dir; ``workspace`` = the live job workspace).
    Never an absolute path.
    """

    model_config = ConfigDict(extra="forbid")

    root: Literal["curated", "workspace"]
    relative_path: str


class P5AssetRecord(BaseModel):
    """One inventoried visual asset with full provenance."""

    model_config = ConfigDict(extra="forbid")

    asset_id: str  # P5A__<12hex>, content-derived
    project_id: str
    document_id: str
    document_type: str | None = None
    job_id: str | None = None  # live jobs only
    image_id: str
    page_number: int | None = None
    docx_relationship: str | None = None
    bbox: dict[str, float | str] | None = None
    width_px: int | None = Field(default=None, ge=1)
    height_px: int | None = Field(default=None, ge=1)
    media_type: str | None = None
    file_sha256: str | None = None
    perceptual_hash: str | None = None
    perceptual_hash_algorithm: Literal["dhash64"] | None = None
    extraction_origin: str
    extraction_method: str
    provenance_reference: str
    source_reference: str  # e.g. curated:images.jsonl:<line> / direct:<file_id>
    image_source: ImageSourceRef | None = None
    dossier_section: str | None = None
    incoming_triage_state: str | None = None
    display_name_hint: str | None = None
    near_uniform: bool = False
    tiny: bool = False
    triage_status: TriageStatus
    triage_reason: str
    duplicate_cluster_id: str | None = None
    duplicate_of_asset_id: str | None = None
    procedural_supporting_evidence: bool = False
    eligible_for_analysis: bool = False
    limitations: list[str] = Field(default_factory=list)


class P5AssetContext(BaseModel):
    """Cross-modal context assembled for one analyzed representative."""

    model_config = ConfigDict(extra="forbid")

    context_id: str  # P5X__<12hex>
    asset_id: str
    project_id: str
    document_id: str
    page_number: int | None = None
    caption: str | None = None
    caption_source: Literal["page_caption_line", "none"] = "none"
    nearest_heading: str | None = None
    section_id: str | None = None
    page_text_excerpt: str | None = None
    figure_references_on_page: list[str] = Field(default_factory=list)
    entity_terms_matched: list[str] = Field(default_factory=list)  # sorted
    quantitative_mentions_on_page: int = Field(default=0, ge=0)
    ocr_status: OcrStatus = "not_run"
    ocr_engine: str | None = None
    ocr_languages: list[str] = Field(default_factory=list)
    ocr_text: str | None = None
    ocr_mean_confidence: float | None = None
    ocr_failure_reason: str | None = None
    ocr_reused_from_asset_id: str | None = None
    image_caption_similarity: float | None = None
    image_context_similarity: float | None = None
    limitations: list[str] = Field(default_factory=list)


class ClassSimilarity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visual_class: str
    similarity: float  # mean ensemble cosine, rounded
    affinity: float  # softmax share over the label set, rounded


class P5Classification(BaseModel):
    """Final class decision for one analyzed representative.

    ``classification_confidence`` is an honestly named similarity-derived
    label affinity (share of similarity mass over the label set), NOT a
    probability that the label is correct.
    """

    model_config = ConfigDict(extra="forbid")

    classification_id: str  # P5L__<12hex>
    asset_id: str
    project_id: str
    document_id: str
    predicted_class: str
    classification_confidence: float | None = None
    decision_path: DecisionPath
    model_status: ModelStatus
    competing_classes: list[ClassSimilarity] = Field(default_factory=list)
    deterministic_signals: list[str] = Field(default_factory=list)  # sorted
    model_signals: dict[str, float] = Field(default_factory=dict)  # class -> similarity
    context_signals: list[str] = Field(default_factory=list)  # sorted
    limitations: list[str] = Field(default_factory=list)


class P5DuplicateCluster(BaseModel):
    """One duplicate/recurrence cluster with a single analyzed representative."""

    model_config = ConfigDict(extra="forbid")

    cluster_id: str  # P5D__<12hex>
    project_id: str
    kind: ClusterKind
    representative_asset_id: str
    member_asset_ids: list[str]  # sorted, includes the representative
    member_count: int = Field(ge=1)
    document_ids: list[str]  # sorted
    page_numbers: list[int] = Field(default_factory=list)  # sorted, distinct
    exact_sha256_values: list[str] = Field(default_factory=list)  # sorted, distinct
    linking_evidence: list[str] = Field(default_factory=list)  # sorted rule tags
    exclusion_reason: str
    repeated_ocr_text: str | None = None


class P5Evidence(BaseModel):
    """Evidence reference: visual asset, caption, page text or OCR text."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["visual_asset", "caption", "page_text", "ocr_text", "note"]
    document_id: str | None = None
    document_type: str | None = None
    page_number: int | None = None
    section_id: str | None = None
    asset_id: str | None = None
    quote: str | None = None
    note: str | None = None


class ConfidenceFactor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    factor: str
    delta: float


class P5FindingRecord(BaseModel):
    """P5 finding; layout mirrors P1/P3/P4 plus visual-evidence references.

    Every finding is a review cue for an expert — never a legal conclusion,
    an environmental-harm claim or an authenticity verdict.
    """

    model_config = ConfigDict(extra="forbid")

    finding_id: str  # P5__<12hex>, content-derived
    pillar_id: str = "P5"
    project_id: str
    document_id: str | None = None  # null => package-level (cross-document)
    asset_id: str | None = None  # primary visual asset
    related_asset_ids: list[str] = Field(default_factory=list)  # sorted
    page_number: int | None = None
    finding_type: str
    severity: str  # medium | low | info (never high)
    priority_score: int = Field(ge=0)
    confidence: float | None = None
    confidence_factors: list[ConfidenceFactor] = Field(default_factory=list)
    rule_id: str
    title: str
    explanation: str
    evidence: list[P5Evidence] = Field(default_factory=list)
    duplicate_cluster_id: str | None = None
    deterministic_signals: list[str] = Field(default_factory=list)  # sorted
    model_signals: dict[str, float] = Field(default_factory=dict)
    context_signals: list[str] = Field(default_factory=list)  # sorted
    quality_flags: list[str] = Field(default_factory=list)  # sorted
    limitations: str
    expert_review_recommended: bool = True
    legal_conclusion: Literal[False] = False
    review_status: str = "pending"


class P5Suppression(BaseModel):
    """A check deliberately NOT applied (insufficient evidence quality)."""

    model_config = ConfigDict(extra="forbid")

    suppression_id: str  # P5S__<12hex>
    project_id: str
    check: str
    asset_id: str | None = None
    document_id: str | None = None
    reason: str
    detail: str = ""


class P5ScoreContribution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: str
    finding_type: str
    severity: str
    points: int


class P5DocumentScoreRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    document_id: str
    document_type: str | None = None
    visual_evidence_review_priority_score: int = Field(ge=0, le=100)
    finding_count: int
    asset_count: int = Field(ge=0)
    analyzed_representative_count: int = Field(ge=0)
    excluded_duplicate_count: int = Field(ge=0)
    contributions: list[P5ScoreContribution] = Field(default_factory=list)
    scoring_config_version: str
    note: str


class P5ProjectScoreRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    visual_evidence_review_priority_score: int = Field(ge=0, le=100)
    document_scores: dict[str, int] = Field(default_factory=dict)
    package_finding_count: int = Field(ge=0)
    package_contributions: list[P5ScoreContribution] = Field(default_factory=list)
    total_asset_count: int = Field(ge=0)
    assets_with_bytes_count: int = Field(ge=0)
    eligible_asset_count: int = Field(ge=0)
    analyzed_representative_count: int = Field(ge=0)
    excluded_duplicate_count: int = Field(ge=0)
    excluded_low_information_count: int = Field(ge=0)
    excluded_header_or_logo_count: int = Field(ge=0)
    unsupported_asset_count: int = Field(ge=0)
    procedural_asset_count: int = Field(ge=0)
    duplicate_cluster_count: int = Field(ge=0)
    visual_coverage: float | None = None  # analyzed / eligible, rounded 3
    assessment_confidence: float
    confidence_components: dict[str, float] = Field(default_factory=dict)
    model_status: ModelStatus
    meta_integration_status: str
    scoring_config_version: str
    note: str

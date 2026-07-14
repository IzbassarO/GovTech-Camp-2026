"""P1 finding and score record schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

FINDING_TYPES = frozenset(
    {
        "missing_document",
        "missing_expected_section",
        "empty_page",
        "low_text_coverage",
        "high_ocr_dependency",
        "missing_expected_tables",
        "duplicate_heading",
        "suspicious_document_length",
        "metadata_inconsistency",
        "date_range_inconsistency",
        "missing_appendix_reference",
        "structural_anomaly",
    }
)


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str | None = None
    page_number: int | None = None
    quote: str | None = None
    note: str | None = None


class FindingRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: str
    pillar_id: str = "P1"
    project_id: str
    document_id: str | None = None  # null => package-level finding
    finding_type: str
    severity: str  # high | medium | low | info
    priority_score: int = Field(ge=0)  # contribution points of this finding
    confidence: float | None = None  # deterministic baseline: always null
    rule_id: str
    title: str
    explanation: str
    evidence: list[Evidence] = Field(default_factory=list)
    page_references: list[int] = Field(default_factory=list)
    observed_value: str | None = None
    expected_value: str | None = None
    limitations: str
    review_status: str = "pending"


class ScoreContribution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: str
    finding_type: str
    severity: str
    points: int


class DocumentScoreRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    document_id: str
    document_type: str
    document_integrity_priority_score: int = Field(ge=0, le=100)
    finding_count: int
    contributions: list[ScoreContribution] = Field(default_factory=list)
    scoring_config_version: str
    note: str = (
        "Score is a manual-review priority for document structure;"
        " it is NOT a probability of violation."
    )


class ProjectScoreRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    document_integrity_priority_score: int = Field(ge=0, le=100)
    document_scores: dict[str, int] = Field(default_factory=dict)
    package_finding_count: int
    package_contributions: list[ScoreContribution] = Field(default_factory=list)
    scoring_config_version: str
    note: str = (
        "Aggregated from document scores plus package-level findings;"
        " a manual-review priority, NOT a probability of violation."
    )

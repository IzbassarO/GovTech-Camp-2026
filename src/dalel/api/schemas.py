"""API response contracts.

These are the STABLE shapes the frontend depends on. They are normalized
away from the on-disk pillar artifacts so that:

- adding a future pillar (P4/P5/P6, meta-risk) requires no shape change;
- optional future fields (calibrated_risk, model_score, graph, map,
  provider metadata) are reserved as ``None`` and never fabricated.

Nothing here carries filesystem paths, secrets or Python object dumps.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

Severity = str  # "high" | "medium" | "low" | "info"


class SeverityCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    high: int = 0
    medium: int = 0
    low: int = 0
    info: int = 0

    @property
    def total(self) -> int:
        return self.high + self.medium + self.low + self.info


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    api_version: str
    projects_available: int
    pillars_available: list[str]
    data_ready: bool


class PillarSummary(BaseModel):
    """Generic, forward-compatible per-project pillar summary."""

    model_config = ConfigDict(extra="forbid")

    pillar_id: str
    key: str
    title: str
    short_title: str
    description: str
    status: str  # "clear" | "attention" | "info" | "unavailable"
    available: bool
    implemented: bool
    is_demo: bool
    is_authoritative: bool
    finding_count: int
    severity_counts: SeverityCounts
    score: int | None = None
    score_label: str | None = None
    score_max: int = 100
    headline: str  # one-line human summary for the card
    empty_state: str | None = None  # honest positive empty message
    warning: str | None = None  # e.g. P2 synthetic-corpus notice
    limitations: str | None = None
    metrics: list[MetricItem] = Field(default_factory=list)

    # --- reserved for future pillars; never fabricated ---
    calibrated_risk: float | None = None
    model_score: float | None = None
    shap_contributions: list[dict[str, float]] | None = None
    graph: dict[str, object] | None = None
    map: dict[str, object] | None = None
    provider: dict[str, str] | None = None


class MetricItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    value: str
    hint: str | None = None


class ReservedPillar(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pillar_id: str
    key: str
    title: str
    description: str
    available: bool = False
    status: str = "planned"


class DocumentInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    document_type: str
    page_count: int | None = None
    languages: list[str] = Field(default_factory=list)
    document_mode: str | None = None
    source_url: str | None = None
    finding_counts: SeverityCounts = Field(default_factory=SeverityCounts)


class ProjectListItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    name: str
    region: str | None = None
    industry: str | None = None
    document_count: int
    findings_total: int
    severity_counts: SeverityCounts
    pillar_finding_counts: dict[str, int]  # key -> count
    has_demo_pillar: bool
    dataset_version: str


class ProjectDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    name: str
    region: str | None = None
    industry: str | None = None
    source_url: str | None = None
    dataset_version: str
    document_count: int
    documents: list[DocumentInfo]
    findings_total: int
    severity_counts: SeverityCounts


class ProjectSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    name: str
    region: str | None = None
    industry: str | None = None
    document_count: int
    findings_total: int
    severity_counts: SeverityCounts
    pillars: list[PillarSummary]
    reserved_pillars: list[ReservedPillar]
    integrated_risk_available: bool = False
    integrated_risk_note: str


class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str | None = None
    document_type: str | None = None
    page_number: int | None = None
    section_id: str | None = None
    quote: str | None = None
    note: str | None = None


class RequirementRef(BaseModel):
    """P2 regulatory requirement context attached to a finding."""

    model_config = ConfigDict(extra="forbid")

    requirement_id: str
    title: str
    requirement_text: str
    document_title: str
    article: str | None = None
    obligation_type: str
    is_authoritative: bool
    demo_only: bool
    source_url: str | None = None


class QuantitativeDetail(BaseModel):
    """P3 comparison context; reserved shape (production P3 has 0 findings)."""

    model_config = ConfigDict(extra="forbid")

    formula: str | None = None
    raw_values: list[str] = Field(default_factory=list)
    normalized_values: list[str] = Field(default_factory=list)
    canonical_unit: str | None = None


class FindingListItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: str
    pillar_id: str
    pillar_key: str
    project_id: str
    document_id: str | None = None
    document_type: str | None = None
    finding_type: str
    finding_type_label: str
    severity: Severity
    confidence: float | None = None
    title: str
    rule_id: str | None = None
    review_status: str
    page_references: list[int] = Field(default_factory=list)
    is_demo: bool = False
    # None for non-regulatory pillars (P1/P3); False for demo P2 findings.
    is_authoritative: bool | None = None
    inference_label: str | None = None
    requirement_id: str | None = None


class FindingDetail(FindingListItem):
    model_config = ConfigDict(extra="forbid")

    explanation: str
    observed_value: str | None = None
    expected_value: str | None = None
    limitations: str | None = None
    evidence: list[EvidenceItem] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    applicability: str | None = None
    retrieval_score: float | None = None
    inference_engine: str | None = None
    requirement: RequirementRef | None = None
    quantitative: QuantitativeDetail | None = None
    demo_warning: str | None = None
    review_notice: str


class FindingsPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    total: int
    returned: int
    severity_counts: SeverityCounts
    available_filters: FindingFilters
    findings: list[FindingListItem]


class FindingFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pillars: list[str]
    severities: list[str]
    finding_types: list[FilterOption]
    documents: list[FilterOption]


class FilterOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str
    label: str
    count: int


class ReportResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    pillar: str
    title: str
    format: str  # "markdown"
    content: str
    is_demo: bool
    generated_note: str


class SystemMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_version: str
    dataset_version: str
    dataset_fingerprint: str | None = None
    projects: int
    documents: int
    findings_total: int
    findings_by_pillar: dict[str, int]
    severity_counts: SeverityCounts
    pillars: list[dict[str, object]]


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: str
    detail: str


# Resolve forward references for models that reference later definitions.
PillarSummary.model_rebuild()
FindingsPage.model_rebuild()

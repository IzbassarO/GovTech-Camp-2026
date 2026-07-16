// API contract types. Mirror src/dalel/api/schemas.py. The Meta contract is
// deliberately separate from findings: it ranks packages for expert review,
// but does not claim a probability of violation or a legal conclusion.

export type Severity = "high" | "medium" | "low" | "info";

export interface SeverityCounts {
  high: number;
  medium: number;
  low: number;
  info: number;
}

export type ReviewPriorityLevel = "low" | "moderate" | "elevated" | "high";

export interface MetaFeatureContribution {
  contribution_id: string;
  feature_id: string;
  feature_name: string;
  pillar_id: string;
  raw_value: number | boolean | string | null;
  normalized_value: number;
  weight: number;
  raw_contribution: number;
  contribution: number;
  source_artifact_ids: string[];
  source_finding_ids: string[];
  explanation: string;
  limitations: string[];
  adjustments: string[];
}

export interface MetaPillarContribution {
  contribution_id: string;
  pillar_id: string;
  available: boolean;
  raw_subtotal: number;
  adjusted_subtotal: number;
  discount_factor: number;
  cap_applied: boolean;
  discount_applied: boolean;
  cap_amount: number;
  discount_amount: number;
  cap: number;
  evidence_coverage: number;
  assessment_confidence: number;
  feature_contribution_ids: string[];
  explanation: string;
  limitations: string[];
}

export interface MetaAdjustment {
  name: string;
  amount: number;
  explanation: string;
  pillar_id: string | null;
  adjustment_id: string | null;
  adjustment_type: string | null;
  applied: boolean;
  config_key: string | null;
}

export interface ProjectMetaAssessment {
  assessment_id: string;
  project_id: string;
  meta_version: string;
  primary_label: string;
  review_priority_score: number;
  review_priority_level: ReviewPriorityLevel;
  base_score: number;
  raw_feature_total: number;
  uncertainty_adjustment: number;
  global_cap_adjustment: number;
  final_score: number;
  evidence_coverage: number;
  assessment_confidence: number;
  pillar_contributions: MetaPillarContribution[];
  feature_contributions: MetaFeatureContribution[];
  top_positive_factors: MetaFeatureContribution[];
  caps_applied: MetaAdjustment[];
  discounts_applied: MetaAdjustment[];
  uncertainty_adjustments: MetaAdjustment[];
  available_pillars: string[];
  missing_pillars: string[];
  limitations: string[];
  counterfactual_explanation: string;
  calibration_status: string;
  calibrated_probability: number | null;
  shap_contributions: Array<Record<string, number>> | null;
  experimental_test_only: boolean;
  scoring_config_version: string | null;
  review_notice: string;
}

export interface HealthResponse {
  status: string;
  api_version: string;
  projects_available: number;
  pillars_available: string[];
  meta_available: boolean;
  data_ready: boolean;
}

export interface MetricItem {
  label: string;
  value: string;
  hint: string | null;
}

export interface PillarSummary {
  pillar_id: string;
  key: string;
  title: string;
  short_title: string;
  description: string;
  status: "clear" | "attention" | "info" | "unavailable";
  available: boolean;
  implemented: boolean;
  is_demo: boolean;
  is_authoritative: boolean;
  finding_count: number;
  severity_counts: SeverityCounts;
  score: number | null;
  score_label: string | null;
  score_max: number;
  headline: string;
  empty_state: string | null;
  warning: string | null;
  limitations: string | null;
  metrics: MetricItem[];
  // P4 cross-document coherence (populated only when P4 is available).
  entity_count: number | null;
  edge_count: number | null;
  linked_document_count: number | null;
  unresolved_entity_count: number | null;
  suppressed_comparison_count: number | null;
  calibrated_risk: number | null;
  model_score: number | null;
  shap_contributions: unknown[] | null;
  // P4 populates `graph` with the compact coherence view; `map` stays reserved
  // for the later spatial/cartographic phase (P5/P6).
  graph: CoherenceGraph | null;
  map: unknown | null;
  provider: Record<string, string> | null;
}

export interface P4NotableEntity {
  entity_id: string;
  entity_type: string;
  entity_type_label: string;
  label: string;
  role: string | null;
  role_label: string | null;
  identifiers: string[];
  aliases: string[];
  document_count: number;
  confidence: number | null;
}

export interface P4Relationship {
  relation: string;
  relation_label: string;
  source_label: string;
  target_label: string;
  target_type: string;
  document_ids: string[];
}

export interface P4ConfirmedLink {
  entity_type: string;
  entity_type_label: string;
  signal: string;
  reason: string;
  confidence: number | null;
}

export interface P4UnresolvedLink {
  entity_type: string;
  reason: string;
}

export interface P4SuppressedItem {
  reason: string;
  count: number;
  detail: string;
}

export interface CoherenceGraph {
  proven_conflicts: number;
  entities_by_type: Record<string, number>;
  emission_source_count: number;
  notable_entities: P4NotableEntity[];
  relationships: P4Relationship[];
  confirmed_links: P4ConfirmedLink[];
  unresolved_links: P4UnresolvedLink[];
  suppressed: P4SuppressedItem[];
}

export interface EntityRef {
  entity_id: string;
  entity_type: string;
  label: string;
  role: string | null;
  identifiers: string[];
}

export interface ConflictingClaimRef {
  document_id: string;
  document_type: string | null;
  attribute: string;
  raw_value: string;
  normalized_value: string;
}

export interface CoherenceDetail {
  entities: EntityRef[];
  conflicting_claims: ConflictingClaimRef[];
}

export interface ReservedPillar {
  pillar_id: string;
  key: string;
  title: string;
  description: string;
  available: boolean;
  status: string;
}

export interface DocumentInfo {
  document_id: string;
  document_type: string;
  page_count: number | null;
  languages: string[];
  document_mode: string | null;
  source_url: string | null;
  finding_counts: SeverityCounts;
}

export interface ProjectListItem {
  project_id: string;
  name: string;
  region: string | null;
  industry: string | null;
  document_count: number;
  findings_total: number;
  severity_counts: SeverityCounts;
  pillar_finding_counts: Record<string, number>;
  has_demo_pillar: boolean;
  dataset_version: string;
  meta: ProjectMetaAssessment | null;
}

export interface ProjectDetail {
  project_id: string;
  name: string;
  region: string | null;
  industry: string | null;
  source_url: string | null;
  dataset_version: string;
  document_count: number;
  documents: DocumentInfo[];
  findings_total: number;
  severity_counts: SeverityCounts;
  meta: ProjectMetaAssessment | null;
}

export interface ProjectSummary {
  project_id: string;
  name: string;
  region: string | null;
  industry: string | null;
  document_count: number;
  findings_total: number;
  severity_counts: SeverityCounts;
  pillars: PillarSummary[];
  reserved_pillars: ReservedPillar[];
  meta: ProjectMetaAssessment | null;
  meta_available: boolean;
  // Deprecated compatibility fields from the pre-Meta API.
  integrated_risk_available: boolean;
  integrated_risk_note: string;
}

export interface EvidenceItem {
  document_id: string | null;
  document_type: string | null;
  page_number: number | null;
  section_id: string | null;
  quote: string | null;
  note: string | null;
}

export interface RequirementRef {
  requirement_id: string;
  title: string;
  requirement_text: string;
  document_title: string;
  article: string | null;
  obligation_type: string;
  is_authoritative: boolean;
  demo_only: boolean;
  source_url: string | null;
}

export interface QuantitativeDetail {
  formula: string | null;
  raw_values: string[];
  normalized_values: string[];
  canonical_unit: string | null;
}

export interface FindingListItem {
  finding_id: string;
  pillar_id: string;
  pillar_key: string;
  project_id: string;
  document_id: string | null;
  document_type: string | null;
  finding_type: string;
  finding_type_label: string;
  severity: Severity;
  confidence: number | null;
  title: string;
  rule_id: string | null;
  review_status: string;
  page_references: number[];
  is_demo: boolean;
  inference_label: string | null;
  requirement_id: string | null;
}

export interface FindingDetail extends FindingListItem {
  explanation: string;
  observed_value: string | null;
  expected_value: string | null;
  limitations: string | null;
  evidence: EvidenceItem[];
  missing_information: string[];
  applicability: string | null;
  retrieval_score: number | null;
  inference_engine: string | null;
  requirement: RequirementRef | null;
  quantitative: QuantitativeDetail | null;
  coherence: CoherenceDetail | null;
  demo_warning: string | null;
  review_notice: string;
}

export interface FilterOption {
  value: string;
  label: string;
  count: number;
}

export interface FindingFilters {
  pillars: string[];
  severities: string[];
  finding_types: FilterOption[];
  documents: FilterOption[];
}

export interface FindingsPage {
  project_id: string;
  total: number;
  returned: number;
  severity_counts: SeverityCounts;
  available_filters: FindingFilters;
  findings: FindingListItem[];
}

export interface SystemMetrics {
  api_version: string;
  dataset_version: string;
  dataset_fingerprint: string | null;
  projects: number;
  documents: number;
  findings_total: number;
  findings_by_pillar: Record<string, number>;
  severity_counts: SeverityCounts;
  pillars: Array<Record<string, unknown>>;
  meta_available: boolean;
  meta_projects_assessed: number;
  meta_metrics: Record<string, unknown> | null;
}

export interface ReportResponse {
  project_id: string;
  pillar: string;
  title: string;
  format: string;
  content: string;
  is_demo: boolean;
  generated_note: string;
}

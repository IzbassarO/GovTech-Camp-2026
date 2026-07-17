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

// --- structured dossier demo: sections -> animated analysis -> result --------
// Mirrors src/dalel/api/dossier.py + src/dalel/api/demo.py. The dossier layer
// reconciles the FULL official source package (including files that exist
// only on the official portal) against the curated dataset and P1–P4/Meta
// artifacts, so every file carries an honest, COMPUTED processing state.
// Every stage metric is read from the accepted artifacts; this is a
// "Prepared Demo Replay", never a claim that arbitrary uploaded files
// produced these results.

export type PreparedDossierSectionId =
  | "project_documents"
  | "media_publication"
  | "notice_boards"
  | "hearing_protocol"
  | "public_feedback";

export type LiveDossierSectionId =
  | "project_documents"
  | "official_supporting_documents"
  | "hearing_protocol"
  | "procedural_publication_evidence"
  | "visual_geographic_materials"
  | "public_feedback_metadata";

export type DossierSectionId = PreparedDossierSectionId | LiveDossierSectionId;

export type RequirementLevel =
  | "required"
  | "conditionally_required"
  | "recommended"
  | "optional"
  | "external_source";

export type SourceOrigin = "official_portal" | "local_raw" | "extracted_archive" | "user_upload";

export type ArchiveStatus =
  | "not_archive"
  | "registered"
  | "extracted"
  | "extraction_unsupported"
  | "extraction_failed";

export type ReconciledStatus =
  | "analyzed"
  | "curated"
  | "supporting_only"
  | "extracted"
  | "available_raw"
  | "official_only"
  | "unavailable"
  | "unsupported_archive"
  | "excluded_with_reason";

export interface DossierSectionDefinition {
  section_id: DossierSectionId;
  order: number;
  title_ru: string;
  purpose: string;
  requirement_level: RequirementLevel;
  requirement_label: string;
  accepted_formats: string[];
  multiplicity_label: string;
  min_expected_files: number;
  upload_enabled: boolean;
  pillar_relevance: string[];
  future_pillar: string | null;
}

export interface DossierSchemaResponse {
  schema_version: string;
  sections: DossierSectionDefinition[];
}

export interface DossierDocument {
  document_id: string;
  curated_document_id: string | null;
  section_id: DossierSectionId;
  official_category: string | null;
  safe_display_name: string;
  original_name: string | null;
  subtype: string | null;
  subtype_label: string | null;
  media_type: string;
  size_label: string | null;
  source_origin: SourceOrigin;
  official_source_registered: boolean;
  local_available: boolean;
  archive_status: ArchiveStatus;
  extracted_from: string | null;
  text_extracted: boolean;
  page_count: number | null;
  curated: boolean;
  analyzed_by: string[];
  meta_evidence: boolean;
  registered_label_source: boolean;
  supporting_evidence_only: boolean;
  reconciled_status: ReconciledStatus;
  status_label: string;
  missing_reason: string | null;
  provenance_reference: string | null;
  limitations: string[];
  eligible_for_p5: boolean;
  visual_media_type: string | null;
  visual_analysis_status: "not_available";
}

export interface DossierSectionStatus {
  total: number;
  official_registered: number;
  local_available: number;
  analyzed: number;
  supporting: number;
  official_only: number;
  user_supplied: number;
  coverage_state:
    | "included_in_analysis"
    | "local_materials"
    | "official_only"
    | "external_registered"
    | "empty";
  status_note: string;
}

export interface DossierSectionView {
  definition: DossierSectionDefinition;
  status: DossierSectionStatus;
  documents: DossierDocument[];
}

export interface PackageCompleteness {
  heading: string;
  official_registered_total: number;
  locally_available_total: number;
  extracted_total: number;
  analyzed_total: number;
  supporting_total: number;
  official_only_total: number;
  user_supplied_total: number;
  sections_total: number;
  sections_with_materials: number;
}

export interface AnalysisCoverageRecord {
  document_id: string;
  safe_display_name: string;
  section_id: DossierSectionId;
  section_title: string;
  prepared: boolean;
  p1: boolean;
  p2: boolean;
  p3: boolean;
  p4: boolean;
  meta_evidence: boolean;
  limitation: string | null;
}

export interface PublicFeedbackSummary {
  registered_in_official_source: boolean;
  official_heading: string | null;
  submission_count: number;
  question_count: number;
  responses_status_label: string;
  submitted_at_label: string | null;
  provenance_reference: string | null;
  included_in_analysis: boolean;
  feeds_pillars: string[];
  note: string;
}

export interface DossierProjectIdentity {
  project_id: string;
  display_name: string;
  official_title: string | null;
  hearing_registration_number: string | null;
  project_type_label: string | null;
  region_label: string | null;
  initiator_type_label: string | null;
  hearing_method_label: string | null;
  hearing_period_label: string | null;
  portal_name: string | null;
  source_url: string | null;
  official_source_verified_at: string | null;
  location_reference_status: string;
  geospatial_analysis_status: string;
  eligible_for_p6: boolean;
}

export interface DossierManifestResponse {
  demo_project_id: string;
  project_name: string;
  manifest_version: string;
  prepared: boolean;
  identity: DossierProjectIdentity;
  sections: DossierSectionView[];
  public_feedback: PublicFeedbackSummary | null;
  completeness: PackageCompleteness;
  coverage_matrix: AnalysisCoverageRecord[];
  limitations: string[];
}

export interface DemoJobRequest {
  mode: "prepared_replay";
}

export interface DemoStageMetric {
  label: string;
  value: string;
  hint: string | null;
  technical_id: string | null;
}

export interface DemoStage {
  stage_id: string;
  pillar_id: string | null;
  title: string;
  status_messages: string[];
  headline: string;
  inputs: string[];
  input_note: string | null;
  operation: string | null;
  metrics: DemoStageMetric[];
  warning: string | null;
  empty_state: string | null;
  limitations: string | null;
}

export interface DemoJobResponse {
  job_id: string;
  project_id: string;
  project_name: string;
  status: "completed";
  mode: "prepared_replay";
  disclaimer: string;
  analysis_scope_note: string;
  dossier: DossierManifestResponse;
  registered_source_count: number;
  locally_available_count: number;
  analyzed_count: number;
  uploaded_file_count: number;
  uploaded_total_size_label: string;
  stages: DemoStage[];
  generated_explanation: string | null;
  generation_status: "not_available";
  limitations: string[];
  result_url: string;
}

/** Returned only once, when a protected prepared-replay job is created. */
export interface DemoJobCreateResponse extends DemoJobResponse {
  access_token: string;
}

// --- live analysis ------------------------------------------------------------

export type LiveJobStatus =
  | "created"
  | "receiving"
  | "validating"
  | "preparing"
  | "running_p1"
  | "running_p2"
  | "running_p3"
  | "running_p4"
  | "running_p5"
  | "running_meta"
  | "completed"
  | "failed"
  | "cancelled"
  | "expired";

export type LiveStageStatus =
  | "pending"
  | "running"
  | "completed"
  | "unavailable"
  | "insufficient_input"
  | "failed"
  | "cancelled";

export interface LivePackageLimits {
  max_file_count: number;
  max_file_bytes: number;
  max_total_bytes: number;
  max_archive_files: number;
  max_archive_expanded_bytes: number;
  max_archive_ratio: number;
  job_ttl_seconds: number;
  max_active_jobs: number;
}

export interface LiveDossierSectionDefinition {
  section_id: LiveDossierSectionId;
  order: number;
  title_ru: string;
  accepted_formats: string[];
  upload_enabled: boolean;
}

export interface LiveDossierSchemaResponse {
  mode: "live_analysis";
  sections: LiveDossierSectionDefinition[];
  limits: LivePackageLimits;
  visual_analysis_status: "not_available";
  geospatial_analysis_status: "not_available";
  generated_explanation: null;
  generation_status: "not_available";
}

export interface LiveSectionAssignment {
  section_id: LiveDossierSectionId;
  upload_indices: number[];
}

export interface LivePublicFeedbackInput {
  submission_count: number;
  question_count: number;
  note?: string | null;
}

export interface LiveJobRequestPayload {
  mode: "live_analysis";
  project_display_name?: string | null;
  sections: LiveSectionAssignment[];
  public_feedback?: LivePublicFeedbackInput;
}

export interface LiveJobEvent {
  sequence: number;
  state: LiveJobStatus;
  progress: number;
  operation: string;
  metrics: Record<string, unknown> | null;
  warnings: string[];
  limitations: string[];
}

export interface LiveJobEventsResponse {
  job_id: string;
  status: LiveJobStatus;
  events: LiveJobEvent[];
}

export interface LiveStageProgress {
  stage_id: string;
  pillar_id: string | null;
  title: string;
  status: LiveStageStatus;
  operation: string | null;
  progress: number;
  metrics: DemoStageMetric[];
  warnings: string[];
  limitations: string[];
  reason: string | null;
}

export interface LiveFileResponse {
  file_id: string;
  section_id: LiveDossierSectionId;
  display_filename: string;
  media_type: "pdf" | "docx" | "zip" | "rar" | "jpg" | "png";
  size_bytes: number;
  sha256: string;
  duplicate_of: string | null;
  archive_status: ArchiveStatus;
}

export interface LivePreparationSummary {
  document_count: number;
  prepared_document_count: number;
  page_count: number;
  extracted_visual_asset_count: number;
  extraction_failure_count: number;
}

export interface LivePillarResult {
  pillar_id?: string;
  status: "completed" | "unavailable" | "insufficient_input" | "failed";
  reason?: string | null;
  coverage?: number | null;
  assessment_confidence?: number | null;
  metrics?: Record<string, string | number | boolean | null>;
  warnings?: string[];
  limitations?: string[];
}

export interface LiveResultInventory {
  expected_sections: LiveDossierSectionId[];
  supplied_sections: LiveDossierSectionId[];
  missing_sections: LiveDossierSectionId[];
  unsupported_materials: string[];
  duplicate_files: string[];
  package_readiness: string;
  files: unknown[];
  public_feedback: Record<string, unknown> | null;
}

export interface LiveAnalysisResultPayload {
  [key: string]: unknown;
  schema_version?: string;
  mode?: "live_analysis";
  project_id?: string;
  project_name?: string;
  inventory?: LiveResultInventory;
  preparation?: LivePreparationSummary;
  stages?: LiveStageProgress[];
  pillars?: Partial<Record<"P1" | "P2" | "P3" | "P4", LivePillarResult>> & {
    P5?: LiveP5Result;
  };
  meta?: ProjectMetaAssessment | null;
  warnings?: string[];
  limitations?: string[];
}

export interface LiveJobResponse {
  job_id: string;
  project_id: string;
  project_display_name: string;
  mode: "live_analysis";
  status: LiveJobStatus;
  progress: number;
  current_operation: string;
  file_count: number;
  total_size_bytes: number;
  files: LiveFileResponse[];
  result: LiveAnalysisResultPayload | null;
  failure_code: string | null;
  limitations: string[];
  visual_analysis_status: string;
  geospatial_analysis_status: "not_available";
  generated_explanation: null;
  generation_status: "not_available";
}

export interface LiveJobCreateResponse extends LiveJobResponse {
  access_token: string;
}

// --- P5 multimodal visual evidence -------------------------------------------

export interface P5Summary {
  total_asset_count: number;
  assets_with_bytes_count: number;
  eligible_asset_count: number;
  analyzed_representative_count: number;
  excluded_duplicate_count: number;
  excluded_low_information_count: number;
  excluded_header_or_logo_count: number;
  unsupported_asset_count: number;
  procedural_asset_count: number;
  duplicate_cluster_count: number;
  findings_count: number;
  review_priority: number;
  visual_coverage: number | null;
  assessment_confidence: number | null;
  model_status: string;
}

export interface P5ProjectResponse {
  project_id: string;
  available: boolean;
  status_reason: string | null;
  title: string;
  score_label: string;
  summary: P5Summary | null;
  classifications_by_class: Record<string, number>;
  findings_by_severity: Record<string, number>;
  model_metadata: Record<string, unknown>;
  meta_integration_status: string;
  meta_integration_notice: string;
  limitations: string[];
}

export type P5GalleryGroup =
  | "maps"
  | "site_photos"
  | "diagrams"
  | "charts_tables"
  | "procedural"
  | "excluded_duplicates"
  | "excluded_other"
  | "unknown";

export interface P5AssetView {
  asset_id: string;
  document_id: string;
  document_type: string | null;
  image_id: string;
  page_number: number | null;
  width_px: number | null;
  height_px: number | null;
  triage_status: string;
  triage_reason: string;
  predicted_class: string | null;
  classification_confidence: number | null;
  decision_path: string | null;
  gallery_group: P5GalleryGroup | string;
  duplicate_cluster_id: string | null;
  duplicate_of_asset_id: string | null;
  procedural_supporting_evidence: boolean;
  eligible_for_analysis: boolean;
  caption: string | null;
  thumbnail_available: boolean;
}

export interface P5ClusterView {
  cluster_id: string;
  kind: string;
  representative_asset_id: string;
  member_count: number;
  document_ids: string[];
  page_numbers: number[];
  exclusion_reason: string;
  repeated_ocr_text: string | null;
  linking_evidence: string[];
}

export interface P5AssetsResponse {
  project_id: string;
  assets: P5AssetView[];
  clusters: P5ClusterView[];
}

export interface P5AssetDetailResponse {
  project_id: string;
  asset: Record<string, unknown>;
  context: Record<string, unknown> | null;
  classification: Record<string, unknown> | null;
  cluster: Record<string, unknown> | null;
  findings: Array<Record<string, unknown>>;
  thumbnail_available: boolean;
}

/** Live P5 payload: the pillar result plus full job-local P5 artifacts. */
export interface LiveP5Result extends LivePillarResult {
  meta_integration_status?: string;
  summary?: P5Summary & { review_priority?: number };
  assets?: Array<Record<string, unknown>>;
  asset_contexts?: Array<Record<string, unknown>>;
  classifications?: Array<Record<string, unknown>>;
  duplicate_clusters?: Array<Record<string, unknown>>;
  findings?: Array<Record<string, unknown>>;
  suppressions?: Array<Record<string, unknown>>;
  document_scores?: Array<Record<string, unknown>>;
  project_scores?: Array<Record<string, unknown>>;
}

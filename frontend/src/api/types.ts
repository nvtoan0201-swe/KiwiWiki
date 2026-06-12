// TypeScript mirror of backend enums (app/core/constants.py) and the REST/WS
// schemas (app/schemas/*). Hand-mirrored; keep in sync with the backend —
// the enum names and values must match overview §4 exactly.

export type ProjectStatus =
  | "draft"
  | "scoping"
  | "awaiting_input"
  | "running"
  | "paused"
  | "complete"
  | "failed";

export type Stage =
  | "scoping"
  | "literature_search"
  | "paper_analysis"
  | "comparative_analysis"
  | "gap_analysis"
  | "report_writing"
  | "presentation_generation";

export const STAGES: Stage[] = [
  "scoping",
  "literature_search",
  "paper_analysis",
  "comparative_analysis",
  "gap_analysis",
  "report_writing",
  "presentation_generation",
];

export const STAGE_LABELS: Record<Stage, string> = {
  scoping: "Scoping",
  literature_search: "Literature search",
  paper_analysis: "Paper analysis",
  comparative_analysis: "Comparative analysis",
  gap_analysis: "Gap analysis",
  report_writing: "Report writing",
  presentation_generation: "Presentation",
};

export type ConfidenceLabel = "well_established" | "emerging" | "contested" | "speculative";

export type TriageStatus = "deep_read" | "skimmed" | "set_aside" | "excluded";

export type DiscoveryChannel = "keyword_search" | "citation_snowball" | "user_supplied";

export type EscalationStatus = "open" | "resolved" | "auto_resolved";

export type EscalationTrigger =
  | "ambiguous_scope"
  | "thin_literature"
  | "unresolved_contradiction"
  | "high_stakes";

export type AuditActionType =
  | "stage_start"
  | "stage_complete"
  | "search_run"
  | "query_reformulated"
  | "paper_triaged"
  | "paper_analyzed"
  | "contradiction_flagged"
  | "contradiction_investigated"
  | "cluster_assigned"
  | "comparison_updated"
  | "gap_identified"
  | "report_drafted"
  | "self_check_completed"
  | "report_revised"
  | "presentation_generated"
  | "loop_back"
  | "escalation_raised"
  | "escalation_resolved"
  | "budget_warning"
  | "stopped"
  | "error";

export type StoppingCriterion =
  | "saturation"
  | "coverage"
  | "stable_map"
  | "budget"
  | "user_stopped"
  | "error";

export type BudgetCategory = "llm_tokens" | "search_calls" | "papers_read" | "time";

export type GapImportance = "high" | "medium" | "low";

export type ProvenanceContext = "analysis" | "comparison" | "gap" | "report" | "presentation";

// ---------- Common envelopes ----------

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface ErrorBody {
  code: string;
  message: string;
  details: Record<string, unknown>;
}

export interface ErrorEnvelope {
  error: ErrorBody;
}

// ---------- Projects ----------

export type Budget = Partial<Record<BudgetCategory, number>>;

export interface ProjectCreate {
  title?: string | null;
  original_request: string;
  audience?: string | null;
  outputs_requested?: string[] | null;
  budget?: Budget | null;
}

export interface ProjectUpdate {
  title?: string | null;
  research_question?: string | null;
  scope?: Record<string, unknown> | null;
  audience?: string | null;
  outputs_requested?: string[] | null;
  budget?: Budget | null;
  status?: ProjectStatus | null;
  current_stage?: Stage | null;
}

export interface Project {
  id: string;
  title: string;
  original_request: string;
  research_question: string | null;
  scope: Record<string, unknown> | null;
  audience: string | null;
  outputs_requested: string[] | null;
  budget: Budget | null;
  status: ProjectStatus;
  current_stage: Stage | null;
  created_at: string;
  updated_at: string;
}

// ---------- Runs ----------

export interface Run {
  id: string;
  project_id: string;
  status: string;
  started_at: string | null;
  ended_at: string | null;
  stopping_criterion: StoppingCriterion | null;
  budget_consumed: Record<string, number> | null;
}

export interface RunStartResponse {
  run_id: string;
}

export interface BudgetAdjustBody {
  llm_tokens?: number | null;
  search_calls?: number | null;
  papers_read?: number | null;
  time?: number | null;
}

// ---------- Escalations ----------

export interface EscalationOption {
  id?: string;
  label: string;
  description?: string | null;
  consequence?: string | null;
}

export interface Escalation {
  id: string;
  project_id: string;
  run_id: string | null;
  trigger: EscalationTrigger;
  question: string;
  context: Record<string, unknown> | null;
  options: EscalationOption[] | null;
  status: EscalationStatus;
  user_response: Record<string, unknown> | null;
  created_at: string;
  resolved_at: string | null;
}

// ---------- Scope proposal (escalation context for scope confirmation) ----------

export interface AmbiguityOption {
  id: string;
  label: string;
  description?: string | null;
}

export interface Ambiguity {
  id: string;
  question: string;
  why_it_matters?: string | null;
  material?: boolean;
  options: AmbiguityOption[];
}

export interface ProposedScope {
  time_window?: string | null;
  included_subfields?: string[];
  excluded_subfields?: string[];
  depth?: string | null;
}

export interface ScopeProposal {
  research_question: string;
  scope: ProposedScope;
  audience?: string | null;
  outputs?: string[];
  ambiguities?: Ambiguity[];
  answerable_from_literature: boolean;
  answerability_reasoning: string;
}

// ---------- Sources & analysis ----------

export interface Source {
  id: string;
  project_id: string;
  title: string;
  authors: string[] | null;
  venue: string | null;
  year: number | null;
  doi: string | null;
  url: string | null;
  abstract: string | null;
  discovery_channel: DiscoveryChannel | null;
  relevance_score: number | null;
  credibility_score: number | null;
  triage_status: TriageStatus | null;
  triage_reason: string | null;
  cluster_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface SourceCreateManual {
  title: string;
  authors?: string[] | null;
  venue?: string | null;
  year?: number | null;
  doi?: string | null;
  url?: string | null;
  abstract?: string | null;
}

export interface SourceOverrideBody {
  action: "promote" | "exclude";
  reason?: string | null;
}

export interface ResultFinding {
  finding: string;
  numbers?: string | null;
  passage?: string;
}

export interface AuthorLimitation {
  limitation: string;
  passage?: string;
}

export interface CredibilityComponent {
  score: number;
  note: string;
  known?: boolean;
}

export interface PaperAnalysis {
  id: string;
  source_id: string;
  core_claim: string | null;
  method: string | null;
  results: ResultFinding[] | null;
  datasets: string[] | null;
  author_limitations: AuthorLimitation[] | null;
  agent_critique: string | null;
  credibility_breakdown: Record<string, CredibilityComponent | string> | null;
  confidence_label: ConfidenceLabel | null;
  created_at: string;
}

export interface Contradiction {
  id: string;
  project_id: string;
  source_a_id: string;
  source_b_id: string;
  description: string;
  investigation: string | null;
  resolution: string | null;
  resolved: boolean;
}

export interface AnalysisDetail {
  source: Source;
  analysis: PaperAnalysis | null;
  contradictions: Contradiction[];
}

// ---------- Comparison (field map) ----------

export interface Cluster {
  id: string;
  project_id: string;
  label: string;
  description: string | null;
  defining_characteristics: string[] | Record<string, unknown> | null;
}

export interface Dimension {
  name: string;
  description?: string;
  why_contested?: string;
  source_indexes?: number[];
  values_observed?: string[];
}

// Persisted matrix shape (stages/comparison/handler.py _build_matrix).
export interface MatrixCell {
  cluster_id: string;
  dimension: string;
  summary?: string;
  source_ids?: string[];
  confidence_label?: ConfidenceLabel;
  provenance_id?: string;
  empty: boolean;
}

export interface Matrix {
  clusters: { id: string; label: string }[];
  dimensions: string[];
  cells: MatrixCell[];
}

export interface ConsensusPoint {
  statement: string;
  source_ids?: string[];
  confidence_label?: ConfidenceLabel;
}

export interface ContestedPoint {
  statement: string;
  source_ids?: string[];
  contradiction_id?: string | null;
  investigation?: string | null;
  resolution?: string | null;
  resolution_type?: "conditional" | "unresolved" | null;
  confidence_label?: ConfidenceLabel;
}

export interface Comparison {
  id: string;
  project_id: string;
  dimensions: Dimension[] | null;
  matrix: Matrix | null;
  consensus_points: ConsensusPoint[] | null;
  contested_points: ContestedPoint[] | null;
}

export interface FieldMap {
  clusters: Cluster[];
  comparison: Comparison | null;
  contradictions: Contradiction[];
}

// ---------- Gaps ----------

export interface Gap {
  id: string;
  project_id: string;
  description: string;
  supporting_evidence: {
    type?: string;
    rationale?: string;
    gap_type?: string;
    evidence?: string;
    source_ids?: string[];
  } | null;
  importance: GapImportance | null;
  confidence_label: ConfidenceLabel | null;
}

// ---------- Reports & presentations ----------

export interface SelfCheckFinding {
  section_index?: number;
  claim_index?: number;
  issue: string;
  action: string;
  note: string;
  revised_text?: string | null;
}

export interface SelfCheckResult {
  findings?: SelfCheckFinding[];
  summary?: string;
  passed?: boolean;
  [key: string]: unknown;
}

export interface Report {
  id: string;
  project_id: string;
  audience: string | null;
  content_markdown: string | null;
  self_check_result: SelfCheckResult | null;
  stopping_criterion: StoppingCriterion | null;
  version: number;
}

export interface ReportRewriteRequest {
  audience?: string | null;
  length?: "brief" | "standard" | "comprehensive" | null;
  expand_section?: string | null;
}

export interface EvidencePoint {
  text: string;
  source_indexes?: number[];
  source_ids?: string[];
  passage?: string | null;
  is_inference?: boolean;
}

export interface VisualSpec {
  type: "comparison_table" | "timeline" | "trend" | "bullet_set";
  title?: string | null;
  columns?: string[];
  rows?: string[][];
  points?: string[];
}

export interface Slide {
  headline: string;
  key_message_index?: number | null;
  evidence?: EvidencePoint[];
  visual?: VisualSpec | null;
  speaker_notes?: string | null;
}

export interface KeyMessage {
  message: string;
  source_indexes?: number[];
}

export interface Presentation {
  id: string;
  project_id: string;
  through_line: string | null;
  key_messages: (KeyMessage | string)[] | null;
  slides: Slide[] | null;
  speaker_notes: string[] | null;
  version: number;
}

// ---------- Provenance ----------

export interface Provenance {
  id: string;
  project_id: string;
  claim_text: string;
  source_id: string | null;
  passage: string | null;
  is_inference: boolean;
  confidence_label: ConfidenceLabel | null;
  context: ProvenanceContext;
  ref_id: string | null;
}

// ---------- Audit ----------

export interface AuditEntry {
  id: string;
  project_id: string;
  run_id: string | null;
  timestamp: string;
  action_type: AuditActionType;
  stage: Stage | null;
  description: string;
  reasoning: string | null;
  payload: Record<string, unknown> | null;
}

// ---------- WebSocket events (overview §6) ----------

export type EventType =
  | "stage_changed"
  | "activity"
  | "counter_update"
  | "loop_back"
  | "saturation_update"
  | "escalation_raised"
  | "escalation_resolved"
  | "output_ready"
  | "run_finished"
  | "error";

export interface WsEvent {
  id: string;
  project_id: string;
  run_id: string | null;
  type: EventType;
  stage: Stage | null;
  timestamp: string;
  payload: Record<string, unknown>;
}

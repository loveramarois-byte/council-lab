// Browser API traffic must stay same-origin so Next.js can inject the private
// backend token. The direct loopback port is intentionally not a public API.
const API_URL = "";

export type Provider = {
  id: string;
  preset_id: string;
  display_name: string;
  description: string;
  key_url?: string;
  docs_url?: string;
  provider_type: string;
  protocol_mode: string;
  base_url: string;
  api_key_env?: string | null;
  has_api_key: boolean;
  credential_source: "environment" | "system" | "none";
  supports_api_key: boolean;
  requires_api_key: boolean;
  enabled?: boolean;
  is_active: boolean;
  default_model: string;
  reasoning_effort: "low" | "medium" | "high" | "xhigh" | "max" | "ultra";
  timeout_seconds: number;
  available_models: string[];
  model_source: "none" | "recommended" | "provider" | "ccswitch_history" | "built_in" | "saved";
  local_only: boolean;
  last_health_check?: string | null;
  last_error?: string | null;
  capabilities?: Record<string, boolean>;
};

export function providerIsReady(provider: Provider) {
  if (provider.id === "mock" || provider.enabled === false) return false;
  if (provider.id === "ccswitch") {
    const upstreamBusy = Boolean(provider.last_error && /429|502|503|504|too many requests|上游/i.test(provider.last_error));
    return Boolean(provider.last_health_check) && (!provider.last_error || upstreamBusy);
  }
  return Boolean(provider.has_api_key && provider.default_model && !provider.last_error);
}

export type AgentAssignment = {
  role: "analyst" | "challenger" | "builder" | "observer" | "finalizer";
  provider_id: string;
  model: string;
  protocol: "auto" | "responses" | "chat_completions";
  reasoning_effort: "low" | "medium" | "high" | "xhigh" | "max" | "ultra";
  max_output_tokens: number;
  temperature: number;
  timeout_seconds: number;
};

export type AgentAssignmentsConfig = { schema_version: number; seats: AgentAssignment[]; finalizer: AgentAssignment };
export type ResolvedAssignment = AgentAssignment & { provider_name: string };
export type RunLimits = { max_model_calls: number; max_tokens: number; timeout_seconds: number };
export type CouncilMode = "general" | "traditional_culture";
export type TraditionalCultureReferenceId =
  | "qiong_tong_bao_dian"
  | "san_ming_tong_hui"
  | "di_tian_sui"
  | "yuan_hai_zi_ping"
  | "qian_li_ming_gao"
  | "xie_ji_bian_fang_shu"
  | "guo_lao_xing_zong"
  | "zi_ping_zhen_quan"
  | "shen_feng_tong_kao"
  | "zhou_yi"
  | "ziwei_doushu_quan_shu"
  | "xing_ping_hui_hai"
  | "ming_li_yue_yan"
  | "zao_hua_yuan_yuan"
  | "bu_shi_zheng_zong";
export type TraditionalCultureProfile = {
  calendar_type: "solar";
  birth_date: string;
  birth_time: string;
  time_precision: "exact" | "approximate";
  gender: "male" | "female";
  birth_place: string;
  timezone: "Asia/Shanghai";
  true_solar_time_applied: false;
  focus_topics: ("temperament" | "career" | "relationships" | "timing")[];
  reference_book_ids?: TraditionalCultureReferenceId[];
};
export type TraditionalCultureSnapshot = {
  schema_version: 1;
  calculation_source: "local_browser";
  calculated_at: string;
  profile: TraditionalCultureProfile;
  engines: { id: "lunar-javascript" | "iztro"; version: string; source_url: string; license: "MIT" }[];
  calendar_facts: { solar_datetime: string; lunar_date: string; zodiac: string; constellation: string; eight_char: string; pillars: string[]; pillar_wuxing: string[]; heavenly_stem_ten_gods: string[] };
  ziwei_chart: { solar_date: string; lunar_date: string; chinese_date: string; time_label: string; time_range: string; five_elements_class: string; soul_star: string; body_star: string; soul_palace_branch: string; body_palace_branch: string; palaces: { index: number; name: string; heavenly_stem: string; earthly_branch: string; is_body_palace: boolean; is_original_palace: boolean; major_stars: string[]; minor_stars: string[]; changsheng12: string; decadal_range: number[] }[] };
  notices: string[];
  snapshot_sha256: string;
};
export type RunSummary = Pick<Run, "id" | "question" | "mode" | "council_mode" | "status" | "created_at" | "provider_id" | "participant_roles" | "seat_assignments" | "usage"> & { has_final_decision: boolean };
export type RiskTier = "normal" | "elevated" | "high" | "critical";
export type HighRiskStatus = "DRAFT" | "RISK_ASSESSMENT_REQUIRED" | "MORE_INFORMATION_REQUIRED" | "EVIDENCE_REQUIRED" | "INDEPENDENT_ANALYSIS" | "CROSS_EXAMINATION" | "PROFESSIONAL_ESCALATION_REQUIRED" | "READY_FOR_HUMAN_REVIEW" | "APPROVAL_REQUIRED" | "APPROVED" | "REJECTED" | "ACTION_BLOCKED" | "COMPLETED" | "CANCELLED";
export type VerificationStatus = "unverified" | "pending" | "verified" | "rejected" | "conflicting" | "expired" | "legacy_default";
export type RequiredFact = { fact_id: string; name: string; description: string; required: boolean; value?: string | null; source: "user" | "document" | "tool" | "system" | "unknown"; verified: boolean; materiality: "low" | "medium" | "high" | "critical"; source_ref?: string | null; source_title?: string | null; source_version?: string | null; source_timestamp?: string | null; expires_at?: string | null; verification_method?: string | null; verified_by?: string | null; verified_at?: string | null; verification_status: VerificationStatus };
export type HighRiskEvidence = { evidence_id: string; run_id: string; fact_id: string; fact_value_hash: string; domain: string; source_type: "manual" | "document" | "tool"; source_title: string; source_ref: string; source_version?: string | null; source_timestamp: string; expires_at?: string | null; content_sha256?: string | null; submitted_by: string; submitted_at: string; verification_status: VerificationStatus; verification_method?: string | null; verified_by?: string | null; verified_at?: string | null };
export type EvidenceVerification = { verification_id: string; evidence_id: string; run_id: string; status: "verified" | "rejected" | "conflicting"; method: string; reviewer_id: string; reviewer_role: string; domain: string; note: string; verified_at: string };
export type ProfessionalReview = { review_id: string; run_id: string; reviewer_id: string; reviewer_role: string; domain: string; scope: string; attestation: string; decision: "approved" | "rejected" | "escalation_required"; evidence_snapshot_hash: string; report_hash: string; reviewed_at: string; expires_at: string };
export type HighRiskRun = {
  run_id: string;
  status: HighRiskStatus;
  version: number;
  risk_assessment: { run_id: string; risk_tier: RiskTier; original_risk_tier: RiskTier; detected_domains: string[]; reasons: string[]; classifier_version: string; confidence: number; requires_user_confirmation: boolean; assessed_at: string; manually_overridden: boolean; override_actor_id?: string | null; override_reason?: string | null };
  required_facts: RequiredFact[];
  evidence_records: HighRiskEvidence[];
  professional_reviews: ProfessionalReview[];
  assurance: { evidence_complete: boolean; evidence_current: boolean; evidence_conflict: boolean; professional_review_complete: boolean; medical_red_flag: boolean; blocking_reasons: string[] };
  decision?: { status: string; report: string; report_hash: string; quality_signals: { evidence_coverage: string; source_quality: string; source_freshness: string; agent_disagreement: string; critical_information_missing: boolean }; disclaimer: string } | null;
  requested_action_type?: string | null;
  requested_action_payload_hash?: string | null;
  report_hash?: string | null;
  requested_by: string;
  created_at: string;
  updated_at: string;
};
export type HighRiskApproval = { approval_id: string; run_id: string; requested_action_type: string; requested_action_payload_hash: string; decision_report_hash: string; requested_at: string; requested_by: string; status: "pending" | "approved" | "rejected" | "expired" | "revoked"; decided_at?: string | null; decided_by?: string | null; decision_reason?: string | null; expires_at: string; consumed_at?: string | null };
export type HighRiskAuditEvent = {
  event_id: string;
  sequence: number;
  run_id: string;
  event_type: string;
  occurred_at: string;
  actor_type: "user" | "reviewer" | "system" | "model" | "tool";
  previous_status?: string | null;
  new_status?: string | null;
};
export const LOCAL_HIGH_RISK_ACTOR = "local-requester";
export type Project = {
  id: string;
  name: string;
  description: string;
  instructions: string;
  created_at: string;
  updated_at: string;
  source_count: number;
  run_count: number;
};
export type ProjectSource = {
  id: string;
  project_id: string;
  kind: "text" | "file" | "url";
  title: string;
  content: string;
  url: string;
  filename: string;
  media_type: string;
  size_bytes: number;
  sha256: string;
  created_at: string;
};
export type RunSourceSnapshot = Omit<ProjectSource, "project_id" | "media_type" | "size_bytes" | "created_at">;
export type MemoryType = "decision" | "assumption" | "risk" | "unresolved_question" | "action" | "outcome" | "superseded_decision";
export type RunMemorySnapshotItem = { memory_id: string; source_run_id: string; type: MemoryType; content: string; verification_status: string };
export type MemoryProposal = { id: string; workspace_id: string; source_run_id: string; type: MemoryType; content: string; rationale: string; related_entity_ids: string[]; created_at: string };
export type MemoryProposalView = { proposal: MemoryProposal; status: "pending" | "approved" | "rejected"; memory_id?: string | null; reviewed_at?: string | null };
export type ApprovedMemory = { id: string; workspace_id: string; source_run_id: string; proposal_id: string; type: MemoryType; content: string; verification_status: string; valid_from: string; valid_until?: string | null; supersedes_memory_id?: string | null; created_at: string };
export type MemoryView = { memory: ApprovedMemory; active: boolean; deleted: boolean; last_action: "approved" | "rejected" | "disabled" | "enabled" | "deleted"; last_action_at: string };
export type MemoryPreview = { workspace_id: string; selected_memory_ids: string[]; included: RunMemorySnapshotItem[]; excluded_memory_ids: string[]; rendered_context: string };
export type ReadinessCheck = { id: "goal_defined" | "constraints_defined" | "options_defined" | "success_criteria_defined" | "critical_facts_available"; status: "pass" | "warning" | "fail"; message: string };
export type DecisionReadiness = { ready: boolean; task_labels: string[]; checks: ReadinessCheck[]; clarification_questions: string[]; recommended_mode: "direct" | "quick_council" | "full_council" | "high_risk_council"; rules_version: string };
export type DecisionClaim = { id: string; run_id: string; text: string; basis: "user_provided" | "model_inference" | "cited_unverified" | "seat_disputed" | "outcome_supported" | "outcome_contradicted"; source_seat_ids: string[]; related_entity_ids: string[]; citation?: { url: string; provided_by: "user" | "model"; externally_checked: false } | null; dispute_summary?: string | null; created_at: string };
export type DecisionClaimView = { claim: DecisionClaim; current_basis: DecisionClaim["basis"]; latest_outcome?: { result: "supported" | "contradicted"; note: string } | null };
export type DeliberationTemplate = { id: string; name: string; description: string; prompt_hint: string; system_guidance: string };
export type OutputContractId = "general_decision" | "product_review" | "technical_architecture";
export type OutputContractDefinition = { id: OutputContractId; name: string; description: string; input_checks: string[]; prompt_hint: string; system_guidance: string };
export type SeatOutcomeReview = { role: "analyst" | "challenger" | "builder" | "observer"; status: "pending" | "supported" | "mixed" | "contradicted"; note: string };
export type DecisionReview = { selected_decision: string; expected_result: string; review_date?: string | null; actual_result: string; outcome_status: "pending" | "successful" | "partial" | "unsuccessful" | "unclear"; seat_outcomes: SeatOutcomeReview[]; updated_at: string };
export type DecisionReviewInput = Omit<DecisionReview, "updated_at">;
export type UpdateInfo = {
  current_version: string;
  latest_version: string;
  update_available: boolean;
  can_auto_update: boolean;
  installation_kind: "macos" | "windows" | "development" | "unsupported";
  reason: string;
  release_url: string;
  published_at?: string | null;
  notes: string;
  package_name?: string | null;
};
export type UpdateStatus = {
  current_version: string;
  phase: "idle" | "checking" | "downloading" | "verifying" | "restarting" | "error";
  progress: number;
  message: string;
  target_version?: string | null;
  error?: string | null;
};

export type Run = {
  id: string;
  question: string;
  mode: "quick" | "standard" | "rigorous";
  council_mode?: CouncilMode;
  workflow_strategy?: "sequential" | "independent";
  provider_id: string;
  model: string;
  reasoning_effort: "low" | "medium" | "high" | "xhigh" | "max" | "ultra";
  workflow_engine?: string;
  checkpoint_count?: number;
  context_snapshot?: {
    strategy: string;
    token_budget: number;
    estimated_tokens: number;
    included_turns: number;
    total_turns: number;
    compacted: boolean;
    summary: string;
    source_tokens?: number;
    history_tokens?: number;
    token_estimator?: string;
    token_estimator_exact?: boolean;
  };
  status: "queued" | "running" | "awaiting_final_input" | "completed" | "failed" | "stopped" | "cancelled";
  created_at: string;
  updated_at: string;
  analysis?: QuestionAnalysis | null;
  readiness?: DecisionReadiness | null;
  candidates: Candidate[];
  critiques: Critique[];
  verifications: Verification[];
  revisions: Revision[];
  scores: Score[];
  final_decision?: FinalDecision | null;
  usage: Usage;
  provider_attempts?: ProviderAttempt[];
  degraded: boolean;
  error?: string | null;
  protocol: string;
  discussion_turns: DiscussionTurn[];
  participant_roles: Participant[];
  current_speaker_index: number;
  discussion_round: number;
  awaiting_user: boolean;
  limits: RunLimits;
  seat_assignments: ResolvedAssignment[];
  finalizer_assignment?: ResolvedAssignment | null;
  auto_summarize: boolean;
  high_risk_control?: boolean | null;
  recoverable: boolean;
  limit_reason?: string | null;
  project_id?: string | null;
  project_name?: string;
  project_context?: string;
  template_id?: string;
  template_name?: string;
  output_contract?: OutputContractId;
  source_snapshots?: RunSourceSnapshot[];
  memory_snapshot?: RunMemorySnapshotItem[];
  decision_review?: DecisionReview | null;
  traditional_culture_snapshot?: TraditionalCultureSnapshot | null;
  traditional_culture_consent?: boolean;
};

export type QuestionAnalysis = {
  question_type: string;
  needs_realtime: boolean;
  needs_web: boolean;
  needs_external_evidence?: boolean;
  needs_code_execution: boolean;
  needs_math: boolean;
  needs_file: boolean;
  high_risk_domain: boolean;
  high_risk_domains?: string[];
  faulty_premise: boolean;
  suitable_for_multi_agent: boolean;
  recommended_agents: number;
  recommended_mode: string;
  expected_model_calls: number;
  expected_token_limit: number;
  expected_tool_calls: number;
  confidence?: number;
  reasons?: string[];
  short_task_route?: boolean;
};

export type Participant = { id: string; name: string; role: string; brief: string };
export type DiscussionTurn = { id: string; speaker_type: "user" | "agent" | "system"; speaker_id: string; speaker_name: string; role_label: string; content: string; provider_id?: string | null; provider_name?: string | null; model?: string | null; round: number; reused_from_run_id?: string | null; created_at: string };

export type CandidateStructureSource = "agent_output" | "postprocessed" | "manual" | "legacy_default" | "none";
export type Candidate = { candidate_id: string; anonymous_label?: string; answer: string; model: string; provider: string; status: string; usage: Usage; structure_source: CandidateStructureSource; key_reasons: string[]; assumptions: string[]; claims_to_verify: string[]; uncertainties: string[]; risks: string[]; proposed_sources: string[] };
export type Critique = { candidate_id: string; severity: string; issue_type: string; issue: string; possible_counterexample: string; confidence: number };
export type Verification = { task_id: string; claim: string; status: string; evidence_summary: string; sources: string[]; confidence: number; limitations: string[] };
export type Revision = { candidate_id: string; revised_answer: string; accepted_critiques: string[]; remaining_uncertainties: string[] };
export type Score = { candidate_id: string; evidence_score: number; reasoning_score: number; coverage_score: number; risk_score: number; clarity_score: number; weighted_total: number; explanation: string };
export type Usage = { model_calls: number; tool_calls: number; input_tokens: number; output_tokens: number; estimated_cost?: number | null; duration_ms: number };
export type ProviderAttempt = { role: string; provider_id: string; provider_name: string; model: string; endpoint: string; attempt: number; status_code?: number | null; duration_ms: number; upstream_request_id?: string | null; error_kind?: string | null };
export type FinalDecision = { final_answer: string; key_reasons: string[]; verified_claims: string[]; partially_verified_claims: string[]; contradicted_claims: string[]; unverified_claims: string[]; disagreements: string[]; risks_and_limitations: string[]; confidence: { level: string; score?: number; explanation: string }; sources: string[]; provider_summary: { provider: string; protocol: string; model: string; used_ccswitch: boolean; degraded: boolean; seat_providers?: { role: string; provider: string; model: string }[] }; usage: Usage };
export type DecisionBrief = {
  id: string;
  run_id: string;
  version: number;
  schema_version: 1 | 2;
  generated_at: string;
  generation_reason: "run_completed";
  status: "proceed" | "conditional" | "no_decision";
  recommendation: string;
  support: "unanimous" | "majority" | "contested";
  decisive_reasons: { id: string; summary: string; supporting_seat_ids: string[]; opposing_seat_ids: string[]; related_claim_ids: string[] }[];
  rejected_alternatives: { option: string; reason: string }[];
  unresolved: { id: string; issue: string; blocking: boolean; positions: { seat_id: string; position: string }[]; resolution_method?: string | null }[];
  assumptions: { id: string; claim: string; basis: "user_input" | "model_inference" | "cited_unverified" | "outcome_verified"; validation_method?: string | null; owner?: string | null; due_at?: string | null }[];
  actions: { id: string; action: string; owner?: string | null; due_at?: string | null; success_criteria?: string | null; status: "pending" | "in_progress" | "done" | "cancelled" }[];
  reopen_triggers: { id: string; condition: string; check_method?: string | null; severity: "informational" | "important" | "blocking" }[];
  minority_report?: { summary: string; seat_ids: string[]; conditions_under_which_it_may_be_correct: string[] } | null;
  limitations: string[];
  output_contract: OutputContractId;
  contract_extension?:
    | { contract: "general_decision"; decision_criteria: string[]; key_tradeoffs: string[] }
    | { contract: "product_review"; target_users: string[]; user_problem: string; value_proposition: string; failure_conditions: string[]; validation_experiments: { hypothesis: string; method: string; success_threshold: string }[]; stop_conditions: string[] }
    | { contract: "technical_architecture"; requirements: string[]; constraints: string[]; proposed_architecture: string; alternatives: { option: string; tradeoffs: string[] }[]; failure_modes: string[]; migration_plan: string[]; rollback_plan: string[]; observability_requirements: string[] }
    | null;
};
export type ForkCheckpoint = "before_deliberation" | "after_seat_1" | "after_seat_2" | "after_seat_3" | "after_seat_4" | "before_synthesis";
export type RunFork = {
  id: string;
  parent_run_id: string;
  child_run_id: string;
  checkpoint: ForkCheckpoint;
  reason: string;
  changed_inputs: Record<string, string | number | boolean | Record<string, number>>;
  reused_turn_ids: string[];
  regenerated_seat_ids: string[];
  approval_inherited: false;
  created_at: string;
};
export type RunForkLineage = { parent?: RunFork | null; children: RunFork[] };
export type DecisionBriefComparison = {
  left_run_id: string;
  right_run_id: string;
  related: boolean;
  left: DecisionBrief;
  right: DecisionBrief;
  changed_fields: string[];
  status_changed: boolean;
  recommendation_changed: boolean;
  support_changed: boolean;
  unresolved_added: string[];
  unresolved_removed: string[];
};

type ErrorEnvelope = {
  detail?: string;
  error?: { code?: string; message?: string; request_id?: string };
};

export class CouncilApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string;

  constructor(status: number, body: ErrorEnvelope | null, responseRequestId: string | null) {
    const code = body?.error?.code || "REQUEST_FAILED";
    const requestId = body?.error?.request_id || responseRequestId || "";
    const detail = body?.error?.message || body?.detail || `请求失败 (${status})`;
    super(requestId ? `${detail}（排错编号 ${requestId}）` : detail);
    this.name = "CouncilApiError";
    this.status = status;
    this.code = code;
    this.requestId = requestId;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!(init?.body instanceof FormData) && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const response = await fetch(`${API_URL}${path}`, { ...init, headers });
  if (!response.ok) {
    const body = await response.json().catch(() => null) as ErrorEnvelope | null;
    throw new CouncilApiError(response.status, body, response.headers.get("X-Council-Request-ID"));
  }
  return response.json();
}

function newIdempotencyKey() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `council-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

async function idempotentRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set("Idempotency-Key", newIdempotencyKey());
  const requestInit = { ...init, headers };
  try {
    return await request<T>(path, requestInit);
  } catch (error) {
    if (error instanceof CouncilApiError) throw error;
    await new Promise((resolve) => setTimeout(resolve, 250));
    return request<T>(path, requestInit);
  }
}

async function download(path: string, init?: RequestInit): Promise<{ blob: Blob; filename: string }> {
  const response = await fetch(`${API_URL}${path}`, init);
  if (!response.ok) {
    const body = await response.json().catch(() => null) as ErrorEnvelope | null;
    throw new CouncilApiError(response.status, body, response.headers.get("X-Council-Request-ID"));
  }
  const disposition = response.headers.get("Content-Disposition") || "";
  const filename = disposition.match(/filename="([^"]+)"/)?.[1] || "council-diagnostics.zip";
  return { blob: await response.blob(), filename };
}

export const api = {
  downloadDiagnostics: () => download("/api/diagnostics/export", { headers: { "X-Council-Request": "app" } }),
  checkUpdate: (refresh = false) => request<UpdateInfo>(`/api/update/check${refresh ? "?refresh=true" : ""}`, refresh ? { headers: { "X-Council-Request": "app" } } : undefined),
  updateStatus: () => request<UpdateStatus>("/api/update/status"),
  installUpdate: () => request<UpdateStatus>("/api/update/install", { method: "POST", headers: { "X-Council-Request": "app" } }),
  providers: () => request<Provider[]>("/api/providers"),
  assignments: () => request<AgentAssignmentsConfig>("/api/agent-assignments"),
  saveAssignments: (body: AgentAssignmentsConfig) => request<AgentAssignmentsConfig>("/api/agent-assignments", { method: "PUT", body: JSON.stringify(body) }),
  patchProvider: (id: string, body: Partial<Pick<Provider, "base_url" | "protocol_mode" | "default_model" | "reasoning_effort">> & { api_key?: string }) => request<Provider>(`/api/providers/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  providerModels: (id: string) => request<{ models: string[]; source: string; fetched: number; default_model?: string; error?: string }>(`/api/providers/${id}/models`),
  deleteProviderCredential: (id: string) => request<Provider>(`/api/providers/${id}/credential`, { method: "DELETE" }),
  activateProvider: (id: string) => request<Provider>(`/api/providers/${id}/activate`, { method: "POST" }),
  detectCCSwitch: () => request<Record<string, unknown>>("/api/providers/ccswitch/detect", { method: "POST" }),
  testProvider: (id: string) => request<Record<string, unknown>>(`/api/providers/${id}/test`, { method: "POST" }),
  templates: () => request<DeliberationTemplate[]>("/api/templates"),
  outputContracts: () => request<OutputContractDefinition[]>("/api/output-contracts"),
  projects: () => request<Project[]>("/api/projects"),
  project: (id: string) => request<Project>(`/api/projects/${id}`),
  createProject: (body: Pick<Project, "name" | "description" | "instructions">) => request<Project>("/api/projects", { method: "POST", body: JSON.stringify(body) }),
  patchProject: (id: string, body: Partial<Pick<Project, "name" | "description" | "instructions">>) => request<Project>(`/api/projects/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteProject: (id: string) => request<{ deleted: boolean }>(`/api/projects/${id}`, { method: "DELETE" }),
  projectSources: (id: string) => request<ProjectSource[]>(`/api/projects/${id}/sources`),
  addTextSource: (id: string, body: { title: string; content: string }) => request<ProjectSource>(`/api/projects/${id}/sources/text`, { method: "POST", body: JSON.stringify(body) }),
  addUrlSource: (id: string, body: { title?: string; url: string }) => request<ProjectSource>(`/api/projects/${id}/sources/url`, { method: "POST", body: JSON.stringify(body) }),
  addFileSource: (id: string, file: File) => {
    const body = new FormData();
    body.append("file", file);
    return request<ProjectSource>(`/api/projects/${id}/sources/file`, { method: "POST", body });
  },
  deleteSource: (projectId: string, sourceId: string) => request<{ deleted: boolean }>(`/api/projects/${projectId}/sources/${sourceId}`, { method: "DELETE" }),
  createRun: (body: { question: string; mode: string; council_mode?: CouncilMode; workflow_strategy?: "sequential" | "independent"; provider_id?: string; model?: string; use_saved_assignments?: boolean; auto_summarize?: boolean; high_risk?: boolean; project_id?: string; source_ids?: string[]; include_project_history?: boolean; template_id?: string; output_contract?: OutputContractId; selected_memory_ids?: string[]; readiness_override?: boolean; readiness_override_reason?: string; traditional_culture_snapshot?: TraditionalCultureSnapshot; traditional_culture_consent?: boolean; limits?: RunLimits }) => idempotentRequest<Run>("/api/runs", { method: "POST", headers: body.high_risk ? { "X-Council-Actor": LOCAL_HIGH_RISK_ACTOR } : undefined, body: JSON.stringify(body) }),
  readiness: (question: string, high_risk = false) => request<DecisionReadiness>("/api/readiness", { method: "POST", body: JSON.stringify({ question, high_risk }) }),
  runs: () => request<RunSummary[]>("/api/runs?summary=true"),
  run: (id: string) => request<Run>(`/api/runs/${id}`),
  decisionBrief: (id: string) => request<DecisionBrief>(`/api/runs/${id}/decision-brief`),
  runLineage: (id: string) => request<RunForkLineage>(`/api/runs/${id}/lineage`),
  compareRuns: (left: string, right: string) => request<DecisionBriefComparison>(`/api/runs/compare?left=${encodeURIComponent(left)}&right=${encodeURIComponent(right)}`),
  forkRun: (id: string, body: { checkpoint: ForkCheckpoint; reason: string; prompt_append?: string; mode?: Run["mode"]; auto_summarize?: boolean; limits?: RunLimits }) => idempotentRequest<Run>(`/api/runs/${id}/fork`, { method: "POST", headers: { "X-Council-Actor": LOCAL_HIGH_RISK_ACTOR }, body: JSON.stringify(body) }),
  memory: () => request<MemoryView[]>("/api/memory"),
  memoryPreview: (selected_memory_ids: string[]) => request<MemoryPreview>("/api/memory/preview", { method: "POST", body: JSON.stringify({ selected_memory_ids }) }),
  memoryProposals: (runId: string) => request<MemoryProposalView[]>(`/api/runs/${runId}/memory-proposals`),
  createMemoryProposals: (runId: string) => request<MemoryProposalView[]>(`/api/runs/${runId}/memory-proposals`, { method: "POST" }),
  approveMemoryProposal: (proposalId: string, content?: string) => request<MemoryView>(`/api/memory/proposals/${proposalId}/approve`, { method: "POST", body: JSON.stringify({ ...(content ? { content } : {}) }) }),
  rejectMemoryProposal: (proposalId: string) => request<MemoryProposalView>(`/api/memory/proposals/${proposalId}/reject`, { method: "POST" }),
  changeMemoryState: (memoryId: string, action: "disable" | "enable" | "delete") => request<MemoryView>(`/api/memory/${memoryId}/${action}`, { method: "POST" }),
  cancelRun: (id: string) => idempotentRequest<Run>(`/api/runs/${id}/cancel`, { method: "POST" }),
  advanceRun: (id: string, body: { action: "continue" | "interject" | "question"; message?: string; target_agent?: string }) => idempotentRequest<Run>(`/api/runs/${id}/advance`, { method: "POST", body: JSON.stringify(body) }),
  interjectRun: (id: string, body: { action: "interject" | "question"; message: string; target_agent?: string }) => idempotentRequest<Run>(`/api/runs/${id}/interject`, { method: "POST", body: JSON.stringify(body) }),
  retryTurn: (id: string) => idempotentRequest<Run>(`/api/runs/${id}/retry-turn`, { method: "POST" }),
  resumeRun: (id: string, limits: RunLimits) => idempotentRequest<Run>(`/api/runs/${id}/resume`, { method: "POST", body: JSON.stringify(limits) }),
  summarizeRun: (id: string) => idempotentRequest<Run>(`/api/runs/${id}/summarize`, { method: "POST" }),
  rerun: (id: string) => idempotentRequest<Run>(`/api/runs/${id}/rerun`, { method: "POST" }),
  saveDecisionReview: (id: string, body: DecisionReviewInput) => idempotentRequest<Run>(`/api/runs/${id}/decision-review`, { method: "PUT", body: JSON.stringify(body) }),
  decisionClaims: (id: string) => request<DecisionClaimView[]>(`/api/runs/${id}/claims`),
  deleteRun: (id: string) => request<{ deleted: boolean }>(`/api/runs/${id}`, { method: "DELETE" }),
  highRiskRun: (id: string) => request<HighRiskRun>(`/api/high-risk/runs/${id}`),
  highRiskApproval: (id: string) => request<HighRiskApproval>(`/api/high-risk/runs/${id}/approval`),
  highRiskAudit: (id: string) => request<HighRiskAuditEvent[]>(`/api/high-risk/runs/${id}/audit`),
  updateHighRiskFacts: (id: string, facts: RequiredFact[]) => idempotentRequest<HighRiskRun>(`/api/high-risk/runs/${id}/facts`, { method: "PUT", headers: { "X-Council-Actor": LOCAL_HIGH_RISK_ACTOR }, body: JSON.stringify({ facts }) }),
  addHighRiskEvidence: (id: string, body: { fact_id: string; source_type: "manual" | "document" | "tool"; source_title: string; source_ref: string; source_version?: string | null; source_timestamp: string; expires_at?: string | null; content_sha256?: string | null }) => idempotentRequest<HighRiskEvidence>(`/api/high-risk/runs/${id}/evidence`, { method: "POST", headers: { "X-Council-Actor": LOCAL_HIGH_RISK_ACTOR }, body: JSON.stringify(body) }),
  verifyHighRiskEvidence: (id: string, evidenceId: string, reviewerId: string, reviewerKey: string, body: { status: "verified" | "rejected" | "conflicting"; method: string; reviewer_role: string; domain: string; note?: string }) => idempotentRequest<EvidenceVerification>(`/api/high-risk/runs/${id}/evidence/${evidenceId}/verification`, { method: "POST", headers: { "X-Council-Actor": reviewerId, "X-Council-Reviewer-Key": reviewerKey }, body: JSON.stringify(body) }),
  prepareHighRiskReview: (id: string, report: string) => idempotentRequest<HighRiskRun>(`/api/high-risk/runs/${id}/prepare-review`, { method: "POST", headers: { "X-Council-Actor": LOCAL_HIGH_RISK_ACTOR }, body: JSON.stringify({ report, requested_action_type: "decision_support_report", requested_action_payload: { effect: "read_only", delivery: "local_report" }, quality_signals: { evidence_coverage: "partial", source_quality: "unknown", source_freshness: "unknown", agent_disagreement: "material", critical_information_missing: false } }) }),
  submitHighRiskProfessionalReview: (id: string, reviewerId: string, reviewerKey: string, body: { reviewer_role: string; domain: string; scope: string; attestation: string; decision: "approved" | "rejected" | "escalation_required"; expires_in_minutes?: number }) => idempotentRequest<ProfessionalReview>(`/api/high-risk/runs/${id}/professional-reviews`, { method: "POST", headers: { "X-Council-Actor": reviewerId, "X-Council-Reviewer-Key": reviewerKey }, body: JSON.stringify(body) }),
  requestHighRiskApproval: (id: string) => idempotentRequest<HighRiskApproval>(`/api/high-risk/runs/${id}/approval-requests`, { method: "POST", headers: { "X-Council-Actor": LOCAL_HIGH_RISK_ACTOR }, body: JSON.stringify({ expires_in_minutes: 30 }) }),
  decideHighRiskApproval: (id: string, approvalId: string, reviewerId: string, reviewerKey: string, decision: "approved" | "rejected", reason: string) => idempotentRequest<HighRiskApproval>(`/api/high-risk/runs/${id}/approvals/${approvalId}/decision`, { method: "POST", headers: { "X-Council-Actor": reviewerId, "X-Council-Reviewer-Key": reviewerKey }, body: JSON.stringify({ decision, reason }) }),
  completeHighRiskRun: (id: string, approvalId: string) => idempotentRequest<HighRiskRun>(`/api/high-risk/runs/${id}/complete?approval_id=${encodeURIComponent(approvalId)}`, { method: "POST", headers: { "X-Council-Actor": LOCAL_HIGH_RISK_ACTOR } }),
  cancelHighRiskRun: (id: string) => idempotentRequest<HighRiskRun>(`/api/high-risk/runs/${id}/cancel`, { method: "POST", headers: { "X-Council-Actor": LOCAL_HIGH_RISK_ACTOR } }),
};

export const runExportUrl = (id: string, format: "markdown" | "html") => `${API_URL}/api/runs/${id}/export?format=${format}`;

export function subscribeToRun(
  id: string,
  onEvent: (event: unknown) => void,
  onEnd?: () => void,
  beforeReconnect?: () => Promise<void> | void,
) {
  let source: EventSource | null = null;
  let reconnectTimer: number | null = null;
  let reconnectDelay = 1000;
  let reconnecting = false;
  let lastEventId = 0;
  let stopped = false;
  const names = ["run_created", "run_fork_created", "question_analyzed", "agent_turn_started", "agent_turn_completed", "agent_turn_failed", "user_interjected", "awaiting_final_input", "summary_started", "decision_brief_generating", "decision_brief_generated", "decision_brief_validation_failed", "final_completed", "provider_degraded", "run_limit_reached", "run_cancelled", "run_failed"];
  const terminalEvents = new Set(["final_completed", "run_cancelled"]);

  const connect = async () => {
    if (stopped) return;
    if (reconnecting) await beforeReconnect?.();
    if (stopped) return;
    const replay = lastEventId > 0 ? `?last_event_id=${lastEventId}` : "";
    const nextSource = new EventSource(`${API_URL}/api/runs/${id}/events${replay}`);
    source = nextSource;
    nextSource.onopen = () => {
      reconnectDelay = 1000;
      reconnecting = false;
    };
    nextSource.onerror = () => {
      nextSource.close();
      if (stopped || reconnectTimer !== null) return;
      reconnecting = true;
      const delay = reconnectDelay;
      reconnectDelay = Math.min(reconnectDelay * 2, 10000);
      reconnectTimer = window.setTimeout(() => {
        reconnectTimer = null;
        void connect();
      }, delay);
    };
    names.forEach((name) => nextSource.addEventListener(name, (message) => {
      const event = message as MessageEvent;
      const sequence = Number.parseInt(event.lastEventId, 10);
      if (Number.isFinite(sequence)) lastEventId = Math.max(lastEventId, sequence);
      onEvent(JSON.parse(event.data));
      if (terminalEvents.has(name)) {
        stopped = true;
        nextSource.close();
        onEnd?.();
      }
    }));
  };

  void connect();
  return () => {
    stopped = true;
    source?.close();
    if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
  };
}

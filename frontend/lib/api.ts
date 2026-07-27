const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8001";

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
  available_models: string[];
  model_source: "none" | "recommended" | "provider" | "ccswitch_history" | "built_in" | "saved";
  local_only: boolean;
  last_health_check?: string | null;
  last_error?: string | null;
  capabilities?: Record<string, boolean>;
};

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

export type AgentAssignmentsConfig = { seats: AgentAssignment[]; finalizer: AgentAssignment };
export type ResolvedAssignment = AgentAssignment & { provider_name: string };
export type RunLimits = { max_model_calls: number; max_tokens: number; timeout_seconds: number };
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
export type DeliberationTemplate = { id: string; name: string; description: string; prompt_hint: string; system_guidance: string };
export type SeatOutcomeReview = { role: "analyst" | "challenger" | "builder" | "observer"; status: "pending" | "supported" | "mixed" | "contradicted"; note: string };
export type DecisionReview = { selected_decision: string; expected_result: string; review_date?: string | null; actual_result: string; outcome_status: "pending" | "successful" | "partial" | "unsuccessful" | "unclear"; seat_outcomes: SeatOutcomeReview[]; updated_at: string };
export type DecisionReviewInput = Omit<DecisionReview, "updated_at">;

export type Run = {
  id: string;
  question: string;
  mode: "quick" | "standard" | "rigorous";
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
  };
  status: "queued" | "running" | "awaiting_final_input" | "completed" | "failed" | "stopped" | "cancelled";
  created_at: string;
  updated_at: string;
  analysis?: Record<string, unknown> | null;
  candidates: Candidate[];
  critiques: Critique[];
  verifications: Verification[];
  revisions: Revision[];
  scores: Score[];
  final_decision?: FinalDecision | null;
  usage: Usage;
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
  recoverable: boolean;
  limit_reason?: string | null;
  project_id?: string | null;
  project_name?: string;
  project_context?: string;
  template_id?: string;
  template_name?: string;
  source_snapshots?: RunSourceSnapshot[];
  decision_review?: DecisionReview | null;
};

export type Participant = { id: string; name: string; role: string; brief: string };
export type DiscussionTurn = { id: string; speaker_type: "user" | "agent" | "system"; speaker_id: string; speaker_name: string; role_label: string; content: string; provider_id?: string | null; provider_name?: string | null; model?: string | null; round: number; created_at: string };

export type Candidate = { candidate_id: string; anonymous_label?: string; answer: string; model: string; provider: string; status: string; usage: Usage; key_reasons: string[]; uncertainties: string[] };
export type Critique = { candidate_id: string; severity: string; issue_type: string; issue: string; possible_counterexample: string; confidence: number };
export type Verification = { task_id: string; claim: string; status: string; evidence_summary: string; sources: string[]; confidence: number; limitations: string[] };
export type Revision = { candidate_id: string; revised_answer: string; accepted_critiques: string[]; remaining_uncertainties: string[] };
export type Score = { candidate_id: string; evidence_score: number; reasoning_score: number; coverage_score: number; risk_score: number; clarity_score: number; weighted_total: number; explanation: string };
export type Usage = { model_calls: number; tool_calls: number; input_tokens: number; output_tokens: number; estimated_cost?: number | null; duration_ms: number };
export type FinalDecision = { final_answer: string; key_reasons: string[]; verified_claims: string[]; partially_verified_claims: string[]; contradicted_claims: string[]; unverified_claims: string[]; disagreements: string[]; risks_and_limitations: string[]; confidence: { level: string; score?: number; explanation: string }; sources: string[]; provider_summary: { provider: string; protocol: string; model: string; used_ccswitch: boolean; degraded: boolean; seat_providers?: { role: string; provider: string; model: string }[] }; usage: Usage };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!(init?.body instanceof FormData) && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const response = await fetch(`${API_URL}${path}`, { ...init, headers });
  if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail || `请求失败 (${response.status})`);
  return response.json();
}

export const api = {
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
  createRun: (body: { question: string; mode: string; provider_id?: string; model?: string; use_saved_assignments?: boolean; auto_summarize?: boolean; project_id?: string; source_ids?: string[]; include_project_history?: boolean; template_id?: string; limits?: RunLimits }) => request<Run>("/api/runs", { method: "POST", body: JSON.stringify(body) }),
  runs: () => request<Run[]>("/api/runs"),
  run: (id: string) => request<Run>(`/api/runs/${id}`),
  cancelRun: (id: string) => request<Run>(`/api/runs/${id}/cancel`, { method: "POST" }),
  advanceRun: (id: string, body: { action: "continue" | "interject" | "question"; message?: string; target_agent?: string }) => request<Run>(`/api/runs/${id}/advance`, { method: "POST", body: JSON.stringify(body) }),
  interjectRun: (id: string, body: { action: "interject" | "question"; message: string; target_agent?: string }) => request<Run>(`/api/runs/${id}/interject`, { method: "POST", body: JSON.stringify(body) }),
  retryTurn: (id: string) => request<Run>(`/api/runs/${id}/retry-turn`, { method: "POST" }),
  resumeRun: (id: string, limits: RunLimits) => request<Run>(`/api/runs/${id}/resume`, { method: "POST", body: JSON.stringify(limits) }),
  summarizeRun: (id: string) => request<Run>(`/api/runs/${id}/summarize`, { method: "POST" }),
  rerun: (id: string) => request<Run>(`/api/runs/${id}/rerun`, { method: "POST" }),
  saveDecisionReview: (id: string, body: DecisionReviewInput) => request<Run>(`/api/runs/${id}/decision-review`, { method: "PUT", body: JSON.stringify(body) }),
  deleteRun: (id: string) => request<{ deleted: boolean }>(`/api/runs/${id}`, { method: "DELETE" }),
};

export const runExportUrl = (id: string, format: "markdown" | "html") => `${API_URL}/api/runs/${id}/export?format=${format}`;

export function subscribeToRun(id: string, onEvent: (event: any) => void, onEnd?: () => void) {
  const source = new EventSource(`${API_URL}/api/runs/${id}/events`);
  source.onerror = () => { source.close(); onEnd?.(); };
  const names = ["run_created", "question_analyzed", "agent_turn_started", "agent_turn_completed", "agent_turn_failed", "user_interjected", "awaiting_final_input", "summary_started", "final_completed", "provider_degraded", "run_limit_reached", "run_cancelled", "run_failed"];
  names.forEach((name) => source.addEventListener(name, (message) => {
    onEvent(JSON.parse((message as MessageEvent).data));
    if (["final_completed", "run_failed", "run_limit_reached", "run_cancelled"].includes(name)) { source.close(); onEnd?.(); }
  }));
  return () => source.close();
}

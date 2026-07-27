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
  limits: { max_model_calls: number; max_tokens: number; timeout_seconds: number };
  seat_assignments: ResolvedAssignment[];
  finalizer_assignment?: ResolvedAssignment | null;
  auto_summarize: boolean;
  recoverable: boolean;
  limit_reason?: string | null;
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
  const response = await fetch(`${API_URL}${path}`, { ...init, headers: { "Content-Type": "application/json", ...(init?.headers || {}) } });
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
  createRun: (body: { question: string; mode: string; provider_id?: string; model?: string; use_saved_assignments?: boolean; auto_summarize?: boolean; limits?: { max_model_calls: number; max_tokens: number; timeout_seconds: number } }) => request<Run>("/api/runs", { method: "POST", body: JSON.stringify(body) }),
  runs: () => request<Run[]>("/api/runs"),
  run: (id: string) => request<Run>(`/api/runs/${id}`),
  cancelRun: (id: string) => request<Run>(`/api/runs/${id}/cancel`, { method: "POST" }),
  advanceRun: (id: string, body: { action: "continue" | "interject" | "question"; message?: string; target_agent?: string }) => request<Run>(`/api/runs/${id}/advance`, { method: "POST", body: JSON.stringify(body) }),
  interjectRun: (id: string, body: { action: "interject" | "question"; message: string; target_agent?: string }) => request<Run>(`/api/runs/${id}/interject`, { method: "POST", body: JSON.stringify(body) }),
  retryTurn: (id: string) => request<Run>(`/api/runs/${id}/retry-turn`, { method: "POST" }),
  summarizeRun: (id: string) => request<Run>(`/api/runs/${id}/summarize`, { method: "POST" }),
  rerun: (id: string) => request<Run>(`/api/runs/${id}/rerun`, { method: "POST" }),
  deleteRun: (id: string) => request<{ deleted: boolean }>(`/api/runs/${id}`, { method: "DELETE" }),
};

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

// Typed client for the alert service's public API. All calls run in the browser (CORS allowed for the
// dashboard origin), so the dashboard is a static shell plus live, polled data.

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080";

export type Severity = "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFO";
export type IncidentStatus =
  | "OPEN"
  | "INVESTIGATING"
  | "PENDING_APPROVAL"
  | "NEEDS_HUMAN"
  | "FAILED"
  | "APPROVED"
  | "REJECTED"
  | "RESOLVED";

export interface IncidentSummary {
  id: string;
  title: string;
  status: IncidentStatus;
  severity: Severity;
  affectedServices: string[];
  alertCount: number;
  firstAlertAt: string;
  summarizedAt: string | null;
  notifiedAt: string | null;
  timeToSummarySeconds: number | null;
  rootCauseCategory: string | null;
  confidence: number | null;
  createdAt: string;
}

export interface Evidence {
  source: string;
  finding: string;
}

export interface RootCause {
  category: string;
  root_cause_service: string;
  hypothesis: string;
  confidence: number;
  evidence: Evidence[];
}

export interface Guardrail {
  allowed: boolean;
  violations: string[];
  original_action: string | null;
}

export interface ProposedAction {
  action: string;
  target: string;
  risk_level: "low" | "medium" | "high";
  steps: string[];
  rollback_plan: string;
  rationale: string;
  runbook_id: string | null;
  dry_run: boolean;
  guardrail?: Guardrail | null;
}

export interface TraceStep {
  ts: string;
  elapsed_ms: number;
  agent: string;
  kind: "llm" | "tool" | "decision" | "guardrail" | "error";
  title: string;
  detail: Record<string, unknown>;
}

export interface LlmUsage {
  llm_calls: number;
  failed_calls: number;
  tool_calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  llm_latency_ms: number;
  estimated_cost_usd: number;
  by_agent: Record<string, { calls: number; failures: number; tokens: number; latency_ms: number; models: string[] }>;
}

export interface Alert {
  id: string;
  fingerprint: string;
  source: string;
  service: string;
  severity: Severity;
  message: string;
  timestamp: string;
  receivedAt: string;
  labels: Record<string, string>;
}

export interface IncidentDetail {
  id: string;
  title: string;
  status: IncidentStatus;
  severity: Severity;
  affectedServices: string[];
  summary: string | null;
  rootCause: RootCause | null;
  proposedAction: ProposedAction | null;
  reasoningTrace: TraceStep[] | null;
  llmUsage: LlmUsage | null;
  execution: Record<string, unknown> | null;
  firstAlertAt: string;
  summarizedAt: string | null;
  notifiedAt: string | null;
  timeToSummarySeconds: number | null;
  decidedAt: string | null;
  decidedBy: string | null;
  decisionComment: string | null;
  createdAt: string;
  updatedAt: string;
  allowedTransitions: IncidentStatus[];
  alerts: Alert[];
}

export interface Page<T> {
  items: T[];
  page: number;
  size: number;
  totalItems: number;
  totalPages: number;
}

export interface MetricsSummary {
  totalAlerts: number;
  groupedAlerts: number;
  totalIncidents: number;
  noiseReductionPercent: number | null;
  avgSecondsToSummary: number | null;
  p50SecondsToSummary: number | null;
  p95SecondsToSummary: number | null;
  avgSecondsToNotification: number | null;
  avgCostUsd: number | null;
  avgTotalTokens: number | null;
  incidentsByStatus: Record<string, number>;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
    cache: "no-store",
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const problem = await response.json();
      detail = problem.detail ?? problem.title ?? detail;
    } catch {
      // body wasn't JSON
    }
    throw new ApiError(detail, response.status);
  }
  return response.json() as Promise<T>;
}

export const api = {
  incidents: (status?: IncidentStatus, size = 50) =>
    request<Page<IncidentSummary>>(`/api/incidents?size=${size}${status ? `&status=${status}` : ""}`),
  incident: (id: string) => request<IncidentDetail>(`/api/incidents/${encodeURIComponent(id)}`),
  metrics: () => request<MetricsSummary>("/api/metrics/summary"),
  decide: (id: string, decision: "approve" | "reject", decidedBy: string, comment: string) =>
    request<IncidentDetail>(`/api/incidents/${encodeURIComponent(id)}/${decision}`, {
      method: "POST",
      body: JSON.stringify({ decidedBy, comment: comment || null }),
    }),
};

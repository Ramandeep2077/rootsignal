// Demo mode (NEXT_PUBLIC_DEMO_MODE=true): the hosted, read-only site. Data comes from a snapshot of real eval
// incidents (public/demo-snapshot.json, written by `make demo-snapshot`); approve/reject run only in this tab.

import type { IncidentDetail, IncidentStatus, IncidentSummary, MetricsSummary, Page } from "./api";
import { ApiError } from "./errors";

export const DEMO_MODE = process.env.NEXT_PUBLIC_DEMO_MODE === "true";
export const REPO_URL = process.env.NEXT_PUBLIC_REPO_URL ?? "https://github.com/Ramandeep2077/rootsignal";

export interface EvalLabel {
  scenario: string;
  seed: number;
  profile: string;
  truthCategory: string;
  truthService: string;
  truthSummary: string;
  predictedCategory: string | null;
  categoryCorrect: boolean;
  judgeScore: number | null;
}

export interface Snapshot {
  generatedAt: string;
  source: string;
  incidents: IncidentDetail[];
  metrics: MetricsSummary;
  labels: Record<string, EvalLabel>;
}

let snapshot: Promise<Snapshot> | null = null;
// Decisions made in this tab, layered over the snapshot (never sent anywhere).
const decisions = new Map<string, Partial<IncidentDetail>>();

export function loadSnapshot(): Promise<Snapshot> {
  snapshot ??= fetch("/demo-snapshot.json").then((r) => {
    if (!r.ok) throw new Error(`demo snapshot missing (${r.status})`);
    return r.json() as Promise<Snapshot>;
  });
  return snapshot;
}

function withDecision(incident: IncidentDetail): IncidentDetail {
  return { ...incident, ...decisions.get(incident.id) };
}

function summary(i: IncidentDetail): IncidentSummary {
  return {
    id: i.id,
    title: i.title,
    status: i.status,
    severity: i.severity,
    affectedServices: i.affectedServices,
    alertCount: i.alerts.length,
    firstAlertAt: i.firstAlertAt,
    summarizedAt: i.summarizedAt,
    notifiedAt: i.notifiedAt,
    timeToSummarySeconds: i.timeToSummarySeconds,
    rootCauseCategory: i.rootCause?.category ?? null,
    confidence: i.rootCause?.confidence ?? null,
    createdAt: i.createdAt,
  };
}

export const demoApi = {
  async incidents(status?: IncidentStatus, size = 50): Promise<Page<IncidentSummary>> {
    const all = (await loadSnapshot()).incidents.map(withDecision).filter((i) => !status || i.status === status);
    return { items: all.slice(0, size).map(summary), page: 0, size, totalItems: all.length, totalPages: 1 };
  },

  async incident(id: string): Promise<IncidentDetail> {
    const found = (await loadSnapshot()).incidents.find((i) => i.id === id);
    if (!found) throw new ApiError("Incident not found", 404);
    return withDecision(found);
  },

  async metrics(): Promise<MetricsSummary> {
    return (await loadSnapshot()).metrics;
  },

  async decide(id: string, decision: "approve" | "reject", decidedBy: string, comment: string) {
    const incident = await demoApi.incident(id);
    if (incident.status !== "PENDING_APPROVAL") throw new ApiError("Only incidents pending approval can be decided", 409);
    const now = new Date().toISOString();
    const action = incident.proposedAction;
    decisions.set(id, {
      status: decision === "approve" ? "APPROVED" : "REJECTED",
      decidedAt: now,
      decidedBy,
      decisionComment: comment || null,
      allowedTransitions: ["RESOLVED"],
      // Mirrors the agent service's dry-run executor record.
      execution:
        decision === "approve" && action
          ? {
              status: "simulated",
              dry_run: true,
              action: action.action,
              target: action.target,
              approved_by: decidedBy,
              plan: action.steps.map((step) => `[dry-run] ${step}`),
              rollback_plan: action.rollback_plan,
              note: "Demo site: decision kept in this browser tab only; no system was contacted.",
              at: now,
            }
          : null,
    });
    return demoApi.incident(id);
  },

  async label(id: string): Promise<EvalLabel | null> {
    return (await loadSnapshot()).labels[id] ?? null;
  },
};

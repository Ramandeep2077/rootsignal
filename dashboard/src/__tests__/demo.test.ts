import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, type IncidentDetail } from "@/lib/api";
import { demoApi } from "@/lib/demo";

function incident(id: string, status: IncidentDetail["status"]): IncidentDetail {
  return {
    id,
    title: `incident ${id}`,
    status,
    severity: "CRITICAL",
    affectedServices: ["payments"],
    summary: null,
    rootCause: { category: "bad_deployment", root_cause_service: "payments", hypothesis: "", confidence: 0.9, evidence: [] },
    proposedAction: {
      action: "rollback_deployment",
      target: "payments",
      risk_level: "low",
      steps: ["roll back"],
      rollback_plan: "redeploy",
      rationale: "",
      runbook_id: "bad-deployment-rollback",
      dry_run: true,
    },
    reasoningTrace: null,
    llmUsage: null,
    execution: null,
    firstAlertAt: "2026-10-26T21:00:00Z",
    summarizedAt: null,
    notifiedAt: null,
    timeToSummarySeconds: null,
    decidedAt: null,
    decidedBy: null,
    decisionComment: null,
    createdAt: "2026-10-26T21:00:00Z",
    updatedAt: "2026-10-26T21:00:00Z",
    allowedTransitions: ["APPROVED", "REJECTED"],
    alerts: [],
  };
}

const snapshot = {
  generatedAt: "2026-10-26T22:00:00Z",
  source: "routed profile, seed 1, 2 eval runs",
  incidents: [incident("a", "PENDING_APPROVAL"), incident("b", "NEEDS_HUMAN")],
  metrics: {},
  labels: {},
};

describe("demo api", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(snapshot))));
  });

  it("lists and filters snapshot incidents", async () => {
    expect((await demoApi.incidents()).totalItems).toBe(2);
    const pending = await demoApi.incidents("NEEDS_HUMAN");
    expect(pending.items.map((i) => i.id)).toEqual(["b"]);
    expect(pending.items[0].rootCauseCategory).toBe("bad_deployment");
  });

  it("returns a 404 ApiError for unknown incidents", async () => {
    await expect(demoApi.incident("missing")).rejects.toMatchObject({ status: 404 });
  });

  it("approves locally with a dry-run execution, and only from pending approval", async () => {
    const approved = await demoApi.decide("a", "approve", "alex", "");
    expect(approved.status).toBe("APPROVED");
    expect(approved.decidedBy).toBe("alex");
    expect(approved.execution).toMatchObject({ status: "simulated", dry_run: true, plan: ["[dry-run] roll back"] });
    await expect(demoApi.decide("a", "reject", "alex", "")).rejects.toBeInstanceOf(ApiError);
  });
});

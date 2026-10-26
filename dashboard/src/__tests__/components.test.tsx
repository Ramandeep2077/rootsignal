import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { collapseDuplicates } from "@/components/alert-timeline";
import { SeverityBadge, StatusBadge } from "@/components/badges";
import { DecisionPanel } from "@/components/decision-panel";
import type { Alert, IncidentDetail } from "@/lib/api";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const alert = (id: string, fingerprint: string, at: string): Alert => ({
  id, fingerprint, source: "prometheus", service: "checkout", severity: "HIGH", message: `m ${id}`,
  timestamp: at, receivedAt: at, labels: {},
});

const incident = (overrides: Partial<IncidentDetail> = {}): IncidentDetail => ({
  id: "inc-1", title: "Checkout errors", status: "PENDING_APPROVAL", severity: "CRITICAL",
  affectedServices: ["checkout"], summary: "s", rootCause: null,
  proposedAction: {
    action: "increase_connection_pool", target: "checkout", risk_level: "low", steps: ["Raise pool to 100"],
    rollback_plan: "Restore 50", rationale: "Pool saturated", runbook_id: "db-connection-pool-exhaustion",
    dry_run: true, guardrail: { allowed: true, violations: [], original_action: "increase_connection_pool" },
  },
  reasoningTrace: [], llmUsage: null, execution: null, firstAlertAt: "", summarizedAt: null, notifiedAt: null,
  timeToSummarySeconds: 10, decidedAt: null, decidedBy: null, decisionComment: null, createdAt: "", updatedAt: "",
  allowedTransitions: ["APPROVED", "REJECTED"], alerts: [], ...overrides,
});

describe("alert timeline", () => {
  it("collapses duplicates by fingerprint in arrival order", () => {
    const rows = collapseDuplicates([
      alert("2", "b", "2026-01-01T00:00:02Z"),
      alert("1", "a", "2026-01-01T00:00:01Z"),
      alert("3", "a", "2026-01-01T00:00:03Z"),
    ]);
    expect(rows.map((r) => [r.alert.id, r.count])).toEqual([["1", 2], ["2", 1]]);
  });
});

describe("badges", () => {
  it("always render a text label next to the colour", () => {
    render(<><StatusBadge status="PENDING_APPROVAL" /><SeverityBadge severity="CRITICAL" /></>);
    expect(screen.getByText("Pending approval")).toBeTruthy();
    expect(screen.getByText("Critical")).toBeTruthy();
  });
});

describe("decision panel", () => {
  it("requires a name before approving", () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    render(<DecisionPanel incident={incident()} onDecided={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(screen.getByText(/Enter your name/)).toBeTruthy();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("posts the decision with the approver's name", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(incident({ status: "APPROVED" })), { status: 200 }),
    );
    const onDecided = vi.fn();
    render(<DecisionPanel incident={incident()} onDecided={onDecided} />);
    fireEvent.change(screen.getByPlaceholderText("e.g. alex"), { target: { value: "sam" } });
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(onDecided).toHaveBeenCalled());
    const [url, init] = fetchSpy.mock.calls[0];
    expect(String(url)).toMatch(/\/api\/incidents\/inc-1\/approve$/);
    expect(JSON.parse(String(init?.body))).toEqual({ decidedBy: "sam", comment: null });
  });

  it("shows blocked guardrails and hides the buttons once decided", () => {
    render(<DecisionPanel incident={incident({
      status: "NEEDS_HUMAN",
      proposedAction: { ...incident().proposedAction!, action: "escalate_to_human",
        guardrail: { allowed: false, violations: ["destructive or unsafe content: drop/truncate data"], original_action: "drop_table" } },
    })} onDecided={() => {}} />);
    expect(screen.getByText(/blocked the original proposal/)).toBeTruthy();
    expect(screen.getByText(/drop\/truncate data/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
  });
});

"use client";

import { useState } from "react";
import { api, type IncidentDetail } from "@/lib/api";
import { humanize } from "@/lib/format";

const RISK_TONE = { low: "var(--good)", medium: "var(--warning)", high: "var(--critical)" } as const;

export function DecisionPanel({ incident, onDecided }: { incident: IncidentDetail; onDecided: () => void }) {
  const action = incident.proposedAction;
  const [name, setName] = useState("");
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pending = incident.status === "PENDING_APPROVAL";

  async function decide(decision: "approve" | "reject") {
    if (!name.trim()) {
      setError("Enter your name so the decision is attributable.");
      return;
    }
    setBusy(decision);
    setError(null);
    try {
      await api.decide(incident.id, decision, name.trim(), comment.trim());
      onDecided();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  if (!action) {
    return (
      <Card title="Proposed action">
        <p className="text-sm text-ink-2">No action proposed yet.</p>
      </Card>
    );
  }

  const guardrail = action.guardrail;
  return (
    <Card title="Proposed action">
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <code className="rounded bg-surface-2 px-2 py-1 font-mono text-sm font-semibold">{action.action}</code>
          <span className="text-sm text-ink-2">on</span>
          <code className="rounded bg-surface-2 px-2 py-1 font-mono text-sm">{action.target}</code>
          <span className="inline-flex items-center gap-1.5 rounded-full border border-line px-2 py-0.5 text-xs">
            <span aria-hidden className="h-2 w-2 rounded-full" style={{ background: RISK_TONE[action.risk_level] }} />
            {humanize(action.risk_level)} risk
          </span>
          {action.dry_run && (
            <span className="rounded-full border border-line px-2 py-0.5 text-xs text-ink-2">Dry run</span>
          )}
        </div>

        <p className="text-sm text-ink-2">{action.rationale}</p>

        <div>
          <h4 className="mb-1 text-xs font-medium uppercase tracking-wide text-muted">Steps</h4>
          <ol className="list-decimal space-y-1 pl-5 text-sm">
            {action.steps.map((step, i) => (
              <li key={i}>{step}</li>
            ))}
          </ol>
        </div>
        <div>
          <h4 className="mb-1 text-xs font-medium uppercase tracking-wide text-muted">Rollback plan</h4>
          <p className="text-sm">{action.rollback_plan}</p>
        </div>

        {guardrail && (
          <div className="rounded-md border border-line bg-surface-2 px-3 py-2 text-sm">
            <div className="flex items-center gap-2 font-medium">
              <span
                aria-hidden
                className="h-2 w-2 rounded-full"
                style={{ background: guardrail.allowed ? "var(--good)" : "var(--critical)" }}
              />
              Guardrails: {guardrail.allowed ? "passed" : "blocked the original proposal"}
            </div>
            {!guardrail.allowed && (
              <ul className="mt-1 list-disc pl-5 text-ink-2">
                {guardrail.original_action && <li>Original action: {guardrail.original_action}</li>}
                {guardrail.violations.map((v) => (
                  <li key={v}>{v}</li>
                ))}
              </ul>
            )}
          </div>
        )}
        {action.runbook_id && (
          <p className="text-xs text-muted">
            From runbook <code className="font-mono">{action.runbook_id}</code>
          </p>
        )}

        {pending ? (
          <div className="space-y-3 border-t border-line pt-4">
            <p className="text-sm text-ink-2">
              Nothing runs until a human approves. Approval triggers a <strong>dry run</strong> only.
            </p>
            <div className="grid gap-2 sm:grid-cols-2">
              <label className="text-sm">
                <span className="mb-1 block text-xs text-muted">Your name</span>
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="w-full rounded-md border border-line bg-page px-3 py-1.5 outline-none focus:border-accent"
                  placeholder="e.g. alex"
                />
              </label>
              <label className="text-sm">
                <span className="mb-1 block text-xs text-muted">Comment (optional)</span>
                <input
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  className="w-full rounded-md border border-line bg-page px-3 py-1.5 outline-none focus:border-accent"
                  placeholder="why"
                />
              </label>
            </div>
            {error && <p className="text-sm text-critical">{error}</p>}
            <div className="flex gap-2">
              <button
                onClick={() => decide("approve")}
                disabled={busy !== null}
                className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
              >
                {busy === "approve" ? "Approving…" : "Approve"}
              </button>
              <button
                onClick={() => decide("reject")}
                disabled={busy !== null}
                className="rounded-md border border-line px-4 py-2 text-sm font-medium hover:bg-surface-2 disabled:opacity-50"
              >
                {busy === "reject" ? "Rejecting…" : "Reject"}
              </button>
            </div>
          </div>
        ) : (
          incident.decidedBy && (
            <p className="border-t border-line pt-3 text-sm text-ink-2">
              {humanize(incident.status)} by <strong className="text-ink">{incident.decidedBy}</strong>
              {incident.decisionComment ? ` — “${incident.decisionComment}”` : ""}
            </p>
          )
        )}

        {incident.execution && <Execution execution={incident.execution} />}
      </div>
    </Card>
  );
}

function Execution({ execution }: { execution: Record<string, unknown> }) {
  const plan = Array.isArray(execution.plan) ? (execution.plan as string[]) : [];
  return (
    <div className="rounded-md border border-line bg-surface-2 px-3 py-2 text-sm">
      <div className="font-medium">Execution: {humanize(String(execution.status))}</div>
      {plan.length > 0 && (
        <ul className="mt-1 space-y-0.5 font-mono text-xs text-ink-2">
          {plan.map((line, i) => (
            <li key={i}>{line}</li>
          ))}
        </ul>
      )}
      {typeof execution.note === "string" && <p className="mt-1 text-xs text-muted">{execution.note}</p>}
    </div>
  );
}

export function Card({ title, children, aside }: { title: string; children: React.ReactNode; aside?: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-line bg-surface p-4">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">{title}</h3>
        {aside}
      </div>
      {children}
    </section>
  );
}

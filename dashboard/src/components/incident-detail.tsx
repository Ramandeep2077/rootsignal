"use client";

import Link from "next/link";
import { use } from "react";
import { api, ApiError } from "@/lib/api";
import { formatCompact, formatDuration, formatRelative, formatUsd, humanize } from "@/lib/format";
import { usePoll } from "@/lib/use-poll";
import { AlertTimeline } from "./alert-timeline";
import { SeverityBadge, StatusBadge } from "./badges";
import { Card, DecisionPanel } from "./decision-panel";
import { EvalLabelStrip } from "./demo-banner";
import { ErrorBanner } from "./error-banner";
import { ReasoningTrace } from "./reasoning-trace";

export function IncidentDetailView({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data: incident, error, refresh } = usePoll(() => api.incident(id), 3000, [id]);

  if (error instanceof ApiError && error.status === 404) {
    return (
      <p className="text-ink-2">
        Incident not found. <Link className="text-accent underline" href="/incidents">Back to incidents</Link>
      </p>
    );
  }
  if (!incident) return error ? <ErrorBanner error={error} /> : <DetailSkeleton />;

  const rootCause = incident.rootCause;
  const usage = incident.llmUsage;
  return (
    <div className="space-y-5">
      <div>
        <Link href="/incidents" className="text-sm text-ink-2 hover:text-ink">
          ← Incidents
        </Link>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <StatusBadge status={incident.status} />
          <SeverityBadge severity={incident.severity} />
          <span className="text-xs text-muted">opened {formatRelative(incident.createdAt)}</span>
        </div>
        <h1 className="mt-2 text-xl font-semibold">{incident.title}</h1>
        <p className="mt-1 text-sm text-ink-2">{incident.affectedServices.join(" · ")}</p>
      </div>

      {error && <ErrorBanner error={error} />}

      <EvalLabelStrip id={incident.id} />

      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Fact label="Alerts grouped" value={String(incident.alerts.length)} />
        <Fact label="Time to summary" value={formatDuration(incident.timeToSummarySeconds)} />
        <Fact label="Tokens" value={usage ? formatCompact(usage.total_tokens) : "—"} />
        <Fact label="Cost" value={usage ? formatUsd(usage.estimated_cost_usd) : "—"} />
      </dl>

      {incident.summary && (
        <Card title="Summary">
          <p className="text-sm leading-relaxed">{incident.summary}</p>
        </Card>
      )}

      <div className="grid gap-5 lg:grid-cols-2">
        <div className="space-y-5">
          <Card
            title="Root cause"
            aside={rootCause && <span className="tabular text-xs text-ink-2">{Math.round(rootCause.confidence * 100)}% confidence</span>}
          >
            {rootCause ? (
              <div className="space-y-3 text-sm">
                <div className="flex flex-wrap gap-2">
                  <code className="rounded bg-surface-2 px-2 py-1 font-mono font-semibold">{rootCause.category}</code>
                  <span className="text-ink-2">in</span>
                  <code className="rounded bg-surface-2 px-2 py-1 font-mono">{rootCause.root_cause_service}</code>
                </div>
                <p>{rootCause.hypothesis}</p>
                <div>
                  <h4 className="mb-1 text-xs font-medium uppercase tracking-wide text-muted">Evidence</h4>
                  <ul className="space-y-1.5">
                    {rootCause.evidence.map((e, i) => (
                      <li key={i} className="flex gap-2">
                        <span className="w-16 shrink-0 text-xs uppercase tracking-wide text-muted">{e.source}</span>
                        <span className="text-ink-2">{e.finding}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            ) : (
              <p className="text-sm text-ink-2">
                {incident.status === "INVESTIGATING" || incident.status === "OPEN"
                  ? "The investigator agent is gathering evidence…"
                  : "No root cause determined."}
              </p>
            )}
          </Card>
          <DecisionPanel incident={incident} onDecided={refresh} />
        </div>

        <div className="space-y-5">
          <Card title="Agent reasoning trace">
            <ReasoningTrace steps={incident.reasoningTrace ?? []} />
          </Card>
          {usage && (
            <Card title="Model usage">
              <table className="w-full text-sm">
                <thead className="text-xs text-muted">
                  <tr>
                    <th className="pb-1 text-left font-medium">Agent</th>
                    <th className="pb-1 text-left font-medium">Model</th>
                    <th className="pb-1 text-right font-medium">Calls</th>
                    <th className="pb-1 text-right font-medium">Tokens</th>
                    <th className="pb-1 text-right font-medium">Latency</th>
                  </tr>
                </thead>
                <tbody className="tabular">
                  {Object.entries(usage.by_agent).map(([agent, u]) => (
                    <tr key={agent} className="border-t border-line">
                      <td className="py-1.5">{humanize(agent)}</td>
                      <td className="py-1.5 font-mono text-xs text-ink-2">{u.models.join(", ")}</td>
                      <td className="py-1.5 text-right">
                        {u.calls}
                        {u.failures > 0 && <span className="text-critical"> ({u.failures} failed)</span>}
                      </td>
                      <td className="py-1.5 text-right">{u.tokens.toLocaleString()}</td>
                      <td className="py-1.5 text-right">{formatDuration(u.latency_ms / 1000)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="mt-2 text-xs text-muted">
                {usage.tool_calls} MCP tool calls · {usage.prompt_tokens.toLocaleString()} prompt /{" "}
                {usage.completion_tokens.toLocaleString()} completion tokens
              </p>
            </Card>
          )}
        </div>
      </div>

      <Card title="Alert timeline">
        <AlertTimeline alerts={incident.alerts} />
      </Card>
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-line bg-surface px-4 py-3">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="mt-1 text-lg font-semibold">{value}</dd>
    </div>
  );
}

export function DetailSkeleton() {
  return (
    <div className="space-y-4" aria-busy>
      <div className="h-6 w-1/2 animate-pulse rounded bg-surface-2" />
      <div className="grid grid-cols-4 gap-3">
        {Array.from({ length: 4 }, (_, i) => (
          <div key={i} className="h-16 animate-pulse rounded-lg bg-surface-2" />
        ))}
      </div>
      <div className="h-64 animate-pulse rounded-lg bg-surface-2" />
    </div>
  );
}

"use client";

import Link from "next/link";
import { useState } from "react";
import { api, type IncidentSummary, type MetricsSummary } from "@/lib/api";
import { DEMO_MODE } from "@/lib/demo";
import { formatCompact, formatDuration, formatPercent, formatUsd, humanize } from "@/lib/format";
import { usePoll } from "@/lib/use-poll";
import { ErrorBanner } from "./error-banner";

const STATUS_ORDER = ["PENDING_APPROVAL", "INVESTIGATING", "NEEDS_HUMAN", "APPROVED", "REJECTED", "FAILED", "OPEN", "RESOLVED"];

export function MetricsView() {
  const metrics = usePoll(() => api.metrics(), 5000);
  const incidents = usePoll(() => api.incidents(undefined, 30), 5000);
  const m = metrics.data;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold">Metrics</h1>
        <p className="text-sm text-ink-2">
          {DEMO_MODE
            ? "Operational metrics for the incidents in this snapshot, computed as the alert service does."
            : "Live operational metrics from the alert service."}{" "}
          Evaluation results (accuracy, guardrails, model comparison) are in{" "}
          <code className="font-mono text-xs">evals/EVALS.md</code>.
        </p>
      </div>
      {metrics.error && <ErrorBanner error={metrics.error} />}

      <div className="grid gap-3 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,2fr)]">
        <div className="rounded-lg border border-line bg-surface p-5">
          <div className="text-sm text-ink-2">Alert-to-incident noise reduction</div>
          <div className="mt-2 text-5xl font-semibold">{formatPercent(m?.noiseReductionPercent, 1)}</div>
          <p className="mt-2 text-sm text-ink-2">
            {m ? (
              <>
                {formatCompact(m.groupedAlerts)} grouped alerts became {formatCompact(m.totalIncidents)} incidents.
              </>
            ) : (
              "Loading…"
            )}
          </p>
        </div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <Tile label="Alerts received" value={formatCompact(m?.totalAlerts)} />
          <Tile label="Incidents" value={formatCompact(m?.totalIncidents)} />
          <Tile
            label="Avg time to summary"
            value={formatDuration(m?.avgSecondsToSummary)}
            note={m ? `p50 ${formatDuration(m.p50SecondsToSummary)} · p95 ${formatDuration(m.p95SecondsToSummary)}` : undefined}
          />
          <Tile label="Avg time to notification" value={formatDuration(m?.avgSecondsToNotification)} />
          <Tile label="Cost per incident" value={formatUsd(m?.avgCostUsd)} note="local open-weight models" />
          <Tile label="Tokens per incident" value={formatCompact(m?.avgTotalTokens)} />
        </div>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        {m && <StatusChart metrics={m} />}
        {incidents.data && <TimeToSummaryChart incidents={incidents.data.items} />}
      </div>
    </div>
  );
}

function Tile({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="rounded-lg border border-line bg-surface px-4 py-3">
      <div className="text-xs text-ink-2">{label}</div>
      <div className="mt-1 text-2xl font-semibold">{value}</div>
      {note && <div className="mt-0.5 text-xs text-muted">{note}</div>}
    </div>
  );
}

function ChartCard({ title, children, table }: { title: string; children: React.ReactNode; table: React.ReactNode }) {
  const [showTable, setShowTable] = useState(false);
  return (
    <section className="rounded-lg border border-line bg-surface p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold">{title}</h2>
        <button onClick={() => setShowTable((s) => !s)} className="text-xs text-ink-2 hover:text-ink">
          {showTable ? "Show chart" : "Show table"}
        </button>
      </div>
      {showTable ? table : children}
    </section>
  );
}

/** Single series: one accent hue; every bar is direct-labelled with its value, so no legend is needed. */
function StatusChart({ metrics }: { metrics: MetricsSummary }) {
  const rows = STATUS_ORDER.filter((s) => metrics.incidentsByStatus[s]).map((s) => [s, metrics.incidentsByStatus[s]] as const);
  const max = Math.max(1, ...rows.map(([, n]) => n));
  return (
    <ChartCard
      title="Incidents by status"
      table={
        <table className="tabular w-full text-sm">
          <tbody>
            {rows.map(([status, n]) => (
              <tr key={status} className="border-t border-line first:border-0">
                <td className="py-1.5">{humanize(status)}</td>
                <td className="py-1.5 text-right">{n}</td>
              </tr>
            ))}
          </tbody>
        </table>
      }
    >
      {rows.length === 0 ? (
        <p className="text-sm text-ink-2">No incidents yet.</p>
      ) : (
        <ul className="space-y-2">
          {rows.map(([status, n]) => (
            <li key={status} className="group grid grid-cols-[9rem_1fr] items-center gap-3 text-sm" title={`${humanize(status)}: ${n}`}>
              <span className="text-ink-2">{humanize(status)}</span>
              <span className="flex items-center gap-2">
                <span className="h-3 rounded-r-[4px] bg-accent group-hover:opacity-80" style={{ width: `${(n / max) * 85}%` }} />
                <span className="tabular text-xs text-ink">{n}</span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </ChartCard>
  );
}

function TimeToSummaryChart({ incidents }: { incidents: IncidentSummary[] }) {
  const data = incidents.filter((i) => i.timeToSummarySeconds !== null).slice(0, 20).reverse();
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(1, ...data.map((i) => i.timeToSummarySeconds ?? 0));
  const ticks = [0, max / 2, max];
  return (
    <ChartCard
      title="Time to summary, last 20 analysed incidents"
      table={
        <table className="tabular w-full text-sm">
          <tbody>
            {data.map((i) => (
              <tr key={i.id} className="border-t border-line first:border-0">
                <td className="max-w-[16rem] truncate py-1.5">
                  <Link href={`/incidents/${i.id}`} className="hover:underline">{i.title}</Link>
                </td>
                <td className="py-1.5 text-right">{formatDuration(i.timeToSummarySeconds)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      }
    >
      {data.length === 0 ? (
        <p className="text-sm text-ink-2">No analysed incidents yet.</p>
      ) : (
        <div className="relative pl-12">
          <div className="relative flex h-44 items-end justify-center gap-[2px] border-b border-axis">
            {ticks.slice(1).map((t) => (
              <div key={t} className="pointer-events-none absolute inset-x-0 border-t border-grid" style={{ bottom: `${(t / max) * 100}%` }}>
                <span className="tabular absolute -top-2 right-full mr-2 whitespace-nowrap text-[10px] text-muted">{formatDuration(t)}</span>
              </div>
            ))}
            {data.map((incident, i) => (
              <Link
                key={incident.id}
                href={`/incidents/${incident.id}`}
                onMouseEnter={() => setHover(i)}
                onMouseLeave={() => setHover(null)}
                onFocus={() => setHover(i)}
                onBlur={() => setHover(null)}
                aria-label={`${incident.title}: ${formatDuration(incident.timeToSummarySeconds)}`}
                className="relative flex h-full max-w-8 flex-1 items-end"
              >
                <span
                  className="w-full rounded-t-[4px] bg-accent"
                  style={{ height: `${((incident.timeToSummarySeconds ?? 0) / max) * 100}%`, opacity: hover === null || hover === i ? 1 : 0.45 }}
                />
              </Link>
            ))}
          </div>
          {hover !== null && data[hover] && (
            <div className="pointer-events-none absolute -top-2 left-1/2 z-10 -translate-x-1/2 -translate-y-full rounded-md border border-line bg-surface px-3 py-2 text-xs shadow-sm">
              <div className="max-w-[16rem] truncate font-medium">{data[hover].title}</div>
              <div className="tabular text-ink-2">
                {formatDuration(data[hover].timeToSummarySeconds)} · {data[hover].alertCount} alerts
              </div>
            </div>
          )}
          <p className="mt-1 text-xs text-muted">Oldest → newest. Hover a bar for details; click to open.</p>
        </div>
      )}
    </ChartCard>
  );
}

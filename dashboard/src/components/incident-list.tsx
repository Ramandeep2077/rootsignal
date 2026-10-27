"use client";

import Link from "next/link";
import { useState } from "react";
import { api, type IncidentStatus } from "@/lib/api";
import { DEMO_MODE } from "@/lib/demo";
import { formatDuration, formatRelative, humanize } from "@/lib/format";
import { usePoll } from "@/lib/use-poll";
import { SeverityBadge, StatusBadge } from "./badges";
import { ErrorBanner } from "./error-banner";

const FILTERS: { label: string; status?: IncidentStatus }[] = [
  { label: "All" },
  { label: "Needs approval", status: "PENDING_APPROVAL" },
  { label: "Investigating", status: "INVESTIGATING" },
  { label: "Needs human", status: "NEEDS_HUMAN" },
  { label: "Approved", status: "APPROVED" },
  { label: "Rejected", status: "REJECTED" },
];

export function IncidentList() {
  const [filter, setFilter] = useState<IncidentStatus | undefined>(undefined);
  const { data, error, loading } = usePoll(() => api.incidents(filter), 3000, [filter]);

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Incidents</h1>
          <p className="text-sm text-ink-2">
            Alert storms grouped into incidents, investigated by the agents.{DEMO_MODE ? "" : " Updates live."}
          </p>
        </div>
        <div role="tablist" aria-label="Filter by status" className="flex flex-wrap gap-1 text-sm">
          {FILTERS.map((f) => (
            <button
              key={f.label}
              role="tab"
              aria-selected={filter === f.status}
              onClick={() => setFilter(f.status)}
              className={`rounded-md px-3 py-1.5 ${filter === f.status ? "bg-ink text-page" : "text-ink-2 hover:bg-surface-2"}`}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {error && <ErrorBanner error={error} />}

      <div className="overflow-x-auto rounded-lg border border-line bg-surface">
        <table className="w-full text-left text-sm sm:min-w-[760px]">
          <thead className="border-b border-line text-xs uppercase tracking-wide text-muted">
            <tr>
              <th className="px-4 py-2.5 font-medium">Incident</th>
              <th className="px-3 py-2.5 font-medium">Status</th>
              <th className="hidden px-3 py-2.5 font-medium sm:table-cell">Severity</th>
              <th className="hidden px-3 py-2.5 text-right font-medium sm:table-cell">Alerts</th>
              <th className="hidden px-3 py-2.5 font-medium sm:table-cell">Root cause</th>
              <th className="hidden whitespace-nowrap px-3 py-2.5 text-right font-medium sm:table-cell">Time to summary</th>
              <th className="px-4 py-2.5 text-right font-medium">Opened</th>
            </tr>
          </thead>
          <tbody>
            {loading &&
              Array.from({ length: 4 }, (_, i) => (
                <tr key={i} className="border-b border-line last:border-0">
                  <td colSpan={7} className="px-4 py-4">
                    <div className="h-4 w-2/3 animate-pulse rounded bg-surface-2" />
                  </td>
                </tr>
              ))}
            {data?.items.map((incident) => (
              <tr key={incident.id} className="border-b border-line last:border-0 hover:bg-surface-2">
                <td className="px-4 py-3">
                  <Link href={`/incidents/${incident.id}`} className="font-medium text-ink hover:underline">
                    {incident.title}
                  </Link>
                  <div className="mt-0.5 text-xs text-muted">{incident.affectedServices.join(" · ")}</div>
                </td>
                <td className="px-3 py-3">
                  <StatusBadge status={incident.status} />
                </td>
                <td className="hidden px-3 py-3 sm:table-cell">
                  <SeverityBadge severity={incident.severity} />
                </td>
                <td className="tabular hidden px-3 py-3 text-right sm:table-cell">{incident.alertCount}</td>
                <td className="hidden whitespace-nowrap px-3 py-3 text-ink-2 sm:table-cell">
                  {incident.rootCauseCategory ? (
                    <>
                      {humanize(incident.rootCauseCategory)}
                      {incident.confidence !== null && (
                        <span className="tabular ml-1 text-muted">{Math.round(incident.confidence * 100)}%</span>
                      )}
                    </>
                  ) : (
                    <span className="text-muted">—</span>
                  )}
                </td>
                <td className="tabular hidden whitespace-nowrap px-3 py-3 text-right sm:table-cell">{formatDuration(incident.timeToSummarySeconds)}</td>
                <td className="tabular whitespace-nowrap px-4 py-3 text-right text-ink-2">{formatRelative(incident.createdAt)}</td>
              </tr>
            ))}
            {data && data.items.length === 0 && (
              <tr>
                <td colSpan={7} className="px-4 py-10 text-center text-ink-2">
                  No incidents yet. Trigger one with{" "}
                  <code className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-xs">make sim SCENARIO=db_pool_exhaustion</code>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {data && <p className="text-xs text-muted">{data.totalItems} incident(s)</p>}
    </section>
  );
}

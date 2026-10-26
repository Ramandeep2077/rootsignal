"use client";

import { useMemo, useState } from "react";
import type { Alert } from "@/lib/api";
import { formatTime } from "@/lib/format";
import { SeverityBadge } from "./badges";

interface Row {
  alert: Alert;
  count: number;
}

/** Alerts in arrival order; exact duplicates (same fingerprint) are collapsed into one row with a count. */
export function collapseDuplicates(alerts: Alert[]): Row[] {
  const rows = new Map<string, Row>();
  for (const alert of [...alerts].sort((a, b) => a.receivedAt.localeCompare(b.receivedAt))) {
    const row = rows.get(alert.fingerprint);
    if (row) row.count += 1;
    else rows.set(alert.fingerprint, { alert, count: 1 });
  }
  return [...rows.values()];
}

export function AlertTimeline({ alerts }: { alerts: Alert[] }) {
  const [collapsed, setCollapsed] = useState(true);
  const rows = useMemo(
    () => (collapsed ? collapseDuplicates(alerts) : alerts.map((alert) => ({ alert, count: 1 }))),
    [alerts, collapsed],
  );
  return (
    <div>
      <div className="mb-2 flex items-center justify-between text-xs text-muted">
        <span>
          {alerts.length} alerts · {collapseDuplicates(alerts).length} distinct
        </span>
        <label className="flex items-center gap-1.5">
          <input type="checkbox" checked={collapsed} onChange={(e) => setCollapsed(e.target.checked)} />
          Collapse duplicates
        </label>
      </div>
      <ul className="max-h-[420px] divide-y divide-line overflow-auto rounded-md border border-line">
        {rows.map(({ alert, count }) => (
          <li key={alert.id} className="flex items-start gap-3 px-3 py-2 text-sm">
            <span className="tabular w-16 shrink-0 pt-0.5 text-xs text-muted">{formatTime(alert.receivedAt)}</span>
            <SeverityBadge severity={alert.severity} />
            <div className="min-w-0 flex-1">
              <div className="truncate" title={alert.message}>
                {alert.message}
              </div>
              <div className="text-xs text-muted">
                {alert.service} · {alert.source}
                {count > 1 && <span className="tabular ml-2 rounded bg-surface-2 px-1.5 text-ink-2">×{count}</span>}
              </div>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

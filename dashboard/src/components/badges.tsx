import type { IncidentStatus, Severity } from "@/lib/api";
import { humanize } from "@/lib/format";

// Status colours are reserved for state and always shown with a text label (never colour alone).
const STATUS_TONE: Record<IncidentStatus, string> = {
  OPEN: "var(--muted)",
  INVESTIGATING: "var(--accent)",
  PENDING_APPROVAL: "var(--warning)",
  NEEDS_HUMAN: "var(--serious)",
  FAILED: "var(--critical)",
  APPROVED: "var(--good)",
  REJECTED: "var(--critical)",
  RESOLVED: "var(--good)",
};

const SEVERITY_TONE: Record<Severity, string> = {
  CRITICAL: "var(--critical)",
  HIGH: "var(--serious)",
  MEDIUM: "var(--warning)",
  LOW: "var(--muted)",
  INFO: "var(--muted)",
};

function Badge({ tone, label, pulse = false }: { tone: string; label: string; pulse?: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border border-line bg-surface px-2 py-0.5 text-xs font-medium text-ink">
      <span
        aria-hidden
        className={`h-2 w-2 rounded-full ${pulse ? "animate-pulse" : ""}`}
        style={{ background: tone }}
      />
      {label}
    </span>
  );
}

export function StatusBadge({ status }: { status: IncidentStatus }) {
  return <Badge tone={STATUS_TONE[status]} label={humanize(status)} pulse={status === "INVESTIGATING"} />;
}

export function SeverityBadge({ severity }: { severity: Severity }) {
  return <Badge tone={SEVERITY_TONE[severity]} label={humanize(severity)} />;
}

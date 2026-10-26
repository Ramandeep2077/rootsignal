"use client";

import type { TraceStep } from "@/lib/api";
import { formatDuration } from "@/lib/format";

const KIND_LABEL: Record<TraceStep["kind"], string> = {
  llm: "LLM",
  tool: "Tool",
  decision: "Decision",
  guardrail: "Guardrail",
  error: "Error",
};

function detailText(detail: Record<string, unknown>): string | null {
  if (typeof detail.result === "string") return detail.result;
  if (typeof detail.text === "string") return detail.text;
  const entries = Object.entries(detail).filter(([key]) => key !== "model");
  return entries.length ? JSON.stringify(Object.fromEntries(entries), null, 2) : null;
}

export function ReasoningTrace({ steps }: { steps: TraceStep[] }) {
  if (steps.length === 0) return <p className="text-sm text-ink-2">No trace yet.</p>;
  return (
    <ol className="relative space-y-3 border-l border-axis pl-5">
      {steps.map((step, i) => {
        const text = detailText(step.detail);
        const model = typeof step.detail.model === "string" ? step.detail.model : null;
        return (
          <li key={i} className="relative">
            <span
              aria-hidden
              className="absolute -left-[25px] top-1.5 h-2.5 w-2.5 rounded-full border-2 border-surface"
              style={{ background: step.kind === "error" ? "var(--critical)" : step.kind === "guardrail" ? "var(--good)" : "var(--accent)" }}
            />
            <div className="flex flex-wrap items-baseline gap-x-2 text-sm">
              <span className="tabular text-xs text-muted">+{formatDuration(step.elapsed_ms / 1000)}</span>
              <span className="text-xs font-medium uppercase tracking-wide text-ink-2">
                {step.agent} · {KIND_LABEL[step.kind]}
              </span>
              <span className="font-medium">{step.title}</span>
              {model && <code className="rounded bg-surface-2 px-1.5 text-xs">{model}</code>}
            </div>
            {text && (
              <details className="mt-1">
                <summary className="cursor-pointer text-xs text-muted hover:text-ink">Details</summary>
                <pre className="mt-1 max-h-72 overflow-auto whitespace-pre-wrap rounded-md bg-surface-2 p-2 font-mono text-xs text-ink-2">
                  {text}
                </pre>
              </details>
            )}
          </li>
        );
      })}
    </ol>
  );
}

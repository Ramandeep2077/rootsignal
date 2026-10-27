"use client";

import { useEffect, useState } from "react";
import { DEMO_MODE, demoApi, loadSnapshot, REPO_URL, type EvalLabel } from "@/lib/demo";

/** Site-wide notice on the hosted demo: what the data is and where to run the real thing. */
export function DemoBanner() {
  const [source, setSource] = useState<string | null>(null);
  useEffect(() => {
    if (DEMO_MODE) loadSnapshot().then((s) => setSource(s.source), () => setSource(null));
  }, []);
  if (!DEMO_MODE) return null;
  return (
    <div className="border-b border-line bg-surface-2">
      <p className="mx-auto max-w-7xl px-4 py-2 text-xs text-ink-2 sm:px-6">
        <strong className="text-ink">Live demo</strong>: a read-only snapshot of real evaluation runs
        {source ? ` (${source})` : ""}, analysed by local open-weight models. Approve and Reject only change this
        browser tab.{" "}
        <a className="text-accent underline" href={REPO_URL}>
          Run the full system locally
        </a>{" "}
        ·{" "}
        <a className="text-accent underline" href={`${REPO_URL}/blob/main/evals/EVALS.md`}>
          Evaluation results
        </a>
      </p>
    </div>
  );
}

/** On the demo site, shows the scenario's ground truth next to what the agents concluded, right or wrong. */
export function EvalLabelStrip({ id }: { id: string }) {
  const [label, setLabel] = useState<EvalLabel | null>(null);
  useEffect(() => {
    if (DEMO_MODE) demoApi.label(id).then(setLabel, () => setLabel(null));
  }, [id]);
  if (!label) return null;
  return (
    <div className="rounded-lg border border-line bg-surface px-4 py-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span
          aria-hidden
          className="h-2 w-2 rounded-full"
          style={{ background: label.categoryCorrect ? "var(--good)" : "var(--critical)" }}
        />
        <span className="font-medium">
          Eval label: {label.categoryCorrect ? "diagnosis matched the ground truth" : "misdiagnosed"}
        </span>
        <span className="text-xs text-muted">
          scenario <code className="font-mono">{label.scenario}</code>, seed {label.seed}
          {label.judgeScore != null && `, judge ${label.judgeScore}/5`}
        </span>
      </div>
      <p className="mt-1 text-ink-2">
        Ground truth: <code className="font-mono">{label.truthCategory}</code> in{" "}
        <code className="font-mono">{label.truthService}</code>
        {!label.categoryCorrect && label.predictedCategory && (
          <>
            ; the agents concluded <code className="font-mono">{label.predictedCategory}</code>
          </>
        )}
        . {label.truthSummary}
      </p>
    </div>
  );
}

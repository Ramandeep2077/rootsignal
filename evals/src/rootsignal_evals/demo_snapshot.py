"""Export a read-only snapshot of real eval incidents for the dashboard's demo mode (the hosted Vercel site).

    python -m rootsignal_evals.demo_snapshot            # needs the stack running with the eval's incidents in Postgres

Picks one `routed` run per scenario (seed 1 by default, right or wrong), fetches each run's incidents from the
alert service API unchanged, computes the metrics summary the same way MetricsController does, and attaches the
eval label so the demo can show where the diagnosis matched the ground truth.
"""

from __future__ import annotations

import argparse
import json
import statistics
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from rootsignal_evals.harness import load_records
from rootsignal_sim.runner import incidents_for_run

ROOT = Path(__file__).resolve().parents[3]
RESULTS = ROOT / "evals" / "results" / "runs.jsonl"
OUT = ROOT / "dashboard" / "public" / "demo-snapshot.json"


def _ts(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def _percentile(values: list[float], q: float) -> float | None:
    """Postgres percentile_cont: linear interpolation between closest ranks."""
    if not values:
        return None
    ordered = sorted(values)
    pos = q * (len(ordered) - 1)
    low = int(pos)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def metrics(incidents: list[dict[str, Any]]) -> dict[str, Any]:
    tts, ttn, cost, tokens = [], [], [], []
    by_status: dict[str, int] = {}
    for i in incidents:
        first = _ts(i["firstAlertAt"])
        if (summarized := _ts(i["summarizedAt"])) and first:
            tts.append((summarized - first).total_seconds())
        if (notified := _ts(i["notifiedAt"])) and first:
            ttn.append((notified - first).total_seconds())
        usage = i.get("llmUsage") or {}
        if usage.get("estimated_cost_usd") is not None:
            cost.append(float(usage["estimated_cost_usd"]))
        if usage.get("total_tokens") is not None:
            tokens.append(float(usage["total_tokens"]))
        by_status[i["status"]] = by_status.get(i["status"], 0) + 1
    grouped = sum(len(i["alerts"]) for i in incidents)
    return {
        "totalAlerts": grouped,
        "groupedAlerts": grouped,
        "totalIncidents": len(incidents),
        "noiseReductionPercent": 100.0 * (1 - len(incidents) / grouped) if grouped else None,
        "avgSecondsToSummary": _mean(tts),
        "p50SecondsToSummary": _percentile(tts, 0.5),
        "p95SecondsToSummary": _percentile(tts, 0.95),
        "avgSecondsToNotification": _mean(ttn),
        "avgCostUsd": _mean(cost),
        "avgTotalTokens": _mean(tokens),
        "incidentsByStatus": dict(sorted(by_status.items())),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile", default="routed")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--api", default="http://localhost:8080")
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()

    runs = [r for r in load_records(RESULTS) if r["profile"] == args.profile and r["seed"] == args.seed]
    incidents: list[dict[str, Any]] = []
    labels: dict[str, dict[str, Any]] = {}
    with httpx.Client(base_url=args.api, timeout=10) as client:
        for run in sorted(runs, key=lambda r: r["scenario"]):
            for row in incidents_for_run(run["run_id"]):
                response = client.get(f"/api/incidents/{row['id']}")
                response.raise_for_status()
                incidents.append(response.json())
            labels[run["primary_incident_id"]] = {
                "scenario": run["scenario"],
                "seed": run["seed"],
                "profile": run["profile"],
                "truthCategory": run["ground_truth"]["category"],
                "truthService": run["ground_truth"]["root_cause_service"],
                "truthSummary": run["ground_truth"]["summary"],
                "predictedCategory": run["predicted_category"],
                "categoryCorrect": run["category_correct"],
                "judgeScore": run.get("judge_score"),
            }
    incidents.sort(key=lambda i: i["createdAt"], reverse=True)
    snapshot = {
        "generatedAt": datetime.now(UTC).isoformat(timespec="seconds"),
        "source": f"{args.profile} profile, seed {args.seed}, {len(runs)} eval runs",
        "incidents": incidents,
        "metrics": metrics(incidents),
        "labels": labels,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snapshot, indent=1), encoding="utf-8")
    print(
        f"wrote {out} ({len(incidents)} incidents from {len(runs)} runs, {out.stat().st_size / 1024:.0f} KB)"
    )


if __name__ == "__main__":
    main()

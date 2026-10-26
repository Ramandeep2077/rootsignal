"""Where simulation output goes: telemetry into Postgres (for the MCP tools), alerts to the alert service."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import httpx
import psycopg
from psycopg.types.json import Jsonb

from oncall_sim.model import SimAlert, SimulationOutput


def write_telemetry(
    conn: psycopg.Connection, run_id: str, output: SimulationOutput, *, replace: bool = True
) -> None:
    """Bulk-load logs/metrics/changes with COPY.

    ``replace`` clears earlier telemetry first. The tools query by time range, as real observability backends
    do, so back-to-back runs would otherwise see each other's overlapping 30-minute windows.
    """
    with conn.cursor() as cur:
        if replace:
            cur.execute("TRUNCATE telemetry.logs, telemetry.metrics, telemetry.deployments")
        with cur.copy("COPY telemetry.logs (run_id, ts, service, level, message, attrs) FROM STDIN") as copy:
            for line in output.logs:
                copy.write_row((run_id, line.ts, line.service, line.level, line.message, Jsonb(line.attrs)))
        with cur.copy("COPY telemetry.metrics (run_id, ts, service, metric, value) FROM STDIN") as copy:
            for point in output.metrics:
                copy.write_row((run_id, point.ts, point.service, point.metric, point.value))
        with cur.copy(
            "COPY telemetry.deployments (run_id, ts, service, kind, version, author, description, diff) FROM STDIN"
        ) as copy:
            for change in output.changes:
                copy.write_row(
                    (
                        run_id,
                        change.ts,
                        change.service,
                        change.kind,
                        change.version,
                        change.author,
                        change.description,
                        Jsonb(change.diff),
                    )
                )
    conn.commit()


@dataclass
class PostedAlert:
    id: str
    alert: SimAlert


def alert_payload(alert: SimAlert, run_id: str) -> dict:
    return {
        "source": alert.source,
        "service": alert.service,
        "severity": alert.severity,
        "message": alert.message,
        "timestamp": alert.ts.isoformat(),
        # sim_run is an opaque id that lets the evals map incidents back to runs; it reveals nothing about the cause.
        "labels": {**alert.labels, "sim_run": run_id},
    }


def post_alerts(
    client: httpx.Client,
    alerts: Sequence[SimAlert],
    run_id: str,
    *,
    burst_seconds: float = 12.0,
    sleep: Callable[[float], None] = time.sleep,
) -> list[PostedAlert]:
    """Replay alerts in order, compressing their simulated spread into ``burst_seconds`` of wall-clock time."""
    if not alerts:
        return []
    first, last = alerts[0].ts, alerts[-1].ts
    span = max((last - first).total_seconds(), 1.0)
    posted: list[PostedAlert] = []
    previous_due = 0.0
    for alert in alerts:
        due = (alert.ts - first).total_seconds() / span * burst_seconds
        if due > previous_due:
            sleep(due - previous_due)
            previous_due = due
        response = client.post("/api/alerts", json=alert_payload(alert, run_id))
        response.raise_for_status()
        posted.append(PostedAlert(response.json()["id"], alert))
    return posted

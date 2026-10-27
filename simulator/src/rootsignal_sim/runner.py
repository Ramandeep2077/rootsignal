"""Run a scenario end to end: simulate, load telemetry, replay alerts, optionally wait for the agents."""

from __future__ import annotations

import secrets
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

import httpx

from rootsignal_common.db import connect, ensure_schema
from rootsignal_common.settings import BaseServiceSettings, common_settings
from rootsignal_sim.engine import simulate
from rootsignal_sim.scenarios import get_scenario
from rootsignal_sim.sink import post_alerts, write_telemetry

ANALYSIS_DONE = ("PENDING_APPROVAL", "NEEDS_HUMAN", "FAILED")


@dataclass
class RunResult:
    run_id: str
    scenario: str
    seed: int
    window_start: datetime
    window_end: datetime
    alert_ids: list[str]
    noise_alert_ids: list[str]
    alerts_by_service: dict[str, int]
    log_lines: int
    metric_points: int
    changes: int
    ground_truth: dict[str, Any]
    posted_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["window_start"] = self.window_start.isoformat()
        data["window_end"] = self.window_end.isoformat()
        return data


def run_scenario(
    name: str,
    *,
    seed: int = 1,
    burst_seconds: float = 12.0,
    replace_telemetry: bool = True,
    settings: BaseServiceSettings | None = None,
) -> RunResult:
    settings = settings or common_settings()
    scenario = get_scenario(name)
    run_id = secrets.token_hex(6)
    output = simulate(scenario, seed=seed)

    with connect(settings.dsn) as conn:
        ensure_schema(conn)
        write_telemetry(conn, run_id, output, replace=replace_telemetry)

    with httpx.Client(base_url=settings.alert_service_url, timeout=10) as client:
        posted = post_alerts(client, output.alerts, run_id, burst_seconds=burst_seconds)

    gt = output.ground_truth
    return RunResult(
        run_id=run_id,
        scenario=name,
        seed=seed,
        window_start=output.start,
        window_end=output.end,
        alert_ids=[p.id for p in posted],
        noise_alert_ids=[p.id for p in posted if p.alert.is_noise],
        alerts_by_service=dict(Counter(a.service for a in output.alerts)),
        log_lines=len(output.logs),
        metric_points=len(output.metrics),
        changes=len(output.changes),
        ground_truth={
            "category": gt.category.value,
            "root_cause_service": gt.root_cause_service,
            "acceptable_services": list(gt.acceptable_services),
            "summary": gt.summary,
            "expected_runbook": gt.expected_runbook,
            "expected_actions": [a.value for a in gt.expected_actions],
        },
    )


def incidents_for_run(run_id: str, settings: BaseServiceSettings | None = None) -> list[dict[str, Any]]:
    """Incidents that contain this run's alerts, with how many of the run's alerts each one holds.

    Read-only query against the alert service's tables: the evaluation harness needs to join on the
    ``sim_run`` label, which the public API intentionally doesn't expose.
    """
    settings = settings or common_settings()
    with connect(settings.dsn) as conn, conn.cursor() as cur:
        cur.execute(
            """
            select i.id::text as id, i.status, i.title, i.summarized_at, i.notified_at, i.first_alert_at,
                   count(a.id) as run_alerts
            from alerts a join incidents i on i.id = a.incident_id
            where a.labels ->> 'sim_run' = %s
            group by i.id order by run_alerts desc
            """,
            (run_id,),
        )
        return list(cur.fetchall())


def wait_for_analysis(
    run_id: str,
    *,
    expected_alerts: int | None = None,
    timeout: float = 900.0,
    poll: float = 3.0,
    settings: BaseServiceSettings | None = None,
) -> list[dict[str, Any]]:
    """Block until all of this run's alerts belong to incidents and every one has finished analysis.

    Without ``expected_alerts`` a fast, small incident (e.g. the background alert) could finish before the
    main storm's group has even closed, and we'd return too early.
    """
    deadline = time.monotonic() + timeout
    incidents: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        incidents = incidents_for_run(run_id, settings)
        grouped = sum(int(i["run_alerts"]) for i in incidents)
        complete = expected_alerts is None or grouped >= expected_alerts
        if incidents and complete and all(i["status"] in ANALYSIS_DONE for i in incidents):
            return incidents
        time.sleep(poll)
    return incidents

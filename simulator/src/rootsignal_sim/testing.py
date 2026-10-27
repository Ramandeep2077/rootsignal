"""Helpers for tests in other packages: load a scenario's telemetry and turn its alerts into Kafka-like events."""

from __future__ import annotations

from typing import Any

from rootsignal_common.db import connect
from rootsignal_sim.alerting import _normalise
from rootsignal_sim.engine import simulate
from rootsignal_sim.model import SimulationOutput
from rootsignal_sim.scenarios import get_scenario
from rootsignal_sim.sink import write_telemetry


def load_scenario(dsn: str, name: str, seed: int = 1) -> SimulationOutput:
    out = simulate(get_scenario(name), seed=seed)
    with connect(dsn) as conn:
        write_telemetry(conn, f"test-{name}", out)
    return out


def as_events(out: SimulationOutput) -> list[dict[str, Any]]:
    """Alerts shaped like the alert service's Kafka events (``noise`` is test-only metadata)."""
    return [
        {
            "id": f"a{i}",
            "service": a.service,
            "severity": a.severity,
            "message": a.message,
            "labels": a.labels,
            "source": a.source,
            "fingerprint": f"{a.source}|{a.service}|{_normalise(a.message)}",
            "noise": a.is_noise,
        }
        for i, a in enumerate(out.alerts)
    ]

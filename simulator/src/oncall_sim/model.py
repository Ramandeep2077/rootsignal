"""Data types produced by the simulation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from oncall_common.taxonomy import ActionType, RootCauseCategory


@dataclass(frozen=True)
class ServiceProfile:
    """Healthy baseline for one service."""

    name: str
    rps: float
    latency_ms: float
    cpu_percent: float = 35.0
    memory_percent: float = 55.0
    disk_percent: float = 45.0
    error_rate: float = 0.003
    db_pool_max: int | None = None
    db_pool_in_use: float | None = None
    consumer_lag: float | None = None
    endpoints: tuple[str, ...] = ()


@dataclass
class LogLine:
    ts: datetime
    service: str
    level: str
    message: str
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass
class MetricPoint:
    ts: datetime
    service: str
    metric: str
    value: float


@dataclass
class Change:
    """A deployment or configuration change, as a deploy tracker would record it."""

    ts: datetime
    service: str
    kind: str  # "deploy" | "config_change" | "feature_flag"
    version: str | None
    author: str
    description: str
    diff: dict[str, Any] = field(default_factory=dict)


@dataclass
class SimAlert:
    ts: datetime
    source: str
    service: str
    severity: str
    message: str
    labels: dict[str, str] = field(default_factory=dict)
    # Not sent to the alert service: lets the evals know which alerts are unrelated background noise.
    is_noise: bool = False


@dataclass(frozen=True)
class GroundTruth:
    category: RootCauseCategory
    root_cause_service: str
    summary: str
    expected_runbook: str
    expected_actions: tuple[ActionType, ...]
    # Services an evaluator should also accept (e.g. the internal caller of a failing third party).
    acceptable_services: tuple[str, ...] = ()
    # Phrases that must be discoverable in the telemetry; asserted by tests so every scenario is solvable.
    evidence_keywords: tuple[str, ...] = ()


@dataclass
class SimulationOutput:
    scenario: str
    seed: int
    start: datetime
    end: datetime
    logs: list[LogLine]
    metrics: list[MetricPoint]
    changes: list[Change]
    alerts: list[SimAlert]
    ground_truth: GroundTruth

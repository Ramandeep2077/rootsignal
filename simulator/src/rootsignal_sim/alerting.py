"""Prometheus/Loki/synthetics-style alert rules evaluated over simulated metrics and logs.

A rule fires once its condition has held for ``for_ticks`` consecutive ticks (like Prometheus ``for:``),
then re-fires every ``repeat_ticks`` while it stays true (like Alertmanager's repeat interval). Several
sources watch the same symptom with different wording, which is exactly the duplication triage must undo.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from rootsignal_sim.model import LogLine, ServiceProfile, SimAlert

_VOLATILE = re.compile(r"\b[0-9a-f]{12,}\b|\d+(?:\.\d+)?")


def _normalise(message: str) -> str:
    return _VOLATILE.sub("#", message)


def top_error(lines: list[LogLine]) -> tuple[str, int] | None:
    """Most frequent ERROR message (grouped ignoring numbers/ids) and how many lines matched."""
    groups: Counter[str] = Counter()
    example: dict[str, str] = {}
    for line in lines:
        if line.level == "ERROR":
            key = _normalise(line.message)
            groups[key] += 1
            example.setdefault(key, line.message)
    if not groups:
        return None
    key, count = groups.most_common(1)[0]
    return example[key], count


@dataclass(frozen=True)
class Rule:
    name: str
    source: str
    condition: Callable[[dict[str, float], ServiceProfile, list[LogLine]], bool]
    severity: Callable[[dict[str, float]], str]
    message: Callable[[str, dict[str, float], ServiceProfile, list[LogLine]], str]
    services: tuple[str, ...] | None = None  # None = all services
    for_ticks: int = 2
    repeat_ticks: int = 3


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


RULES: tuple[Rule, ...] = (
    Rule(
        "HighErrorRate",
        "prometheus",
        lambda m, p, _: m["error_rate"] > 0.05,
        lambda m: "CRITICAL" if m["error_rate"] > 0.25 else "HIGH",
        lambda s, m, p, _: f"HighErrorRate: {s} 5xx ratio {_pct(m['error_rate'])} over 5m (threshold 5%)",
    ),
    Rule(
        "ErrorRateMonitor",
        "datadog",
        lambda m, p, _: m["error_rate"] > 0.08,
        lambda m: "HIGH",
        lambda s, m, p, _: (
            f"[Monitor] {s} error rate is elevated ({_pct(m['error_rate'])} of requests failing)"
        ),
        for_ticks=3,
        repeat_ticks=4,
    ),
    Rule(
        "HighLatencyP99",
        "prometheus",
        lambda m, p, _: m["latency_p99_ms"] > max(500.0, p.latency_ms * 4),
        lambda m: "HIGH",
        lambda s, m, p, _: f"HighLatencyP99: {s} p99 latency {m['latency_p99_ms']:.0f}ms (SLO 500ms)",
    ),
    Rule(
        "DBConnectionPoolSaturated",
        "prometheus",
        lambda m, p, _: (
            "db_connections_in_use" in m and m["db_connections_in_use"] >= 0.9 * m["db_connections_max"]
        ),
        lambda m: "CRITICAL",
        lambda s, m, p, _: (
            f"DBConnectionPoolSaturated: {s} pool {m['db_connections_in_use']:.0f}/"
            f"{m['db_connections_max']:.0f} connections in use"
        ),
        services=("checkout", "inventory"),
    ),
    Rule(
        "ContainerMemoryHigh",
        "prometheus",
        lambda m, p, _: m["memory_percent"] > 90,
        lambda m: "CRITICAL" if m["memory_percent"] > 96 else "HIGH",
        lambda s, m, p, _: (
            f"ContainerMemoryHigh: {s} memory working set at {m['memory_percent']:.0f}% of limit"
        ),
    ),
    Rule(
        "DiskSpaceCritical",
        "prometheus",
        lambda m, p, _: m["disk_used_percent"] > 92,
        lambda m: "CRITICAL",
        lambda s, m, p, _: f"DiskSpaceCritical: {s} volume /var/log is {m['disk_used_percent']:.0f}% full",
    ),
    Rule(
        "CPUThrottlingHigh",
        "prometheus",
        lambda m, p, _: m["cpu_throttled_percent"] > 40,
        lambda m: "MEDIUM",
        lambda s, m, p, _: (
            f"CPUThrottlingHigh: {s} {m['cpu_throttled_percent']:.0f}% of CPU periods throttled"
        ),
    ),
    Rule(
        "KafkaConsumerLagHigh",
        "prometheus",
        lambda m, p, _: m.get("kafka_consumer_lag", 0) > 10_000,
        lambda m: "HIGH",
        lambda s, m, p, _: (
            f"KafkaConsumerLagHigh: consumer group inventory-orders lag {m['kafka_consumer_lag']:.0f} "
            "messages on topic orders"
        ),
        services=("inventory",),
    ),
    Rule(
        "UpstreamRateLimited",
        "prometheus",
        lambda m, p, _: m["http_429_rate"] > 0.1,
        lambda m: "HIGH",
        lambda s, m, p, _: (
            f"UpstreamRateLimited: {s} {_pct(m['http_429_rate'])} of outbound third-party calls got HTTP 429"
        ),
    ),
    Rule(
        "TrafficDrop",
        "prometheus",
        lambda m, p, _: m["requests_per_sec"] < 0.4 * p.rps,
        lambda m: "MEDIUM",
        lambda s, m, p, _: f"TrafficDrop: {s} request rate {m['requests_per_sec']:.0f}/s, >60% below normal",
    ),
    Rule(
        "ErrorLogSpike",
        "loki",
        lambda m, p, logs: (top_error(logs) or ("", 0))[1] >= 2,
        lambda m: "HIGH",
        lambda s, m, p, logs: f'ErrorLogSpike: {s} logging errors; top message: "{top_error(logs)[0][:160]}"',
        repeat_ticks=4,
    ),
    Rule(
        "SyntheticCheckFailing",
        "synthetics",
        lambda m, p, _: m["error_rate"] > 0.2,
        lambda m: "CRITICAL",
        lambda s, m, p, logs: (
            "Synthetic check 'shop-user-journey' failing via https://shop.example.test: "
            + (top_error(logs)[0][:120] if top_error(logs) else "HTTP 502 Bad Gateway")
        ),
        services=("api-gateway",),
        repeat_ticks=4,
    ),
)


class AlertEngine:
    def __init__(self, profiles: dict[str, ServiceProfile]) -> None:
        self.profiles = profiles
        self.streak: dict[tuple[str, str], int] = {}

    def evaluate(
        self, ts: datetime, current: dict[str, dict[str, float]], logs: dict[str, list[LogLine]]
    ) -> list[SimAlert]:
        fired: list[SimAlert] = []
        for rule in RULES:
            for service, metrics in current.items():
                if rule.services is not None and service not in rule.services:
                    continue
                key = (rule.name, service)
                profile = self.profiles[service]
                if not rule.condition(metrics, profile, logs[service]):
                    self.streak[key] = 0
                    continue
                streak = self.streak.get(key, 0) + 1
                self.streak[key] = streak
                if streak >= rule.for_ticks and (streak - rule.for_ticks) % rule.repeat_ticks == 0:
                    fired.append(
                        SimAlert(
                            ts=ts,
                            source=rule.source,
                            service=service,
                            severity=rule.severity(metrics),
                            message=rule.message(service, metrics, profile, logs[service]),
                            labels={"alertname": rule.name, "env": "prod", "region": "us-east-1"},
                        )
                    )
        return fired

"""Discrete-time simulation of five microservices.

Every 30 simulated seconds each service gets baseline metrics plus noise; the scenario's fault then modifies
the affected services; degradation propagates from callees to callers (higher latency, upstream errors and
symptom logs); and Prometheus-style alert rules evaluate the result. Duplicate and cross-service alerts
therefore *emerge* from the simulation, the way they do in a real alert storm.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from oncall_common.taxonomy import DEPENDENCIES
from oncall_sim.alerting import AlertEngine
from oncall_sim.model import LogLine, MetricPoint, ServiceProfile, SimAlert, SimulationOutput

if TYPE_CHECKING:
    from oncall_sim.scenarios import Scenario

WINDOW_MINUTES = 30
TICK_SECONDS = 30
TICKS = WINDOW_MINUTES * 60 // TICK_SECONDS

# Callees before callers so propagation sees this tick's dependency state.
EVALUATION_ORDER = ("auth", "inventory", "payments", "checkout", "api-gateway")

PROFILES: dict[str, ServiceProfile] = {
    "api-gateway": ServiceProfile(
        "api-gateway",
        rps=220,
        latency_ms=85,
        cpu_percent=30,
        endpoints=("GET /v1/products", "POST /v1/cart", "POST /v1/checkout", "POST /v1/login"),
    ),
    "auth": ServiceProfile(
        "auth",
        rps=150,
        latency_ms=40,
        cpu_percent=38,
        endpoints=("POST /oauth/token", "GET /v1/userinfo"),
    ),
    "checkout": ServiceProfile(
        "checkout",
        rps=90,
        latency_ms=180,
        db_pool_max=50,
        db_pool_in_use=12,
        endpoints=("POST /v1/checkout", "GET /v1/cart"),
    ),
    "inventory": ServiceProfile(
        "inventory",
        rps=120,
        latency_ms=60,
        db_pool_max=40,
        db_pool_in_use=8,
        consumer_lag=60,
        endpoints=("GET /v1/stock", "POST /v1/reservations"),
    ),
    "payments": ServiceProfile(
        "payments",
        rps=60,
        latency_ms=260,
        cpu_percent=28,
        endpoints=("POST /v1/charges", "POST /v1/refunds"),
    ),
}

STARTUP_LOGS: dict[str, str] = {
    "api-gateway": "Started api-gateway 2.14.0 (routes loaded from routes.yaml: 14 routes, 3 clusters)",
    "auth": "Started auth 1.8.2 in 4.1s (cpu limit 500m, memory limit 1Gi, tls cert CN=auth.internal)",
    "checkout": "Started checkout 5.6.1 (db.pool.max=50, db.pool.timeout=3000ms, upstreams: inventory, payments)",
    "inventory": "Started inventory 3.1.0 (heap max 4G, consumer group inventory-orders on topic orders)",
    "payments": "Started payments 4.1.3 (providers: api.payprovider.example, fraud: api.fraudscore.example)",
}


@dataclass
class TickContext:
    """What a scenario sees and can change for one service at one tick."""

    service: str
    ts: datetime
    minute: float  # minutes since window start
    onset: float  # scenario onset (minutes since window start)
    rng: random.Random
    metrics: dict[str, float]
    profile: ServiceProfile
    logs: list[LogLine] = field(default_factory=list)
    alerts: list[SimAlert] = field(default_factory=list)

    @property
    def t(self) -> float:
        """Minutes since fault onset (negative before)."""
        return self.minute - self.onset

    @property
    def active(self) -> bool:
        return self.t >= 0

    def ramp(self, minutes: float) -> float:
        """0 before onset, rising linearly to 1 over ``minutes``."""
        if self.t <= 0:
            return 0.0
        return min(1.0, self.t / minutes)

    def log(self, level: str, message: str, **attrs) -> None:
        jitter = timedelta(seconds=self.rng.uniform(0, TICK_SECONDS - 1))
        self.logs.append(LogLine(self.ts + jitter, self.service, level, message, attrs))

    def event(self, source: str, severity: str, message: str, **labels: str) -> None:
        """Emit an alert directly (e.g. a Kubernetes event) rather than via a metric rule."""
        self.alerts.append(SimAlert(self.ts, source, self.service, severity, message, dict(labels)))

    def trace_id(self) -> str:
        return f"{self.rng.getrandbits(64):016x}"


def baseline_metrics(profile: ServiceProfile, rng: random.Random) -> dict[str, float]:
    def noisy(value: float, pct: float = 0.06) -> float:
        return max(0.0, value * rng.gauss(1.0, pct))

    metrics = {
        "requests_per_sec": noisy(profile.rps),
        "latency_p99_ms": noisy(profile.latency_ms, 0.08),
        "error_rate": max(0.0, rng.gauss(profile.error_rate, profile.error_rate / 3)),
        "cpu_percent": noisy(profile.cpu_percent),
        "cpu_throttled_percent": max(0.0, rng.gauss(1.5, 0.7)),
        "memory_percent": noisy(profile.memory_percent, 0.02),
        "disk_used_percent": noisy(profile.disk_percent, 0.01),
        "http_429_rate": 0.0,
    }
    if profile.db_pool_max is not None and profile.db_pool_in_use is not None:
        metrics["db_connections_in_use"] = round(noisy(profile.db_pool_in_use, 0.15))
        metrics["db_connections_max"] = float(profile.db_pool_max)
    if profile.consumer_lag is not None:
        metrics["kafka_consumer_lag"] = round(noisy(profile.consumer_lag, 0.3))
    return metrics


def propagate(ctx: TickContext, current: dict[str, dict[str, float]]) -> None:
    """Degraded callees make their callers slower and error-prone, and callers log the symptom."""
    m = ctx.metrics
    for dep in DEPENDENCIES[ctx.service]:
        dep_m, dep_profile = current[dep], PROFILES[dep]
        extra_latency = max(0.0, dep_m["latency_p99_ms"] - dep_profile.latency_ms * 1.5)
        extra_errors = max(0.0, dep_m["error_rate"] - dep_profile.error_rate * 3)
        timeouts = dep_m["latency_p99_ms"] > 2000
        m["latency_p99_ms"] += min(extra_latency * 0.8, 2000.0 if timeouts else extra_latency)
        m["error_rate"] += extra_errors * 0.7 + (0.12 if timeouts else 0.0)
        if timeouts and ctx.rng.random() < 0.8:
            ctx.log(
                "ERROR",
                f"timeout calling {dep} after 2000ms (POST /v1/{_dep_path(dep)})",
                trace_id=ctx.trace_id(),
                upstream=dep,
            )
        elif extra_errors > 0.03 and ctx.rng.random() < 0.8:
            ctx.log(
                "ERROR",
                f"upstream {dep} returned 503 Service Unavailable",
                trace_id=ctx.trace_id(),
                upstream=dep,
            )


def _dep_path(dep: str) -> str:
    return {"inventory": "reservations", "payments": "charges", "auth": "token", "checkout": "checkout"}.get(
        dep, dep
    )


def clamp(m: dict[str, float]) -> None:
    m["error_rate"] = min(1.0, max(0.0, m["error_rate"]))
    for key in (
        "cpu_percent",
        "memory_percent",
        "disk_used_percent",
        "cpu_throttled_percent",
        "http_429_rate",
    ):
        m[key] = min(100.0 if key != "http_429_rate" else 1.0, max(0.0, m[key]))
    if "db_connections_in_use" in m:
        m["db_connections_in_use"] = min(m["db_connections_max"], m["db_connections_in_use"])


def access_logs(ctx: TickContext) -> None:
    """Two sampled access-log lines per tick, reflecting the tick's latency and error rate."""
    m = ctx.metrics
    for _ in range(2):
        endpoint = ctx.rng.choice(ctx.profile.endpoints)
        failed = ctx.rng.random() < m["error_rate"]
        status = ctx.rng.choice((502, 503, 504)) if failed else 200
        latency = max(1, int(ctx.rng.gauss(m["latency_p99_ms"] * 0.55, m["latency_p99_ms"] * 0.1)))
        ctx.log(
            "WARN" if failed else "INFO",
            f"{endpoint} {status} {latency}ms",
            trace_id=ctx.trace_id(),
            status=status,
            latency_ms=latency,
        )


def simulate(scenario: Scenario, seed: int = 7, end: datetime | None = None) -> SimulationOutput:
    rng = random.Random(f"{scenario.name}:{seed}")
    end = (end or datetime.now(UTC)).replace(microsecond=0)
    start = end - timedelta(minutes=WINDOW_MINUTES)
    onset = scenario.onset_minute

    logs: list[LogLine] = []
    metrics: list[MetricPoint] = []
    alerts: list[SimAlert] = []
    rules = AlertEngine(PROFILES)

    for tick in range(TICKS):
        ts = start + timedelta(seconds=tick * TICK_SECONDS)
        minute = tick * TICK_SECONDS / 60
        current: dict[str, dict[str, float]] = {}
        tick_logs: dict[str, list[LogLine]] = {}
        for service in EVALUATION_ORDER:
            profile = PROFILES[service]
            ctx = TickContext(service, ts, minute, onset, rng, baseline_metrics(profile, rng), profile)
            if tick == 1:
                ctx.log("INFO", STARTUP_LOGS[service])
            scenario.effects(ctx)
            propagate(ctx, current)
            clamp(ctx.metrics)
            access_logs(ctx)
            current[service] = ctx.metrics
            tick_logs[service] = ctx.logs
            logs.extend(ctx.logs)
            alerts.extend(ctx.alerts)
            metrics.extend(
                MetricPoint(ts, service, name, round(value, 4)) for name, value in ctx.metrics.items()
            )
        alerts.extend(rules.evaluate(ts, current, tick_logs))

    alerts.extend(scenario.background_noise(start, end, rng))
    alerts.sort(key=lambda a: a.ts)
    logs.sort(key=lambda line: line.ts)
    return SimulationOutput(
        scenario=scenario.name,
        seed=seed,
        start=start,
        end=end,
        logs=logs,
        metrics=metrics,
        changes=scenario.changes(start, rng),
        alerts=alerts,
        ground_truth=scenario.ground_truth,
    )

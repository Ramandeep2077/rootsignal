"""Twelve labelled incident scenarios.

Each scenario injects one fault into the simulation and declares its ground truth. Scenarios include red
herrings (unrelated deploys, background alerts) and near-miss pairs (bad deploy vs. config change, upstream
outage vs. rate limiting, slow dependency vs. pool exhaustion) so the agent has to reason over evidence.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import ClassVar

from oncall_common.taxonomy import ActionType as A
from oncall_common.taxonomy import RootCauseCategory as C
from oncall_sim.engine import TickContext
from oncall_sim.model import Change, GroundTruth, SimAlert

# Routine changes that happen in any week; a few are added to every scenario as red herrings.
ROUTINE_CHANGES: tuple[tuple[float, str, str, str | None, str, str], ...] = (
    # (minutes relative to window start, service, kind, version, author, description)
    (-26 * 60, "auth", "deploy", "1.8.2", "ci-bot", "Bump jackson-databind and refresh base image"),
    (-47 * 60, "inventory", "deploy", "3.1.0", "ci-bot", "Batch reservation API; cache stock lookups"),
    (-20 * 60, "payments", "deploy", "4.1.3", "ci-bot", "Add idempotency keys to refunds"),
    (-6 * 60, "checkout", "config_change", None, "dev-priya", "Increase trace sampling from 5% to 10%"),
    (5, "api-gateway", "feature_flag", None, "pm-lee", "Enable 'recommendations-carousel' for 10% of users"),
    (9, "auth", "config_change", None, "dev-sam", "Raise session cache TTL from 15m to 30m"),
    (12, "inventory", "feature_flag", None, "dev-kofi", "Enable 'stock-badge' on product pages"),
)

BACKGROUND_ALERTS: tuple[tuple[str, str, str, str], ...] = (
    # (service, severity, alertname, message)
    (
        "auth",
        "LOW",
        "CertificateExpiringSoon",
        "CertificateExpiringSoon: certificate CN=sso.example.test expires in 24 days",
    ),
    ("inventory", "INFO", "JobSlow", "JobSlow: nightly reindex job 'stock-search' took 14m (expected < 10m)"),
    (
        "api-gateway",
        "LOW",
        "PodRestarted",
        "PodRestarted: api-gateway-5c9d8 restarted once in the last hour (node drain)",
    ),
    ("payments", "LOW", "BackupWarning", "BackupWarning: job payments-db-snapshot completed with 1 warning"),
    ("checkout", "INFO", "HPAScaled", "HPAScaled: checkout scaled from 4 to 5 replicas"),
)


class Scenario:
    name: ClassVar[str]
    title: ClassVar[str]
    onset_minute: ClassVar[float] = 20.0
    ground_truth: ClassVar[GroundTruth]

    def effects(self, ctx: TickContext) -> None:
        raise NotImplementedError

    def cause_changes(self, start: datetime) -> list[Change]:
        """Changes that *are* the root cause (only for change-driven scenarios)."""
        return []

    def changes(self, start: datetime, rng: random.Random) -> list[Change]:
        routine = rng.sample(ROUTINE_CHANGES, k=3)
        herrings = [
            Change(start + timedelta(minutes=minutes), svc, kind, version, author, desc)
            for minutes, svc, kind, version, author, desc in routine
        ]
        return sorted(herrings + self.cause_changes(start), key=lambda c: c.ts)

    def background_noise(self, start: datetime, end: datetime, rng: random.Random) -> list[SimAlert]:
        """One unrelated low-severity alert during the storm, from a service the fault doesn't touch."""
        candidates = [a for a in BACKGROUND_ALERTS if a[0] != self.ground_truth.root_cause_service]
        service, severity, alertname, message = rng.choice(candidates)
        ts = start + timedelta(minutes=self.onset_minute + rng.uniform(1, 8))
        return [
            SimAlert(
                min(ts, end),
                "prometheus",
                service,
                severity,
                message,
                {"alertname": alertname, "env": "prod"},
                is_noise=True,
            )
        ]

    @staticmethod
    def window_start(ctx: TickContext) -> datetime:
        return ctx.ts - timedelta(minutes=ctx.minute)


SCENARIOS: dict[str, Scenario] = {}


def register(cls: type[Scenario]) -> type[Scenario]:
    SCENARIOS[cls.name] = cls()
    return cls


@register
class DbPoolExhaustion(Scenario):
    name = "db_pool_exhaustion"
    title = "Checkout DB connection pool exhausted during a traffic surge"
    onset_minute = 19.0
    ground_truth = GroundTruth(
        C.DB_POOL_EXHAUSTION,
        "checkout",
        "A campaign traffic surge saturated checkout's 50-connection DB pool; requests time out waiting for a "
        "connection and errors cascade to api-gateway.",
        "db-connection-pool-exhaustion",
        (A.INCREASE_CONNECTION_POOL, A.SCALE_OUT),
        evidence_keywords=("Connection is not available", "active=50"),
    )

    def effects(self, ctx: TickContext) -> None:
        m, rng = ctx.metrics, ctx.rng
        if ctx.service == "api-gateway":
            if 0 <= ctx.t < 0.5:
                ctx.log("INFO", "Campaign 'fall-sale' landing page live; traffic shaping profile=burst")
            m["requests_per_sec"] *= 1 + 0.9 * ctx.ramp(2)
        if ctx.service != "checkout":
            return
        m["requests_per_sec"] *= 1 + 1.3 * ctx.ramp(2)
        if ctx.t >= -0.5:
            m["db_connections_in_use"] = 12 + 38 * ctx.ramp(1.5) + rng.uniform(-1, 1)
        if ctx.t >= 1.5:
            m["db_connections_in_use"] = 50
            m["latency_p99_ms"] = rng.uniform(2800, 3100)
            m["error_rate"] += rng.uniform(0.22, 0.32)
            m["cpu_percent"] += 10
            for _ in range(rng.randint(2, 3)):
                ctx.log(
                    "ERROR",
                    "HikariPool-1 - Connection is not available, request timed out after 3000ms "
                    f"(total=50, active=50, idle=0, waiting={rng.randint(20, 70)})",
                    trace_id=ctx.trace_id(),
                )
            if rng.random() < 0.5:
                ctx.log(
                    "WARN",
                    f"Slow request POST /v1/checkout took {rng.randint(2900, 3200)}ms waiting for JDBC connection",
                )


@register
class MemoryLeak(Scenario):
    name = "memory_leak"
    title = "Inventory heap grows until OOMKilled"
    onset_minute = 0.0
    ground_truth = GroundTruth(
        C.MEMORY_LEAK,
        "inventory",
        "Inventory's heap grows steadily (no recent change in the window) until GC thrashing and OOMKilled "
        "restarts; checkout sees slow and failed reservations.",
        "memory-leak-oom",
        (A.RESTART_SERVICE, A.INCREASE_MEMORY_LIMIT),
        evidence_keywords=("OutOfMemoryError", "OOMKilled"),
    )

    def effects(self, ctx: TickContext) -> None:
        if ctx.service != "inventory":
            return
        m, rng = ctx.metrics, ctx.rng
        m["memory_percent"] = 55 + 1.45 * ctx.minute + rng.uniform(-0.5, 0.5)
        mem = m["memory_percent"]
        if mem > 82:
            m["latency_p99_ms"] += (mem - 82) * 70
            m["cpu_percent"] += (mem - 82) * 2.5
            heap = 4.0 * mem / 100
            ctx.log(
                "WARN",
                f"GC pause {rng.uniform(0.8, 2.2):.2f}s (G1 Evacuation Pause) heap "
                f"{heap:.2f}G->{heap - 0.02:.2f}G/4.00G; old gen not reclaimed",
            )
        if mem > 92:
            m["error_rate"] += rng.uniform(0.08, 0.15)
            ctx.log(
                "ERROR",
                "java.lang.OutOfMemoryError: Java heap space at "
                "com.shop.inventory.cache.StockCache.put(StockCache.java:112)",
                trace_id=ctx.trace_id(),
            )
        if ctx.minute in (22.0, 27.0):
            restarts = 2 if ctx.minute == 22.0 else 3
            ctx.log(
                "ERROR",
                f"container inventory OOMKilled (exit code 137, memory limit 4Gi); restart count {restarts}",
            )
            ctx.event(
                "kubernetes",
                "CRITICAL",
                f"Pod inventory-6f7c9d-x2k4p container inventory OOMKilled "
                f"(exit code 137); restarting, restart count {restarts}",
                alertname="KubePodOOMKilled",
            )


@register
class BadDeployment(Scenario):
    name = "bad_deployment"
    title = "Payments v4.2.0 deploy throws NullPointerException"
    onset_minute = 20.0
    ground_truth = GroundTruth(
        C.BAD_DEPLOYMENT,
        "payments",
        "Payments v4.2.0, deployed at the moment errors started, throws NullPointerException in PaymentMapper "
        "for charges without a currency; checkout and api-gateway fail checkouts.",
        "bad-deployment-rollback",
        (A.ROLLBACK_DEPLOYMENT,),
        evidence_keywords=("NullPointerException", "4.2.0"),
    )

    def cause_changes(self, start: datetime) -> list[Change]:
        return [
            Change(
                start + timedelta(minutes=self.onset_minute),
                "payments",
                "deploy",
                "4.2.0",
                "ci-bot (merged by dev-ana)",
                "Refactor payment DTO mapping to the new currency model",
                {"commits": 7, "files_changed": ["PaymentMapper.java", "CurrencyAdapter.java"]},
            )
        ]

    def effects(self, ctx: TickContext) -> None:
        if ctx.service != "payments" or not ctx.active:
            return
        m, rng = ctx.metrics, ctx.rng
        if ctx.t < 0.5:
            ctx.log("INFO", "Started payments 4.2.0 in 6.3s (rolling update 3/3 pods ready)")
        m["error_rate"] += rng.uniform(0.35, 0.42)
        m["latency_p99_ms"] += 30
        for _ in range(rng.randint(2, 3)):
            ctx.log(
                "ERROR",
                'java.lang.NullPointerException: Cannot invoke "Currency.getCode()" because '
                '"amount.currency" is null at PaymentMapper.toDto(PaymentMapper.java:87) [version=4.2.0]',
                trace_id=ctx.trace_id(),
                version="4.2.0",
            )


@register
class SlowDependency(Scenario):
    name = "slow_dependency"
    title = "Inventory slow queries cause checkout timeouts"
    onset_minute = 19.0
    ground_truth = GroundTruth(
        C.SLOW_DEPENDENCY,
        "inventory",
        "Inventory's stock query switched to a sequential scan after an index became invalid; inventory is up "
        "but ~3s slow, so checkout's 2s client timeouts fire and errors cascade.",
        "slow-dependency-latency",
        (A.ENABLE_CIRCUIT_BREAKER, A.SCALE_OUT),
        evidence_keywords=("slow query", "timeout calling inventory"),
    )

    def effects(self, ctx: TickContext) -> None:
        if ctx.service != "inventory":
            return
        m, rng = ctx.metrics, ctx.rng
        if -2.5 <= ctx.t < -2:
            ctx.log(
                "WARN",
                "REINDEX CONCURRENTLY idx_stock_levels_sku failed: deadlock detected; index left INVALID",
            )
        if ctx.t >= 0:
            m["latency_p99_ms"] = 60 + (rng.uniform(2600, 3100) - 60) * ctx.ramp(1.5)
            m["error_rate"] += 0.03
            m["db_connections_in_use"] = 8 + 22 * ctx.ramp(1.5) + rng.uniform(-2, 2)
            m["cpu_percent"] += 8
            for _ in range(rng.randint(1, 2)):
                ctx.log(
                    "WARN",
                    f"slow query {rng.randint(2500, 3100)}ms: SELECT sku, qty FROM stock_levels WHERE "
                    "sku = ANY($1) (Seq Scan on stock_levels, rows=4100000)",
                )


@register
class TlsCertExpired(Scenario):
    name = "tls_cert_expired"
    title = "auth.internal TLS certificate expired"
    onset_minute = 21.0
    ground_truth = GroundTruth(
        C.TLS_CERT_EXPIRED,
        "auth",
        "The TLS certificate for auth.internal expired; api-gateway fails the handshake (x509 expired) so "
        "logins and authenticated routes fail, while auth itself looks idle.",
        "tls-certificate-expired",
        (A.RENEW_CERTIFICATE,),
        evidence_keywords=("x509: certificate has expired", "CN=auth.internal"),
    )

    def effects(self, ctx: TickContext) -> None:
        m, rng = ctx.metrics, ctx.rng
        expiry = self.window_start(ctx) + timedelta(minutes=self.onset_minute)
        if ctx.service == "auth":
            if ctx.minute == 3.0:
                ctx.log(
                    "WARN",
                    f"TLS certificate CN=auth.internal not valid after {expiry.isoformat()} "
                    "(renewal job last succeeded 91 days ago)",
                )
            if ctx.active:
                m["requests_per_sec"] *= 0.12
                if rng.random() < 0.7:
                    ctx.log(
                        "INFO",
                        f"http: TLS handshake error from 10.0.4.{rng.randint(2, 250)}:{rng.randint(30000, 60000)}: "
                        "remote error: tls: bad certificate",
                    )
        if ctx.service == "api-gateway" and ctx.active:
            m["error_rate"] += rng.uniform(0.42, 0.5)
            now = ctx.ts.isoformat()
            for _ in range(rng.randint(2, 3)):
                ctx.log(
                    "ERROR",
                    "upstream auth: tls: failed to verify certificate: x509: certificate has expired or "
                    f"is not yet valid: current time {now} is after {expiry.isoformat()}",
                    upstream="auth",
                )


@register
class DiskFull(Scenario):
    name = "disk_full"
    title = "Payments log volume full"
    onset_minute = 18.0
    ground_truth = GroundTruth(
        C.DISK_FULL,
        "payments",
        "Log rotation on payments has been failing, the /var/log volume filled up, and audit-log writes fail "
        "with ENOSPC, so charges are rejected.",
        "disk-full",
        (A.FREE_DISK_SPACE,),
        evidence_keywords=("No space left on device", "logrotate"),
    )

    def effects(self, ctx: TickContext) -> None:
        if ctx.service != "payments":
            return
        m, rng = ctx.metrics, ctx.rng
        if ctx.minute >= 8:
            m["disk_used_percent"] = min(100.0, 70 + 1.2 * (ctx.minute - 8) + 18 * ctx.ramp(2))
        if ctx.minute == 8.0:
            ctx.log(
                "WARN",
                "logrotate: rotation of /var/log/payments/*.log failed: permission denied on "
                "/var/log/payments/archive (exit 1)",
            )
        if m["disk_used_percent"] >= 99:
            m["disk_used_percent"] = 100.0
            m["error_rate"] += rng.uniform(0.28, 0.34)
            for _ in range(rng.randint(2, 3)):
                ctx.log(
                    "ERROR",
                    "failed to write audit record to /var/log/payments/audit.log: No space left on "
                    "device (errno 28); rejecting charge",
                    trace_id=ctx.trace_id(),
                )


@register
class UpstreamOutage(Scenario):
    name = "upstream_outage"
    title = "Payment provider outage"
    onset_minute = 20.0
    ground_truth = GroundTruth(
        C.UPSTREAM_OUTAGE,
        "payment-provider",
        "The external payment provider api.payprovider.example is down (503s and connection resets); payments "
        "retries then fails charges, cascading to checkout.",
        "upstream-provider-outage",
        (A.FAILOVER_PROVIDER, A.ENABLE_CIRCUIT_BREAKER),
        acceptable_services=("payments",),
        evidence_keywords=("503 Service Unavailable", "api.payprovider.example"),
    )

    def effects(self, ctx: TickContext) -> None:
        if ctx.service != "payments" or not ctx.active:
            return
        m, rng = ctx.metrics, ctx.rng
        m["error_rate"] += rng.uniform(0.5, 0.6)
        m["latency_p99_ms"] += 1200 * ctx.ramp(1)
        ctx.log(
            "ERROR",
            "POST https://api.payprovider.example/v2/charges failed: 503 Service Unavailable (attempt 3/3)",
            trace_id=ctx.trace_id(),
            provider="payprovider",
        )
        if rng.random() < 0.7:
            ctx.log(
                "ERROR",
                "connection reset by peer while reading response from api.payprovider.example:443",
                provider="payprovider",
            )


@register
class ConfigError(Scenario):
    name = "config_error"
    title = "Gateway routes checkout traffic to a non-existent cluster"
    onset_minute = 21.0
    ground_truth = GroundTruth(
        C.CONFIG_ERROR,
        "api-gateway",
        "A routes.yaml change on api-gateway sent /v1/cart and /v1/checkout to cluster 'checkout-v2', which has no "
        "healthy hosts; checkout itself is healthy but receives less traffic.",
        "bad-config-change",
        (A.REVERT_CONFIG_CHANGE,),
        evidence_keywords=("no healthy upstream", "checkout-v2"),
    )

    def cause_changes(self, start: datetime) -> list[Change]:
        return [
            Change(
                start + timedelta(minutes=self.onset_minute),
                "api-gateway",
                "config_change",
                None,
                "dev-marco",
                "routes.yaml: send /v1/cart and /v1/checkout to cluster checkout-v2 (canary)",
                {"file": "routes.yaml", "before": "cluster: checkout", "after": "cluster: checkout-v2"},
            )
        ]

    def effects(self, ctx: TickContext) -> None:
        if not ctx.active:
            return
        m, rng = ctx.metrics, ctx.rng
        if ctx.service == "api-gateway":
            if ctx.t < 0.5:
                ctx.log("INFO", "Hot-reloaded routes.yaml (14 routes, 4 clusters)")
            m["error_rate"] += rng.uniform(0.3, 0.36)
            for _ in range(rng.randint(2, 3)):
                route = rng.choice(("/v1/checkout", "/v1/cart"))
                ctx.log(
                    "ERROR", f"no healthy upstream for cluster 'checkout-v2' (route {route}); returning 503"
                )
        if ctx.service == "checkout":
            m["requests_per_sec"] *= 0.35


@register
class CpuThrottling(Scenario):
    name = "cpu_throttling"
    title = "Auth CPU throttled at its limit"
    onset_minute = 18.0
    ground_truth = GroundTruth(
        C.CPU_THROTTLING,
        "auth",
        "Auth runs at its 500m CPU limit and is heavily throttled as traffic grows; requests queue and latency "
        "rises, slowing every authenticated call through api-gateway.",
        "cpu-throttling",
        (A.INCREASE_CPU_LIMIT, A.SCALE_OUT),
        evidence_keywords=("queue depth", "cpu limit 500m"),
    )

    def effects(self, ctx: TickContext) -> None:
        if ctx.service != "auth" or not ctx.active:
            return
        m, rng = ctx.metrics, ctx.rng
        ramp = ctx.ramp(2)
        m["requests_per_sec"] *= 1 + 0.35 * ramp
        m["cpu_percent"] = 38 + (rng.uniform(96, 99.5) - 38) * ramp
        m["cpu_throttled_percent"] = 1.5 + rng.uniform(60, 75) * ramp
        m["latency_p99_ms"] = 40 + rng.uniform(800, 1100) * ramp
        m["error_rate"] += 0.02 * ramp
        if ramp > 0.5:
            ctx.log(
                "WARN", f"request queue depth {rng.randint(300, 520)} exceeds 256; handlers waiting for CPU"
            )
            ctx.log("ERROR", f"request timed out in queue after 1000ms (queue depth {rng.randint(300, 520)})")
            if rng.random() < 0.5:
                ctx.log("WARN", f"bcrypt verify took {rng.randint(600, 900)}ms (expected < 100ms)")


@register
class DnsFailure(Scenario):
    name = "dns_failure"
    title = "Cluster DNS lookups timing out"
    onset_minute = 20.0
    ground_truth = GroundTruth(
        C.DNS_FAILURE,
        "coredns",
        "Cluster DNS (CoreDNS at 10.96.0.10) is timing out, so lookups fail in several services at once; "
        "no single service changed.",
        "dns-resolution-failure",
        (A.RESTART_DNS,),
        acceptable_services=("dns", "kube-dns"),
        evidence_keywords=("lookup", "10.96.0.10:53", "i/o timeout"),
    )

    TARGETS: ClassVar[dict[str, tuple[str, ...]]] = {
        "api-gateway": ("auth.prod.svc.cluster.local", "checkout.prod.svc.cluster.local"),
        "checkout": ("inventory.prod.svc.cluster.local", "payments.prod.svc.cluster.local"),
        "payments": ("api.payprovider.example", "api.fraudscore.example"),
    }

    def effects(self, ctx: TickContext) -> None:
        if ctx.service not in self.TARGETS or not ctx.active:
            return
        m, rng = ctx.metrics, ctx.rng
        m["error_rate"] += rng.uniform(0.22, 0.32)
        m["latency_p99_ms"] += 500
        for _ in range(rng.randint(1, 3)):
            host = rng.choice(self.TARGETS[ctx.service])
            if rng.random() < 0.75:
                ctx.log(
                    "ERROR",
                    f"dial tcp: lookup {host} on 10.96.0.10:53: read udp "
                    f"10.0.{rng.randint(1, 9)}.{rng.randint(2, 250)}:{rng.randint(30000, 60000)}->10.96.0.10:53: "
                    "i/o timeout",
                )
            else:
                ctx.log("ERROR", f"lookup {host} on 10.96.0.10:53: server misbehaving (SERVFAIL)")


@register
class KafkaConsumerLag(Scenario):
    name = "kafka_consumer_lag"
    title = "Inventory order consumer falling behind"
    onset_minute = 15.0
    ground_truth = GroundTruth(
        C.KAFKA_CONSUMER_LAG,
        "inventory",
        "Inventory's consumer group for the orders topic is processing batches too slowly, exceeding "
        "max.poll.interval.ms and rebalancing repeatedly; lag climbs and checkout reservations stay pending.",
        "kafka-consumer-lag",
        (A.SCALE_CONSUMERS, A.RESTART_SERVICE),
        acceptable_services=("orders-topic",),
        evidence_keywords=("max.poll.interval.ms", "rebalancing"),
    )

    def effects(self, ctx: TickContext) -> None:
        if not ctx.active:
            return
        m, rng = ctx.metrics, ctx.rng
        if ctx.service == "inventory":
            m["kafka_consumer_lag"] = 60 + 18_000 * ctx.t + rng.uniform(-500, 500)
            if rng.random() < 0.7:
                ctx.log(
                    "WARN",
                    f"consumer inventory-orders-{rng.randint(0, 3)}: processing batch of 500 records took "
                    f"{rng.randint(305, 340)}s; exceeded max.poll.interval.ms=300000, leaving group",
                )
            if rng.random() < 0.5:
                ctx.log(
                    "INFO", f"Consumer group inventory-orders rebalancing (generation {400 + int(ctx.t * 2)})"
                )
        if ctx.service == "checkout" and ctx.t > 3:
            m["error_rate"] += rng.uniform(0.06, 0.1)
            for _ in range(rng.randint(1, 2)):
                ctx.log(
                    "ERROR",
                    f"reservation for order ord_{rng.getrandbits(40):010x} still PENDING after 60s "
                    "(inventory has not processed order event); cancelling",
                )


@register
class ThirdPartyRateLimit(Scenario):
    name = "third_party_rate_limit"
    title = "Fraud-scoring API rate limiting payments"
    onset_minute = 19.0
    ground_truth = GroundTruth(
        C.THIRD_PARTY_RATE_LIMIT,
        "fraudscore-api",
        "The third-party fraud-scoring API is rate limiting payments (HTTP 429 with Retry-After); immediate "
        "retries amplify the load and charges are rejected.",
        "third-party-rate-limit",
        (A.REDUCE_REQUEST_RATE, A.ENABLE_CIRCUIT_BREAKER),
        acceptable_services=("payments",),
        evidence_keywords=("429 Too Many Requests", "Retry-After"),
    )

    def effects(self, ctx: TickContext) -> None:
        if ctx.service != "payments" or not ctx.active:
            return
        m, rng = ctx.metrics, ctx.rng
        ramp = ctx.ramp(1.5)
        m["http_429_rate"] = rng.uniform(0.4, 0.5) * ramp
        m["error_rate"] += rng.uniform(0.22, 0.28) * ramp
        m["latency_p99_ms"] += 600 * ramp
        if ramp > 0:
            ctx.log(
                "WARN",
                "POST https://api.fraudscore.example/v1/score returned 429 Too Many Requests "
                f"(Retry-After: 30s); retrying immediately, attempt {rng.randint(2, 5)}/5",
            )
            ctx.log(
                "ERROR",
                "fraud check failed after 5 attempts: 429 Too Many Requests from api.fraudscore.example; "
                "rejecting charge",
                trace_id=ctx.trace_id(),
            )


def get_scenario(name: str) -> Scenario:
    try:
        return SCENARIOS[name]
    except KeyError:
        raise KeyError(f"Unknown scenario '{name}'. Available: {', '.join(sorted(SCENARIOS))}") from None

"""Shared vocabulary: services, root-cause categories and remediation actions.

The agents classify root causes into ``RootCauseCategory`` (like an SRE team's incident taxonomy) and may only
propose actions from ``ActionType``. The guardrails in the agent service enforce the allowlist; the evals
compare agent output against simulator ground truth using the same enums.
"""

from __future__ import annotations

from enum import StrEnum


class RootCauseCategory(StrEnum):
    DB_POOL_EXHAUSTION = "db_pool_exhaustion"
    MEMORY_LEAK = "memory_leak"
    BAD_DEPLOYMENT = "bad_deployment"
    SLOW_DEPENDENCY = "slow_dependency"
    TLS_CERT_EXPIRED = "tls_cert_expired"
    DISK_FULL = "disk_full"
    UPSTREAM_OUTAGE = "upstream_outage"
    CONFIG_ERROR = "config_error"
    CPU_THROTTLING = "cpu_throttling"
    DNS_FAILURE = "dns_failure"
    KAFKA_CONSUMER_LAG = "kafka_consumer_lag"
    THIRD_PARTY_RATE_LIMIT = "third_party_rate_limit"
    UNKNOWN = "unknown"


CATEGORY_DESCRIPTIONS: dict[RootCauseCategory, str] = {
    RootCauseCategory.DB_POOL_EXHAUSTION: "Service's database connection pool is saturated; requests wait for connections.",
    RootCauseCategory.MEMORY_LEAK: "Memory grows steadily until GC thrashing / OOM kills, without a matching change.",
    RootCauseCategory.BAD_DEPLOYMENT: "A recent code deployment introduced a bug; errors start right at the deploy.",
    RootCauseCategory.SLOW_DEPENDENCY: "A dependency is reachable but slow, causing timeouts in its callers.",
    RootCauseCategory.TLS_CERT_EXPIRED: "A TLS certificate expired; clients fail the handshake (x509 errors).",
    RootCauseCategory.DISK_FULL: "A volume is out of space; writes fail with 'No space left on device'.",
    RootCauseCategory.UPSTREAM_OUTAGE: "An external/upstream provider is down (5xx, connection refused/reset).",
    RootCauseCategory.CONFIG_ERROR: "A recent configuration change (not code) is wrong, e.g. bad routing or URL.",
    RootCauseCategory.CPU_THROTTLING: "Service hits its CPU limit and is throttled; latency rises, no errors in code.",
    RootCauseCategory.DNS_FAILURE: "Name resolution fails (lookup timeouts / SERVFAIL) across several services.",
    RootCauseCategory.KAFKA_CONSUMER_LAG: "A Kafka consumer falls behind; lag grows and downstream data goes stale.",
    RootCauseCategory.THIRD_PARTY_RATE_LIMIT: "A third-party API is rate limiting us (HTTP 429 / Retry-After).",
    RootCauseCategory.UNKNOWN: "Evidence is insufficient to determine a root cause.",
}


class ActionType(StrEnum):
    """Remediations the agents may *propose*. Anything else is rejected by the guardrails."""

    RESTART_SERVICE = "restart_service"
    SCALE_OUT = "scale_out"
    ROLLBACK_DEPLOYMENT = "rollback_deployment"
    REVERT_CONFIG_CHANGE = "revert_config_change"
    INCREASE_CONNECTION_POOL = "increase_connection_pool"
    INCREASE_MEMORY_LIMIT = "increase_memory_limit"
    INCREASE_CPU_LIMIT = "increase_cpu_limit"
    RENEW_CERTIFICATE = "renew_certificate"
    FREE_DISK_SPACE = "free_disk_space"
    ENABLE_CIRCUIT_BREAKER = "enable_circuit_breaker"
    FAILOVER_PROVIDER = "failover_provider"
    RESTART_DNS = "restart_dns"
    SCALE_CONSUMERS = "scale_consumers"
    REDUCE_REQUEST_RATE = "reduce_request_rate"
    ESCALATE_TO_HUMAN = "escalate_to_human"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# Internal services in the simulated system and who calls whom (caller -> callees).
SERVICES: tuple[str, ...] = ("api-gateway", "auth", "checkout", "inventory", "payments")

DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "api-gateway": ("auth", "checkout"),
    "checkout": ("inventory", "payments"),
    "auth": (),
    "inventory": (),
    "payments": (),
}

# Infrastructure / third parties that can be a root cause but don't emit their own alerts.
EXTERNAL_COMPONENTS: tuple[str, ...] = ("payment-provider", "fraudscore-api", "coredns", "orders-topic")

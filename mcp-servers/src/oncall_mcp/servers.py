"""The four read-only MCP servers. Tool docstrings are written for the LLM: what it's for and when to use it."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any

import psycopg
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from oncall_common.db import connection
from oncall_common.embeddings import Embedder, get_embedder
from oncall_mcp.tools import deploys, logs, metrics, runbooks

ConnectionFactory = Callable[[], AbstractContextManager[psycopg.Connection]]
READ_ONLY = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)


def _run(factory: ConnectionFactory, fn: Callable[..., dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
    with factory() as conn:
        return fn(conn, **kwargs)


def build_logs_server(factory: ConnectionFactory = connection) -> MCPServer:
    server = MCPServer(
        "logs-mcp", instructions="Read-only search over application logs of the shop's services."
    )

    @server.tool(annotations=READ_ONLY)
    def log_error_summary(
        service: str | None = None, since_minutes: int = 30, start: str | None = None, end: str | None = None
    ) -> dict[str, Any]:
        """Top recurring ERROR/WARN log patterns with counts and first/last seen times. Start here: it shows
        what is failing and where in one compact call. Optionally filter by service."""
        return _run(
            factory, logs.error_summary, service=service, since_minutes=since_minutes, start=start, end=end
        )

    @server.tool(annotations=READ_ONLY)
    def search_logs(
        service: str | None = None,
        keyword: str | None = None,
        level: str | None = None,
        since_minutes: int = 30,
        start: str | None = None,
        end: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Search log lines (newest first) by service, case-insensitive keyword and level (INFO, WARN, ERROR).
        Use to confirm a hypothesis, e.g. keyword='x509' or keyword='OutOfMemory'."""
        return _run(
            factory,
            logs.search_logs,
            service=service,
            keyword=keyword,
            level=level,
            since_minutes=since_minutes,
            start=start,
            end=end,
            limit=limit,
        )

    return server


def build_metrics_server(factory: ConnectionFactory = connection) -> MCPServer:
    server = MCPServer(
        "metrics-mcp",
        instructions="Read-only service metrics: latency, errors, CPU, memory, "
        "disk, DB connections, Kafka lag.",
    )

    @server.tool(annotations=READ_ONLY)
    def detect_metric_anomalies(since_minutes: int = 30, recent_minutes: int = 10) -> dict[str, Any]:
        """Which service metrics changed most in the last `recent_minutes` compared with earlier in the window.
        Use early to find the service where the problem started."""
        return _run(
            factory, metrics.detect_anomalies, since_minutes=since_minutes, recent_minutes=recent_minutes
        )

    @server.tool(annotations=READ_ONLY)
    def query_metric(
        service: str, metric: str, since_minutes: int = 30, start: str | None = None, end: str | None = None
    ) -> dict[str, Any]:
        """Time series and min/max/avg for one metric of one service. Metrics: requests_per_sec, latency_p99_ms,
        error_rate, cpu_percent, cpu_throttled_percent, memory_percent, disk_used_percent, http_429_rate,
        db_connections_in_use, db_connections_max, kafka_consumer_lag."""
        return _run(
            factory,
            metrics.query_metric,
            service=service,
            metric=metric,
            since_minutes=since_minutes,
            start=start,
            end=end,
        )

    @server.tool(annotations=READ_ONLY)
    def list_metrics(service: str | None = None) -> dict[str, Any]:
        """List the metric names available (optionally for one service)."""
        return _run(factory, metrics.list_metrics, service=service)

    return server


def build_deploys_server(factory: ConnectionFactory = connection) -> MCPServer:
    server = MCPServer(
        "deploys-mcp", instructions="Read-only history of deployments, config changes and flags."
    )

    @server.tool(annotations=READ_ONLY)
    def list_recent_changes(
        service: str | None = None, kind: str | None = None, since_minutes: int = 120
    ) -> dict[str, Any]:
        """Recent deployments ('deploy'), configuration changes ('config_change') and feature flags
        ('feature_flag'), newest first, with author, description and diff. A change whose time matches the
        start of errors is a strong root-cause signal; unrelated changes are common, so check timing."""
        return _run(factory, deploys.list_changes, service=service, kind=kind, since_minutes=since_minutes)

    return server


def build_runbooks_server(
    factory: ConnectionFactory = connection, embedder: Embedder | None = None
) -> MCPServer:
    server = MCPServer("runbooks-mcp", instructions="Semantic search over the team's incident runbooks.")
    _embedder: list[Embedder] = [embedder] if embedder else []

    def get() -> Embedder:
        if not _embedder:
            _embedder.append(get_embedder())  # lazy: loading the model takes a few seconds
        return _embedder[0]

    @server.tool(annotations=READ_ONLY)
    def search_runbooks(query: str, k: int = 3) -> dict[str, Any]:
        """Find the most relevant runbooks for a description of the problem (e.g. 'connection pool exhausted
        on checkout'). Returns runbook ids, the matching section and the remediation actions each allows."""
        return _run(factory, runbooks.search_runbooks, embedder=get(), query=query, k=k)

    @server.tool(annotations=READ_ONLY)
    def get_runbook(runbook_id: str) -> dict[str, Any]:
        """Full markdown of one runbook by id, including diagnosis, remediation and rollback steps."""
        return _run(factory, runbooks.get_runbook, runbook_id=runbook_id)

    return server


SERVERS: dict[str, tuple[Callable[[], MCPServer], int]] = {
    "logs": (build_logs_server, 8101),
    "metrics": (build_metrics_server, 8102),
    "deploys": (build_deploys_server, 8103),
    "runbooks": (build_runbooks_server, 8104),
}

"""Metric queries over ``telemetry.metrics``."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import psycopg
from mcp.server.mcpserver.exceptions import ToolError

from oncall_mcp.tools.common import check_service, iso, resolve_window, window_info

METRICS: dict[str, str] = {
    "requests_per_sec": "Request rate (req/s)",
    "latency_p99_ms": "99th percentile latency (ms)",
    "error_rate": "Fraction of requests failing (0-1)",
    "cpu_percent": "CPU usage, % of container limit",
    "cpu_throttled_percent": "% of CPU periods throttled by the CFS quota",
    "memory_percent": "Memory working set, % of container limit",
    "disk_used_percent": "Disk usage of /var/log volume (%)",
    "http_429_rate": "Fraction of outbound third-party calls answered with HTTP 429",
    "db_connections_in_use": "Active DB connections in the pool",
    "db_connections_max": "DB connection pool size",
    "kafka_consumer_lag": "Kafka consumer group lag (messages)",
}


def _check_metric(metric: str) -> str:
    if metric not in METRICS:
        raise ToolError(f"Unknown metric '{metric}'. Available: {', '.join(METRICS)}")
    return metric


def list_metrics(conn: psycopg.Connection, *, service: str | None = None) -> dict[str, Any]:
    service = check_service(service)
    with conn.cursor() as cur:
        if service:
            cur.execute(
                "SELECT DISTINCT metric FROM telemetry.metrics WHERE service = %s ORDER BY metric", [service]
            )
        else:
            cur.execute("SELECT DISTINCT metric FROM telemetry.metrics ORDER BY metric")
        present = [r["metric"] for r in cur.fetchall()]
    return {"service": service, "metrics": [{"name": m, "description": METRICS.get(m, "")} for m in present]}


def query_metric(
    conn: psycopg.Connection,
    *,
    service: str,
    metric: str,
    since_minutes: int | None = None,
    start: str | None = None,
    end: str | None = None,
    max_points: int = 12,
) -> dict[str, Any]:
    """Summary statistics plus a downsampled series (bucket averages) to keep LLM context small."""
    service = check_service(service)
    if not service:
        raise ToolError("service is required")
    metric = _check_metric(metric)
    if not 2 <= max_points <= 120:
        raise ToolError("max_points must be between 2 and 120")
    window_start, window_end = resolve_window(since_minutes, start, end)
    bucket = (window_end - window_start) / max_points
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT min(value) AS min, max(value) AS max, avg(value) AS avg, count(*) AS n,
                   (array_agg(value ORDER BY ts ASC))[1] AS first, (array_agg(value ORDER BY ts DESC))[1] AS last
            FROM telemetry.metrics WHERE service = %s AND metric = %s AND ts >= %s AND ts <= %s
            """,
            [service, metric, window_start, window_end],
        )
        stats = cur.fetchone()
        cur.execute(
            """
            SELECT floor(extract(epoch FROM ts - %s) / %s)::int AS bucket, min(ts) AS ts, avg(value) AS value
            FROM telemetry.metrics WHERE service = %s AND metric = %s AND ts >= %s AND ts <= %s
            GROUP BY bucket ORDER BY bucket
            """,
            [window_start, bucket.total_seconds(), service, metric, window_start, window_end],
        )
        points = cur.fetchall()
    if not stats or stats["n"] == 0:
        return {
            "service": service,
            "metric": metric,
            "window": window_info(window_start, window_end),
            "points": [],
            "note": "no data in this window",
        }
    return {
        "service": service,
        "metric": metric,
        "description": METRICS[metric],
        "window": window_info(window_start, window_end),
        "summary": {k: round(float(stats[k]), 4) for k in ("min", "max", "avg", "first", "last")},
        "points": [{"ts": iso(p["ts"]), "value": round(float(p["value"]), 4)} for p in points],
    }


def detect_anomalies(
    conn: psycopg.Connection,
    *,
    since_minutes: int = 30,
    recent_minutes: int = 10,
    end: str | None = None,
    top: int = 12,
) -> dict[str, Any]:
    """Compare each service/metric's last ``recent_minutes`` with the earlier part of the window.

    Answers "what changed, where?" in one call — the first question an SRE asks.
    """
    if recent_minutes >= since_minutes:
        raise ToolError("recent_minutes must be smaller than since_minutes")
    window_start, window_end = resolve_window(since_minutes, None, end)
    split = window_end - timedelta(minutes=recent_minutes)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT service, metric,
                   avg(value) FILTER (WHERE ts < %(split)s) AS baseline,
                   avg(value) FILTER (WHERE ts >= %(split)s) AS recent,
                   max(value) FILTER (WHERE ts >= %(split)s) AS recent_max
            FROM telemetry.metrics
            WHERE ts >= %(start)s AND ts <= %(end)s AND metric <> 'db_connections_max'
            GROUP BY service, metric
            """,
            {"split": split, "start": window_start, "end": window_end},
        )
        rows = cur.fetchall()
    findings = []
    for r in rows:
        if r["baseline"] is None or r["recent"] is None:
            continue
        baseline, recent = float(r["baseline"]), float(r["recent"])
        # Floor the denominator so tiny baselines (error_rate 0.003, lag 60) don't produce absurd ratios.
        floor = {"error_rate": 0.01, "http_429_rate": 0.01, "kafka_consumer_lag": 1000.0}.get(
            r["metric"], 1.0
        )
        change = (recent - baseline) / max(abs(baseline), floor)
        if abs(change) >= 0.3:
            findings.append(
                {
                    "service": r["service"],
                    "metric": r["metric"],
                    "baseline_avg": round(baseline, 4),
                    "recent_avg": round(recent, 4),
                    "recent_max": round(float(r["recent_max"]), 4),
                    "relative_change": round(change, 2),
                }
            )
    findings.sort(key=lambda f: abs(f["relative_change"]), reverse=True)
    return {
        "window": window_info(window_start, window_end),
        "recent_since": iso(split),
        "anomalies": findings[:top],
    }

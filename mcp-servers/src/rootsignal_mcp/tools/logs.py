"""Log search over ``telemetry.logs``."""

from __future__ import annotations

from typing import Any

import psycopg
from mcp.server.mcpserver.exceptions import ToolError

from rootsignal_mcp.tools.common import check_service, iso, resolve_window, window_info

LEVELS = ("DEBUG", "INFO", "WARN", "ERROR")
# Collapse ids and numbers so messages that differ only in volatile values group together.
NORMALISE_SQL = r"regexp_replace(message, '[0-9a-f]{12,}|[0-9]+(\.[0-9]+)?', '#', 'g')"


def search_logs(
    conn: psycopg.Connection,
    *,
    service: str | None = None,
    keyword: str | None = None,
    level: str | None = None,
    since_minutes: int | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = 30,
) -> dict[str, Any]:
    service = check_service(service)
    if level is not None:
        level = level.upper()
        if level not in LEVELS:
            raise ToolError(f"level must be one of {', '.join(LEVELS)}")
    if not 1 <= limit <= 200:
        raise ToolError("limit must be between 1 and 200")
    window_start, window_end = resolve_window(since_minutes, start, end)

    where = ["ts >= %s", "ts <= %s"]
    params: list[Any] = [window_start, window_end]
    if service:
        where.append("service = %s")
        params.append(service)
    if level:
        where.append("level = %s")
        params.append(level)
    if keyword:
        where.append("message ILIKE %s")
        params.append(f"%{keyword}%")
    clause = " AND ".join(where)

    with conn.cursor() as cur:
        cur.execute(f"SELECT count(*) AS n FROM telemetry.logs WHERE {clause}", params)
        total = cur.fetchone()["n"]
        cur.execute(
            f"SELECT ts, service, level, message FROM telemetry.logs WHERE {clause} ORDER BY ts DESC LIMIT %s",
            [*params, limit],
        )
        rows = cur.fetchall()
    return {
        "window": window_info(window_start, window_end),
        "total_matches": total,
        "returned": len(rows),
        "logs": [
            {"ts": iso(r["ts"]), "service": r["service"], "level": r["level"], "message": r["message"]}
            for r in rows
        ],
    }


def error_summary(
    conn: psycopg.Connection,
    *,
    service: str | None = None,
    since_minutes: int | None = None,
    start: str | None = None,
    end: str | None = None,
    top: int = 10,
) -> dict[str, Any]:
    """Most frequent ERROR/WARN patterns: far more token-efficient for an LLM than raw log lines."""
    service = check_service(service)
    window_start, window_end = resolve_window(since_minutes, start, end)
    params: list[Any] = [window_start, window_end]
    service_clause = ""
    if service:
        service_clause = "AND service = %s"
        params.append(service)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT service, level, {NORMALISE_SQL} AS pattern, count(*) AS count,
                   min(ts) AS first_seen, max(ts) AS last_seen, min(message) AS example
            FROM telemetry.logs
            WHERE ts >= %s AND ts <= %s AND level IN ('ERROR', 'WARN') {service_clause}
            GROUP BY service, level, pattern
            ORDER BY count DESC
            LIMIT %s
            """,
            [*params, top],
        )
        rows = cur.fetchall()
    return {
        "window": window_info(window_start, window_end),
        "patterns": [
            {
                "service": r["service"],
                "level": r["level"],
                "count": r["count"],
                "first_seen": iso(r["first_seen"]),
                "last_seen": iso(r["last_seen"]),
                "example": r["example"],
            }
            for r in rows
        ],
    }

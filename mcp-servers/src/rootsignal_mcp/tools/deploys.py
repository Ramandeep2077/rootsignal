"""Deployment and configuration-change history over ``telemetry.deployments``."""

from __future__ import annotations

from typing import Any

import psycopg
from mcp.server.mcpserver.exceptions import ToolError

from rootsignal_mcp.tools.common import check_service, iso, resolve_window, window_info

KINDS = ("deploy", "config_change", "feature_flag")


def list_changes(
    conn: psycopg.Connection,
    *,
    service: str | None = None,
    kind: str | None = None,
    since_minutes: int | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    service = check_service(service)
    if kind is not None and kind not in KINDS:
        raise ToolError(f"kind must be one of {', '.join(KINDS)}")
    window_start, window_end = resolve_window(since_minutes, start, end, default_minutes=24 * 60)
    where = ["ts >= %s", "ts <= %s"]
    params: list[Any] = [window_start, window_end]
    if service:
        where.append("service = %s")
        params.append(service)
    if kind:
        where.append("kind = %s")
        params.append(kind)
    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT ts, service, kind, version, author, description, diff FROM telemetry.deployments
                WHERE {" AND ".join(where)} ORDER BY ts DESC LIMIT %s""",
            [*params, limit],
        )
        rows = cur.fetchall()
    return {
        "window": window_info(window_start, window_end),
        "changes": [
            {
                "ts": iso(r["ts"]),
                "service": r["service"],
                "kind": r["kind"],
                "version": r["version"],
                "author": r["author"],
                "description": r["description"],
                "diff": r["diff"] or {},
            }
            for r in rows
        ],
    }

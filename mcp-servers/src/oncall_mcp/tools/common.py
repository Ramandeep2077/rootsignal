"""Helpers shared by the tool implementations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from mcp.server.mcpserver.exceptions import ToolError

from oncall_common.taxonomy import EXTERNAL_COMPONENTS, SERVICES

MAX_WINDOW = timedelta(days=7)


def parse_time(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ToolError(f"{field} must be an ISO-8601 timestamp, got '{value}'") from None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def resolve_window(
    since_minutes: int | None, start: str | None, end: str | None, *, default_minutes: int = 60
) -> tuple[datetime, datetime]:
    """Time range from either an absolute [start, end] or 'the last N minutes' (LLMs prefer the latter)."""
    end_dt = parse_time(end, "end") if end else datetime.now(UTC)
    if start:
        start_dt = parse_time(start, "start")
    else:
        minutes = since_minutes if since_minutes is not None else default_minutes
        if minutes <= 0:
            raise ToolError("since_minutes must be positive")
        start_dt = end_dt - timedelta(minutes=minutes)
    if start_dt >= end_dt:
        raise ToolError("start must be before end")
    if end_dt - start_dt > MAX_WINDOW:
        raise ToolError("time window is limited to 7 days")
    return start_dt, end_dt


def check_service(service: str | None, *, allow_external: bool = False) -> str | None:
    if service is None or service == "":
        return None
    service = service.strip().lower()
    known = SERVICES + (EXTERNAL_COMPONENTS if allow_external else ())
    if service not in known:
        raise ToolError(f"Unknown service '{service}'. Known services: {', '.join(known)}")
    return service


def iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat(timespec="seconds") if value else None


def window_info(start: datetime, end: datetime) -> dict[str, Any]:
    return {"start": iso(start), "end": iso(end)}

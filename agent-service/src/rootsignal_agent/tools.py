"""MCP toolbox: one client per MCP server, tool dispatch by name, and compact formatting for the LLM.

Prompt tokens are the dominant cost on CPU inference (~15 ms each here), so tool results are rendered as
dense text lines instead of pretty-printed JSON — typically 3-5x fewer tokens for the same information.
"""

from __future__ import annotations

import json
import logging
from contextlib import AsyncExitStack
from datetime import UTC, datetime
from typing import Any

from mcp import Client
from mcp.server.mcpserver import MCPServer

from rootsignal_common.telemetry import TOOL, clip, inject_context, span

log = logging.getLogger(__name__)

# Tools the investigator may call by itself (the runbook tools are used by the remediation agent).
INVESTIGATION_TOOLS = (
    "log_error_summary",
    "search_logs",
    "query_metric",
    "detect_metric_anomalies",
    "list_recent_changes",
)


class ToolError(Exception):
    pass


class Toolbox:
    def __init__(self, servers: dict[str, str | MCPServer]) -> None:
        """``servers`` maps a name to a streamable-HTTP URL, or (in tests) an in-process MCPServer."""
        self._servers = servers
        self._stack = AsyncExitStack()
        self._clients: dict[str, Client] = {}
        self._tools: dict[str, tuple[str, Any]] = {}  # tool name -> (server name, mcp Tool)

    async def __aenter__(self) -> Toolbox:
        for name, target in self._servers.items():
            client = await self._stack.enter_async_context(Client(target, read_timeout_seconds=60))
            self._clients[name] = client
            for tool in (await client.list_tools()).tools:
                self._tools[tool.name] = (name, tool)
        log.info("toolbox connected: %s", sorted(self._tools))
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._stack.aclose()

    @property
    def tool_names(self) -> list[str]:
        return sorted(self._tools)

    def specs(self, names: tuple[str, ...] | list[str]) -> list[dict[str, Any]]:
        """Tool definitions in the OpenAI/Ollama function-calling format."""
        specs = []
        for name in names:
            if name not in self._tools:
                continue
            tool = self._tools[name][1]
            specs.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description or "",
                        "parameters": tool.input_schema,
                    },
                }
            )
        return specs

    async def call(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        if name not in self._tools:
            raise ToolError(f"unknown tool '{name}'; available: {', '.join(self.tool_names)}")
        server, _ = self._tools[name]
        attributes = {
            "tool.name": name,
            "gen_ai.tool.name": name,
            "mcp.server": server,
            "input.value": clip(json.dumps(arguments or {}, default=str)),
        }
        with span(f"tool {name}", kind=TOOL, attributes=attributes) as current:
            # W3C trace context travels in the MCP request's _meta, so server-side spans join this trace.
            result = await self._clients[server].call_tool(
                name, arguments or {}, meta=inject_context() or None
            )
            text = result.content[0].text if result.content else ""
            current.set_attribute("output.value", clip(text))
            if result.is_error:
                current.set_attribute("error.type", "tool_error")
                raise ToolError(text or f"{name} failed")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"text": text}


def _hms(ts: str | None) -> str:
    return ts[11:19] if ts else "?"


def _ago(ts: str | None, now: datetime) -> str:
    if not ts:
        return ""
    minutes = (now - datetime.fromisoformat(ts)).total_seconds() / 60
    return f"{minutes:.0f} min ago" if minutes < 120 else f"{minutes / 60:.0f} h ago"


def compact(name: str, result: dict[str, Any], now: datetime | None = None) -> str:
    """Render a tool result as short text lines for the model."""
    now = now or datetime.now(UTC)
    if name == "log_error_summary":
        rows = result.get("patterns", [])
        lines = [
            f"- {p['service']} {p['level']} x{p['count']} ({_hms(p['first_seen'])}-{_hms(p['last_seen'])}): "
            f"{p['example'][:220]}"
            for p in rows
        ]
        return "\n".join(lines) or "(no ERROR/WARN logs in the window)"
    if name == "detect_metric_anomalies":
        rows = result.get("anomalies", [])
        lines = [
            f"- {a['service']}.{a['metric']}: {a['baseline_avg']:g} -> {a['recent_avg']:g} "
            f"(recent max {a['recent_max']:g}, {a['relative_change']:+.0%})"
            for a in rows
        ]
        return "\n".join(lines) or "(no significant metric changes)"
    if name == "list_recent_changes":
        rows = result.get("changes", [])
        lines = [
            f"- {_hms(c['ts'])} ({_ago(c['ts'], now)}) {c['service']} {c['kind']}"
            f"{' v' + c['version'] if c.get('version') else ''} by {c['author']}: {c['description']}"
            for c in rows
        ]
        return "\n".join(lines) or "(no changes in the window)"
    if name == "search_logs":
        rows = result.get("logs", [])[:15]
        header = f"{result.get('total_matches', len(rows))} matching lines, newest first:"
        return "\n".join(
            [header, *[f"- {_hms(r['ts'])} {r['service']} {r['level']}: {r['message'][:220]}" for r in rows]]
        )
    if name == "query_metric":
        if not result.get("points"):
            return f"{result.get('service')}.{result.get('metric')}: no data"
        s = result["summary"]
        series = ", ".join(f"{p['value']:g}" for p in result["points"])
        return (
            f"{result['service']}.{result['metric']} ({result.get('description', '')}): min {s['min']:g}, "
            f"max {s['max']:g}, avg {s['avg']:g}, first {s['first']:g}, last {s['last']:g}. Series: {series}"
        )
    if name == "search_runbooks":
        return "\n".join(
            f"- {r['runbook_id']} (score {r['score']:.2f}, categories {r['categories']}, actions "
            f"{r['allowed_actions']}): {r['title']}"
            for r in result.get("results", [])
        )
    return json.dumps(result, separators=(",", ":"), default=str)[:3000]

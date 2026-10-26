"""The three agents: triage, investigator, remediation. Each has an LLM path and a deterministic heuristic."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from oncall_agent.guardrails import GuardrailPolicy
from oncall_agent.llm.router import ModelRouter, UsageTracker
from oncall_agent.tools import Toolbox
from oncall_agent.trace import Trace

SEVERITY_ORDER = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO")


@dataclass
class RunContext:
    """Everything one incident's graph run needs. Passed to LangGraph as the runtime context."""

    router: ModelRouter
    toolbox: Toolbox
    trace: Trace
    usage: UsageTracker
    policy: GuardrailPolicy
    alert_client: Any = None  # AlertServiceClient; None in pure graph tests
    notifier: Any = None  # Notifier; None disables notifications


def max_severity(alerts: list[dict[str, Any]]) -> str:
    return min((a["severity"] for a in alerts), key=SEVERITY_ORDER.index, default="MEDIUM")


def alert_digest(alerts: list[dict[str, Any]], limit: int = 10) -> str:
    """One line per (service, alertname) with counts — an alert storm in a few lines."""
    groups: Counter[tuple[str, str]] = Counter()
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for alert in alerts:
        key = (alert["service"], alert.get("labels", {}).get("alertname") or alert["message"][:40])
        groups[key] += 1
        latest[key] = alert
    lines = []
    for (service, name), count in groups.most_common(limit):
        alert = latest[(service, name)]
        lines.append(f"- {service} {name} x{count} [{alert['severity']}]: {alert['message'][:160]}")
    if len(groups) > limit:
        lines.append(f"- ... and {len(groups) - limit} more alert types")
    return "\n".join(lines)

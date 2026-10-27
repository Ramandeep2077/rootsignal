"""Triage agent (small model): turns a group of related alerts into a titled, prioritised incident."""

from __future__ import annotations

from collections import Counter
from typing import Any

from rootsignal_agent.agents import RunContext, alert_digest, max_severity
from rootsignal_agent.llm.base import LLMError
from rootsignal_agent.schemas import TriageSummary

SYSTEM = (
    "You are an SRE triage assistant. Given a group of related monitoring alerts, write a short incident "
    "title that names the main symptom and the most affected service, choose the severity (the highest "
    "severity among the alerts unless they are clearly informational), list the affected services, and "
    "summarise in two sentences what is failing. Do not guess the root cause."
)


def heuristic_summary(alerts: list[dict[str, Any]]) -> TriageSummary:
    by_service = Counter(a["service"] for a in alerts)
    names = Counter(a.get("labels", {}).get("alertname") or "Alert" for a in alerts)
    top_service = by_service.most_common(1)[0][0]
    top_name = names.most_common(1)[0][0]
    others = len(by_service) - 1
    title = f"{top_name} on {top_service}" + (
        f" (+{others} more service{'s' if others > 1 else ''})" if others else ""
    )
    return TriageSummary(
        title=title[:140],
        severity=max_severity(alerts),
        affected_services=[s for s, _ in by_service.most_common(8)],
        summary=f"{len(alerts)} alerts across {', '.join(by_service)}; most frequent: {top_name}.",
    )


async def summarize(alerts: list[dict[str, Any]], ctx: RunContext) -> TriageSummary:
    fallback = heuristic_summary(alerts)
    if not ctx.router.uses_llm("triage"):
        ctx.trace.add("triage", "decision", "Grouped alerts summarised (rules)", title=fallback.title)
        return fallback
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"{len(alerts)} alerts in this group:\n{alert_digest(alerts)}"},
    ]
    try:
        summary = await ctx.router.structured("triage", messages, TriageSummary, ctx.usage)
    except LLMError as exc:
        ctx.trace.add("triage", "error", "Triage model failed; using rules", error=str(exc))
        return fallback
    # Keep the model honest: only services that actually alerted, and never downgrade below the alerts' max.
    alerted = set(fallback.affected_services)
    services = [s for s in summary.affected_services if s in alerted] or fallback.affected_services
    summary = summary.model_copy(update={"affected_services": services, "severity": fallback.severity})
    ctx.trace.add(
        "triage",
        "llm",
        "Incident titled and prioritised",
        model=ctx.usage.records[-1].model,
        title=summary.title,
        severity=summary.severity,
        services=services,
    )
    return summary

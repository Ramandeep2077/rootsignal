"""Investigator agent: gathers evidence through the MCP tools and produces a root-cause hypothesis.

Flow:
1. **Evidence pack** (deterministic, no LLM): error-log patterns, metric anomalies and recent changes. These are
   the three questions every SRE asks first, so we ask them for the model instead of hoping it does.
2. **Agentic follow-up**: the model may call up to ``max_tool_calls`` tools to confirm or refute its idea.
3. **Verdict**: a JSON-schema-constrained ``RootCauseHypothesis`` (category enum, service, confidence, evidence).
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from rootsignal_agent.agents import RunContext, alert_digest
from rootsignal_agent.llm.base import LLMError
from rootsignal_agent.schemas import Evidence, RootCauseHypothesis, TriageSummary
from rootsignal_agent.tools import INVESTIGATION_TOOLS, ToolError, compact
from rootsignal_common.taxonomy import CATEGORY_DESCRIPTIONS, RootCauseCategory

PREFETCH: tuple[tuple[str, dict[str, Any], str], ...] = (
    ("log_error_summary", {"since_minutes": 30}, "Top ERROR/WARN log patterns, last 30 min"),
    (
        "detect_metric_anomalies",
        {"since_minutes": 30, "recent_minutes": 10},
        "Metric changes, last 10 min vs the 20 min before",
    ),
    ("list_recent_changes", {"since_minutes": 180}, "Deploys / config changes / flags, last 3 h"),
)

TOPOLOGY = (
    "System: api-gateway calls auth and checkout; checkout calls inventory and payments; inventory consumes "
    "Kafka topic 'orders' (consumer group inventory-orders); payments calls external APIs payment-provider "
    "(api.payprovider.example) and fraudscore-api (api.fraudscore.example). Cluster DNS is coredns at 10.96.0.10."
)

SYSTEM = (
    f"""You are a senior SRE finding the root cause of a production incident.
{TOPOLOGY}
Failures propagate from callees to callers. Caller logs such as "upstream X returned 503" or "timeout calling X"
are symptoms; the origin is usually the deepest degraded service, or an external/shared component it depends on.
A change is the cause only if its time matches when the errors began; unrelated changes are common.
Root-cause categories:
"""
    + "\n".join(f"- {c.value}: {d}" for c, d in CATEGORY_DESCRIPTIONS.items())
    + """
Base every claim on the evidence and quote concrete values."""
)

FINAL_INSTRUCTIONS = (
    "Now give the final root-cause analysis as JSON. category must be one of the listed categories. "
    "root_cause_service is where the problem originates (an internal service, or payment-provider, "
    "fraudscore-api, coredns, orders-topic). confidence is 0-1. evidence: 2-5 items quoting the data above."
)


async def gather_evidence(ctx: RunContext) -> dict[str, dict[str, Any]]:
    evidence: dict[str, dict[str, Any]] = {}
    for tool, args, label in PREFETCH:
        try:
            evidence[tool] = await ctx.toolbox.call(tool, args)
            ctx.usage.tool_calls += 1
            ctx.trace.add(
                "investigator",
                "tool",
                f"{tool}: {label}",
                arguments=args,
                result=compact(tool, evidence[tool]),
            )
        except ToolError as exc:
            ctx.trace.add("investigator", "error", f"{tool} failed", error=str(exc))
    return evidence


def evidence_prompt(evidence: dict[str, dict[str, Any]]) -> str:
    now = datetime.now(UTC)
    parts = [f"Current time: {now.strftime('%H:%M:%S')} UTC."]
    for tool, _, label in PREFETCH:
        if tool in evidence:
            parts.append(f"[{label}]\n{compact(tool, evidence[tool], now)}")
    return "\n\n".join(parts)


async def investigate(
    triage: TriageSummary, alerts: list[dict[str, Any]], ctx: RunContext
) -> tuple[RootCauseHypothesis, dict[str, dict[str, Any]]]:
    route = ctx.router.route("investigator")
    evidence = await gather_evidence(ctx) if route.options.get("prefetch_evidence", True) else {}
    if not ctx.router.uses_llm("investigator"):
        hypothesis = heuristic_hypothesis(evidence)
        ctx.trace.add(
            "investigator", "decision", "Root cause from rules", **hypothesis.model_dump(mode="json")
        )
        return hypothesis, evidence

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM},
        {
            "role": "user",
            "content": (
                f"Incident: {triage.title}\n{triage.summary}\nAlerts ({len(alerts)}):\n{alert_digest(alerts, 8)}\n\n"
                f"{evidence_prompt(evidence)}\n\nIf something important is unclear, call a tool to check it "
                f"(at most {route.options.get('max_tool_calls', 3)} calls). Otherwise state your conclusion in at most "
                "two sentences."
            ),
        },
    ]
    try:
        await _tool_loop(
            messages,
            ctx,
            int(route.options.get("max_tool_calls", 3)),
            int(route.options.get("reasoning_max_tokens", 160)),
        )
        messages.append({"role": "user", "content": FINAL_INSTRUCTIONS})
        hypothesis = await ctx.router.structured("investigator", messages, RootCauseHypothesis, ctx.usage)
    except LLMError as exc:
        ctx.trace.add(
            "investigator", "error", "Investigator models failed; falling back to rules", error=str(exc)
        )
        hypothesis = heuristic_hypothesis(evidence)
        ctx.trace.add(
            "investigator",
            "decision",
            "Root cause from rules (fallback)",
            **hypothesis.model_dump(mode="json"),
        )
        return hypothesis, evidence
    ctx.trace.add(
        "investigator",
        "llm",
        "Root-cause hypothesis",
        model=ctx.usage.records[-1].model,
        **hypothesis.model_dump(mode="json"),
    )
    return hypothesis, evidence


async def _tool_loop(
    messages: list[dict[str, Any]], ctx: RunContext, max_calls: int, max_tokens: int
) -> None:
    specs = ctx.toolbox.specs(INVESTIGATION_TOOLS)
    calls = 0
    while True:
        tools = specs if calls < max_calls else None
        result = await ctx.router.chat(
            "investigator", messages, ctx.usage, tools=tools, max_tokens=max_tokens
        )
        messages.append(
            {
                "role": "assistant",
                "content": result.content,
                **(
                    {
                        "tool_calls": [
                            {"function": {"name": c.name, "arguments": c.arguments}}
                            for c in result.tool_calls
                        ]
                    }
                    if result.tool_calls
                    else {}
                ),
            }
        )
        if not result.tool_calls:
            if result.content.strip():
                ctx.trace.add("investigator", "llm", "Reasoning", model=result.model, text=result.content)
            return
        for call in result.tool_calls[: max(0, max_calls - calls)]:
            calls += 1
            try:
                output = compact(call.name, await ctx.toolbox.call(call.name, call.arguments))
                ctx.usage.tool_calls += 1
            except ToolError as exc:
                output = f"ERROR: {exc}"
            ctx.trace.add(
                "investigator",
                "tool",
                f"{call.name} (requested by model)",
                arguments=call.arguments,
                result=output,
            )
            messages.append({"role": "tool", "content": output, "tool_name": call.name})
        if calls >= max_calls:
            messages.append(
                {"role": "user", "content": "Tool budget used up. State your conclusion briefly."}
            )


# ---------------------------------------------------------------------------------------------------------------
# Rules baseline. Written with knowledge of the simulator's log vocabulary, so treat its eval score as an
# optimistic "keyword matcher" baseline, not as a fair competitor to the LLM.
# ---------------------------------------------------------------------------------------------------------------

_RULES: tuple[tuple[RootCauseCategory, str, str | None], ...] = (
    # (category, regex over "service level message" lines, fixed root service or None = the logging service)
    (RootCauseCategory.TLS_CERT_EXPIRED, r"x509|certificate has expired", None),
    (RootCauseCategory.DNS_FAILURE, r"lookup .* on 10\.96\.0\.10:53|SERVFAIL", "coredns"),
    (RootCauseCategory.DISK_FULL, r"No space left on device", None),
    (RootCauseCategory.MEMORY_LEAK, r"OutOfMemoryError|OOMKilled", None),
    (RootCauseCategory.THIRD_PARTY_RATE_LIMIT, r"429 Too Many Requests", "fraudscore-api"),
    (RootCauseCategory.KAFKA_CONSUMER_LAG, r"max\.poll\.interval\.ms|rebalanc", None),
    (RootCauseCategory.CONFIG_ERROR, r"no healthy upstream", None),
    (RootCauseCategory.DB_POOL_EXHAUSTION, r"Connection is not available", None),
    (
        RootCauseCategory.UPSTREAM_OUTAGE,
        r"api\.payprovider\.example.*(503|reset|refused)",
        "payment-provider",
    ),
    (RootCauseCategory.SLOW_DEPENDENCY, r"slow query", None),
)


def heuristic_hypothesis(evidence: dict[str, dict[str, Any]]) -> RootCauseHypothesis:
    patterns = evidence.get("log_error_summary", {}).get("patterns", [])
    anomalies = evidence.get("detect_metric_anomalies", {}).get("anomalies", [])
    changes = evidence.get("list_recent_changes", {}).get("changes", [])
    lines = [(p["service"], f"{p['level']} {p['example']}", p) for p in patterns]

    # x509 errors are logged by the caller; the certificate belongs to the upstream named in the message.
    for category, regex, fixed_service in _RULES:
        for service, text, pattern in lines:
            if re.search(regex, text, re.IGNORECASE):
                root = fixed_service or service
                if category == RootCauseCategory.TLS_CERT_EXPIRED:
                    upstream = re.search(r"upstream (\S+?):", text)
                    root = upstream.group(1) if upstream else service
                return _hypothesis(
                    category,
                    root,
                    f"Log pattern on {service} matches {category.value}: {pattern['example'][:200]}",
                    pattern,
                )

    for anomaly in anomalies:
        if anomaly["metric"] == "cpu_throttled_percent" and anomaly["recent_avg"] > 25:
            return _hypothesis(
                RootCauseCategory.CPU_THROTTLING,
                anomaly["service"],
                f"{anomaly['service']} CPU throttled {anomaly['recent_avg']:.0f}% of periods",
                None,
                metrics=anomaly,
            )
        if anomaly["metric"] == "kafka_consumer_lag" and anomaly["recent_avg"] > 10_000:
            return _hypothesis(
                RootCauseCategory.KAFKA_CONSUMER_LAG,
                anomaly["service"],
                f"consumer lag {anomaly['recent_avg']:.0f}",
                None,
                metrics=anomaly,
            )

    exceptions = [p for p in patterns if re.search(r"Exception|Error:", p["example"])]
    for pattern in exceptions:
        deploys = [c for c in changes if c["service"] == pattern["service"] and c["kind"] == "deploy"]
        for deploy in deploys:
            gap = abs(
                (
                    datetime.fromisoformat(deploy["ts"]) - datetime.fromisoformat(pattern["first_seen"])
                ).total_seconds()
            )
            if gap <= 300:
                return _hypothesis(
                    RootCauseCategory.BAD_DEPLOYMENT,
                    pattern["service"],
                    f"Deploy {deploy.get('version')} at {deploy['ts']} preceded new errors: "
                    f"{pattern['example'][:160]}",
                    pattern,
                    change=deploy,
                )

    timeouts = [p for p in patterns if "timeout calling" in p["example"]]
    if timeouts:
        upstream = re.search(r"timeout calling (\S+)", timeouts[0]["example"])
        return _hypothesis(
            RootCauseCategory.SLOW_DEPENDENCY,
            upstream.group(1) if upstream else "unknown",
            timeouts[0]["example"],
            timeouts[0],
        )

    return RootCauseHypothesis(
        category=RootCauseCategory.UNKNOWN,
        root_cause_service=patterns[0]["service"] if patterns else "unknown",
        hypothesis="No rule matched the evidence.",
        confidence=0.2,
        evidence=[Evidence(source="logs", finding=json.dumps(patterns[:1])[:300] or "no error logs")],
    )


def _hypothesis(
    category: RootCauseCategory,
    service: str,
    finding: str,
    pattern: dict[str, Any] | None,
    *,
    metrics: dict[str, Any] | None = None,
    change: dict[str, Any] | None = None,
) -> RootCauseHypothesis:
    evidence = [Evidence(source="logs" if pattern else "metrics", finding=finding[:300])]
    if metrics:
        evidence.append(
            Evidence(
                source="metrics",
                finding=f"{metrics['service']}.{metrics['metric']}: "
                f"{metrics['baseline_avg']} -> {metrics['recent_avg']}",
            )
        )
    if change:
        evidence.append(
            Evidence(
                source="deploys",
                finding=f"{change['service']} {change['kind']} "
                f"{change.get('version') or ''}: {change['description']}"[:300],
            )
        )
    return RootCauseHypothesis(
        category=category,
        root_cause_service=service,
        hypothesis=f"Rules matched {category.value} on {service}.",
        confidence=0.6,
        evidence=evidence,
    )

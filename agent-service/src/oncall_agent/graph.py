"""The incident workflow as a LangGraph state machine.

    triage ─► investigate ─┬─► remediate ─► guardrails ─┬─► persist ─► notify
                           └──────────(failed)──────────┘

Nothing is ever executed here. The furthest an incident gets is ``PENDING_APPROVAL``; execution only happens
(as a dry run) after a human approves, in ``executor.py``.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from oncall_agent import guardrails
from oncall_agent.agents import RunContext, investigator, remediation, triage
from oncall_agent.notifications import IncidentNotice, NotificationError
from oncall_agent.schemas import ProposedAction, RootCauseHypothesis, TriageSummary
from oncall_common.taxonomy import ActionType, RootCauseCategory
from oncall_common.telemetry import CHAIN, span

log = logging.getLogger(__name__)


class IncidentState(TypedDict, total=False):
    incident_id: str | None
    alerts: list[dict[str, Any]]
    triage: dict[str, Any]
    hypothesis: dict[str, Any] | None
    runbook_id: str | None
    proposal: dict[str, Any] | None
    guardrail: dict[str, Any] | None
    status: str
    summary: str
    error: str | None
    notified: bool
    notified_via: str


async def triage_node(state: IncidentState, runtime: Runtime[RunContext]) -> IncidentState:
    summary = await triage.summarize(state["alerts"], runtime.context)
    return {"triage": summary.model_dump(mode="json")}


async def investigate_node(state: IncidentState, runtime: Runtime[RunContext]) -> IncidentState:
    ctx = runtime.context
    if ctx.alert_client and state.get("incident_id"):
        try:
            await ctx.alert_client.set_status(state["incident_id"], "INVESTIGATING")
        except Exception as exc:  # status is cosmetic; never block the investigation on it
            log.warning("could not mark incident investigating: %s", exc)
    try:
        hypothesis, _ = await investigator.investigate(TriageSummary(**state["triage"]), state["alerts"], ctx)
    except Exception as exc:
        log.exception("investigation failed")
        ctx.trace.add("investigator", "error", "Investigation failed", error=str(exc))
        return {"hypothesis": None, "error": f"investigation failed: {exc}"}
    return {"hypothesis": hypothesis.model_dump(mode="json")}


def after_investigation(state: IncidentState) -> str:
    return "remediate" if state.get("hypothesis") else "persist"


async def remediate_node(state: IncidentState, runtime: Runtime[RunContext]) -> IncidentState:
    hypothesis = RootCauseHypothesis(**state["hypothesis"])
    proposal, runbook = await remediation.propose(hypothesis, runtime.context)
    return {
        "proposal": proposal.model_dump(mode="json"),
        "runbook_id": runbook["runbook_id"] if runbook else None,
        "guardrail": {"runbook_actions": runbook["allowed_actions"] if runbook else None},
    }


async def guardrails_node(state: IncidentState, runtime: Runtime[RunContext]) -> IncidentState:
    ctx = runtime.context
    proposal = ProposedAction(**state["proposal"])
    runbook_actions = (state.get("guardrail") or {}).get("runbook_actions")
    final, verdict = guardrails.check(
        proposal,
        confidence=state["hypothesis"]["confidence"],
        runbook_actions=runbook_actions,
        policy=ctx.policy,
    )
    ctx.trace.add(
        "guardrails",
        "guardrail",
        "Proposal approved for human review" if verdict.allowed else "Proposal blocked",
        allowed=verdict.allowed,
        violations=verdict.violations,
        final_action=final.action,
        dry_run=final.dry_run,
    )
    return {"proposal": final.model_dump(mode="json"), "guardrail": verdict.model_dump(mode="json")}


def compose_summary(state: IncidentState) -> tuple[str, str]:
    """(status, human-readable summary) for the alert service."""
    tri = state["triage"]
    hypothesis, proposal = state.get("hypothesis"), state.get("proposal")
    if not hypothesis:
        return "FAILED", f"{tri['summary']} Automated investigation failed: {state.get('error')}"
    text = (
        f"{tri['summary']} Likely root cause: {hypothesis['category']} on {hypothesis['root_cause_service']} "
        f"({hypothesis['confidence']:.0%} confidence). {hypothesis['hypothesis']}"
    )
    actionable = (
        proposal
        and proposal["action"] != ActionType.ESCALATE_TO_HUMAN.value
        and hypothesis["category"] != RootCauseCategory.UNKNOWN.value
    )
    if actionable:
        return "PENDING_APPROVAL", text + (
            f" Proposed: {proposal['action']} on {proposal['target']} (dry run) - awaiting human approval."
        )
    return "NEEDS_HUMAN", text + " No safe automated action; a human needs to take over."


async def persist_node(state: IncidentState, runtime: Runtime[RunContext]) -> IncidentState:
    ctx = runtime.context
    status, summary = compose_summary(state)
    hypothesis, proposal = state.get("hypothesis"), state.get("proposal")
    if proposal is not None:
        proposal = {**proposal, "guardrail": state.get("guardrail")}
    ctx.trace.add("persist", "decision", f"Incident -> {status}")
    analysis = {
        "status": status,
        "title": state["triage"]["title"],
        "severity": state["triage"]["severity"],
        "summary": summary,
        "rootCause": hypothesis,
        "proposedAction": proposal if status == "PENDING_APPROVAL" else (proposal or None),
        "reasoningTrace": ctx.trace.steps,
        "llmUsage": ctx.usage.summary(),
    }
    if ctx.alert_client and state.get("incident_id"):
        await ctx.alert_client.record_analysis(state["incident_id"], analysis)
    return {"status": status, "summary": summary}


async def notify_node(state: IncidentState, runtime: Runtime[RunContext]) -> IncidentState:
    """One summary message per incident; failures are logged, never fatal."""
    ctx = runtime.context
    if not ctx.notifier:
        return {"notified": False}
    notice = IncidentNotice.from_state(state, ctx.dashboard_url, ctx.usage.summary())
    try:
        channel = await ctx.notifier.notify(notice)
    except NotificationError as exc:
        log.warning("notification failed for incident %s: %s", state.get("incident_id"), exc)
        return {"notified": False}
    if ctx.alert_client and state.get("incident_id"):
        await ctx.alert_client.mark_notified(state["incident_id"])
    return {"notified": True, "notified_via": channel}


Node = Callable[[IncidentState, Runtime[RunContext]], Awaitable[IncidentState]]


def traced(name: str, node: Node) -> Node:
    """Wrap a node in an OpenTelemetry span so each step shows up in Jaeger and Phoenix."""

    @wraps(node)
    async def run(state: IncidentState, runtime: Runtime[RunContext]) -> IncidentState:
        with span(
            f"agent.{name}", kind=CHAIN, attributes={"incident.id": state.get("incident_id")}
        ) as current:
            update = await node(state, runtime)
            for key in ("status", "notified"):
                if key in update:
                    current.set_attribute(f"incident.{key}", str(update[key]))
            if update.get("hypothesis"):
                current.set_attribute("incident.root_cause", update["hypothesis"]["category"])
            return update

    return run


def build_graph():
    graph = StateGraph(IncidentState, context_schema=RunContext)
    for name, node in (
        ("triage", triage_node),
        ("investigate", investigate_node),
        ("remediate", remediate_node),
        ("guardrails", guardrails_node),
        ("persist", persist_node),
        ("notify", notify_node),
    ):
        graph.add_node(name, traced(name, node))
    graph.add_edge(START, "triage")
    graph.add_edge("triage", "investigate")
    graph.add_conditional_edges("investigate", after_investigation, ["remediate", "persist"])
    graph.add_edge("remediate", "guardrails")
    graph.add_edge("guardrails", "persist")
    graph.add_edge("persist", "notify")
    graph.add_edge("notify", END)
    return graph.compile()

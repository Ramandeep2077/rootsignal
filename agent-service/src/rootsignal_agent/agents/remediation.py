"""Remediation agent: retrieves the matching runbook (pgvector search via MCP) and proposes one action."""

from __future__ import annotations

import re
from typing import Any

from rootsignal_agent.agents import RunContext
from rootsignal_agent.guardrails import KNOWN_TARGETS
from rootsignal_agent.llm.base import LLMError
from rootsignal_agent.schemas import ProposedAction, RootCauseHypothesis
from rootsignal_agent.tools import ToolError, compact
from rootsignal_common.taxonomy import CATEGORY_DESCRIPTIONS, ActionType, RiskLevel

SYSTEM = (
    "You are an SRE proposing ONE remediation for a diagnosed incident, strictly following the team runbook. "
    "The action must be exactly one of the allowed action names. Prefer the lowest-risk action that addresses "
    "the root cause. Steps must be concrete and safe; never propose deleting data, disabling monitoring or "
    "running arbitrary shell commands. A human will review your proposal before anything runs."
)

MEDIUM_RISK = {ActionType.FAILOVER_PROVIDER.value, ActionType.INCREASE_MEMORY_LIMIT.value}


def _section(markdown: str, heading: str) -> str:
    match = re.search(rf"^## {heading}\n(.*?)(?=^## |\Z)", markdown, re.MULTILINE | re.DOTALL)
    return match.group(1).strip() if match else ""


async def find_runbook(hypothesis: RootCauseHypothesis, ctx: RunContext) -> dict[str, Any] | None:
    category = hypothesis.category
    # Expand the query with the category's description so retrieval doesn't hinge on the model's wording.
    query = (
        f"{category.value.replace('_', ' ')}: {CATEGORY_DESCRIPTIONS[category]} "
        f"Service: {hypothesis.root_cause_service}. {hypothesis.hypothesis}"
    )
    try:
        found = await ctx.toolbox.call("search_runbooks", {"query": query[:500], "k": 5})
        ctx.usage.tool_calls += 1
        results = found.get("results", [])
        ctx.trace.add(
            "remediation",
            "tool",
            "search_runbooks",
            arguments={"query": query[:200]},
            result=compact("search_runbooks", found),
        )
        if not results:
            return None
        # Retrieval proposes; the category label disposes: prefer a runbook written for this category.
        chosen = next((r for r in results if hypothesis.category.value in r["categories"]), results[0])
        runbook = await ctx.toolbox.call("get_runbook", {"runbook_id": chosen["runbook_id"]})
        ctx.usage.tool_calls += 1
        ctx.trace.add(
            "remediation",
            "tool",
            f"get_runbook {chosen['runbook_id']}",
            score=chosen["score"],
            allowed_actions=runbook["allowed_actions"],
        )
        return runbook
    except ToolError as exc:
        ctx.trace.add("remediation", "error", "Runbook lookup failed", error=str(exc))
        return None


def heuristic_action(hypothesis: RootCauseHypothesis, runbook: dict[str, Any] | None) -> ProposedAction:
    if not runbook or not runbook["allowed_actions"]:
        return ProposedAction(
            action=ActionType.ESCALATE_TO_HUMAN.value,
            target=hypothesis.root_cause_service,
            risk_level=RiskLevel.LOW,
            steps=["Page the owning team with the gathered evidence."],
            rollback_plan="Not applicable.",
            rationale="No runbook matched this root cause.",
        )
    action = runbook["allowed_actions"][0]
    remediation = _section(runbook["markdown"], "Remediation")
    steps = [
        line.lstrip("- ").replace("**", "") for line in remediation.splitlines() if line.startswith("- ")
    ]
    return ProposedAction(
        action=action,
        target=hypothesis.root_cause_service,
        risk_level=RiskLevel.MEDIUM if action in MEDIUM_RISK else RiskLevel.LOW,
        steps=(steps or [f"Apply {action} to {hypothesis.root_cause_service} as described in the runbook."])[
            :8
        ],
        rollback_plan=_section(runbook["markdown"], "Rollback")[:500] or "Revert the change.",
        rationale=f"Runbook {runbook['runbook_id']} recommends {action} for {hypothesis.category.value}.",
        runbook_id=runbook["runbook_id"],
    )


async def propose(
    hypothesis: RootCauseHypothesis, ctx: RunContext
) -> tuple[ProposedAction, dict[str, Any] | None]:
    runbook = await find_runbook(hypothesis, ctx)
    fallback = heuristic_action(hypothesis, runbook)
    if not ctx.router.uses_llm("remediation") or runbook is None:
        ctx.trace.add(
            "remediation", "decision", "Action from runbook (rules)", **fallback.model_dump(mode="json")
        )
        return fallback, runbook

    allowed = [*runbook["allowed_actions"], ActionType.ESCALATE_TO_HUMAN.value]
    messages = [
        {"role": "system", "content": SYSTEM},
        {
            "role": "user",
            "content": (
                f"Root cause: {hypothesis.category.value} on {hypothesis.root_cause_service} "
                f"(confidence {hypothesis.confidence:.2f}). {hypothesis.hypothesis}\n\n"
                f"Runbook '{runbook['runbook_id']}' — {runbook['title']}\n"
                f"Remediation:\n{_section(runbook['markdown'], 'Remediation')}\n"
                f"Rollback:\n{_section(runbook['markdown'], 'Rollback')}\n\n"
                f"Allowed actions: {', '.join(allowed)}\n"
                f"Valid targets: {', '.join(sorted(KNOWN_TARGETS))}\n"
                f"Set runbook_id to '{runbook['runbook_id']}' and dry_run to true. Reply with JSON."
            ),
        },
    ]
    try:
        proposal = await ctx.router.structured("remediation", messages, ProposedAction, ctx.usage)
    except LLMError as exc:
        ctx.trace.add(
            "remediation", "error", "Remediation models failed; using runbook default", error=str(exc)
        )
        return fallback, runbook
    ctx.trace.add(
        "remediation",
        "llm",
        "Proposed remediation",
        model=ctx.usage.records[-1].model,
        **proposal.model_dump(mode="json"),
    )
    return proposal, runbook

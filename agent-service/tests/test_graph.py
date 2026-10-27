"""End-to-end agent graph runs against real (in-process) MCP servers and Postgres."""

import pytest

from rootsignal_agent.agents import RunContext
from rootsignal_agent.graph import build_graph
from rootsignal_agent.guardrails import GuardrailPolicy
from rootsignal_agent.llm.router import ModelRouter, UsageTracker
from rootsignal_agent.routing import load_routing
from rootsignal_agent.settings import AgentSettings
from rootsignal_agent.testing import FakeAlertClient, ScriptedChat, tool_call
from rootsignal_agent.tools import Toolbox
from rootsignal_agent.trace import Trace
from rootsignal_common.taxonomy import ActionType
from rootsignal_sim.scenarios import SCENARIOS
from rootsignal_sim.testing import as_events
from rootsignal_sim.testing import load_scenario as load

pytestmark = pytest.mark.integration


async def run(mcp_servers, alerts, *, profile="heuristic", chat=None, client=None):
    routing = load_routing(
        AgentSettings(_env_file=None, llm_provider="mock" if chat is None else "ollama"), profile
    )
    async with Toolbox(mcp_servers) as toolbox:
        ctx = RunContext(
            router=ModelRouter(routing, chat),
            toolbox=toolbox,
            trace=Trace(),
            usage=UsageTracker(routing.pricing),
            policy=GuardrailPolicy(),
            alert_client=client,
        )
        incident_id = None
        if client:
            incident_id = (await client.create_incident("t", "HIGH", ["x"], [a["id"] for a in alerts]))["id"]
        state = await build_graph().ainvoke({"incident_id": incident_id, "alerts": alerts}, context=ctx)
    return state, ctx


@pytest.mark.parametrize("name", sorted(SCENARIOS))
async def test_rules_pipeline_end_to_end(pg_dsn, mcp_servers, name):
    out = load(pg_dsn, name)
    alerts = [a for a in as_events(out) if not a["noise"]]
    client = FakeAlertClient()
    state, _ctx = await run(mcp_servers, alerts, client=client)

    gt = out.ground_truth
    assert state["hypothesis"]["category"] == gt.category.value
    assert state["status"] == "PENDING_APPROVAL"
    assert state["proposal"]["action"] in {a.value for a in gt.expected_actions}
    assert state["proposal"]["dry_run"] is True
    incident = next(iter(client.incidents.values()))
    assert incident["status"] == "PENDING_APPROVAL"
    assert incident["reasoningTrace"] and incident["llmUsage"]["tool_calls"] >= 5
    assert {s["agent"] for s in incident["reasoningTrace"]} >= {
        "triage",
        "investigator",
        "remediation",
        "guardrails",
    }


async def test_llm_path_with_tool_call_and_injected_unsafe_proposal(pg_dsn, mcp_servers):
    out = load(pg_dsn, "disk_full")
    alerts = [a for a in as_events(out) if not a["noise"]]
    chat = ScriptedChat(
        [
            {
                "title": "Payments failing",
                "severity": "HIGH",
                "affected_services": ["payments", "nope"],
                "summary": "Payments errors.",
            },
            [tool_call("search_logs", service="payments", keyword="No space", since_minutes=60)],
            "Disk on payments is full.",
            {
                "category": "disk_full",
                "root_cause_service": "payments",
                "hypothesis": "Volume full.",
                "confidence": 0.9,
                "evidence": [{"source": "logs", "finding": "No space left on device"}],
            },
            {
                "action": "free_disk_space",
                "target": "payments",
                "risk_level": "low",
                "steps": ["rm -rf /var/lib/postgresql to make room"],
                "rollback_plan": "none",
                "rationale": "space",
            },
        ]
    )
    state, ctx = await run(mcp_servers, alerts, profile="routed", chat=chat, client=FakeAlertClient())

    assert state["triage"]["affected_services"] == ["payments"], "hallucinated services are dropped"
    assert any(s["title"].startswith("search_logs (requested by model)") for s in ctx.trace.steps)
    assert state["hypothesis"]["category"] == "disk_full"
    assert state["guardrail"]["allowed"] is False
    assert state["proposal"]["action"] == ActionType.ESCALATE_TO_HUMAN
    assert state["status"] == "NEEDS_HUMAN"


async def test_all_models_failing_falls_back_to_rules(pg_dsn, mcp_servers):
    from rootsignal_agent.llm.base import LLMError

    out = load(pg_dsn, "dns_failure")
    alerts = [a for a in as_events(out) if not a["noise"]]
    chat = ScriptedChat([LLMError("down", retriable=False)] * 20)
    state, ctx = await run(mcp_servers, alerts, profile="routed", chat=chat)
    assert state["hypothesis"]["category"] == "dns_failure"
    assert state["status"] == "PENDING_APPROVAL"
    assert ctx.usage.summary()["failed_calls"] >= 3

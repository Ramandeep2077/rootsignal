import pytest

from rootsignal_agent.llm.base import LLMError
from rootsignal_agent.llm.router import ModelRouter, UsageTracker
from rootsignal_agent.routing import HEURISTIC, load_routing
from rootsignal_agent.schemas import TriageSummary
from rootsignal_agent.settings import AgentSettings
from rootsignal_agent.testing import ScriptedChat


def settings(**kw):
    return AgentSettings(_env_file=None, **{"llm_provider": "ollama", **kw})


def test_routed_profile_uses_small_model_for_triage_and_large_for_rca():
    routing = load_routing(settings(), "routed")
    assert routing["triage"].model == "qwen2.5:1.5b"
    assert routing["investigator"].model == "qwen2.5:7b"
    assert routing["investigator"].chain == ("qwen2.5:7b", "qwen2.5:1.5b", HEURISTIC)
    assert routing["investigator"].options["max_tool_calls"] == 3


def test_mock_provider_forces_heuristic_profile_even_with_overrides():
    routing = load_routing(settings(llm_provider="mock", investigator_model="qwen2.5:7b"), "routed")
    assert routing.profile == HEURISTIC
    assert {r.model for r in routing.routes.values()} == {HEURISTIC}


def test_env_override_wins_over_profile():
    routing = load_routing(settings(investigator_model="qwen2.5:3b"), "routed")
    assert routing["investigator"].model == "qwen2.5:3b"


def test_unknown_profile_is_an_error():
    with pytest.raises(ValueError, match="Available"):
        load_routing(settings(), "gpt-everything")


async def _no_sleep(_):
    return None


async def test_router_retries_then_falls_back_and_meters_usage():
    routing = load_routing(settings(llm_max_retries=1), "routed")
    chat = ScriptedChat([LLMError("timeout"), LLMError("timeout"), "fallback answer"])
    router = ModelRouter(routing, chat, sleep=_no_sleep)
    usage = UsageTracker(routing.pricing)

    result = await router.chat("investigator", [{"role": "user", "content": "hi"}], usage)

    assert result.content == "fallback answer"
    assert [c["model"] for c in chat.calls] == ["qwen2.5:7b", "qwen2.5:7b", "qwen2.5:1.5b"]
    summary = usage.summary()
    assert summary["failed_calls"] == 2 and summary["llm_calls"] == 1
    assert summary["total_tokens"] == 160
    assert summary["estimated_cost_usd"] == 0.0


async def test_non_retriable_error_skips_retries():
    routing = load_routing(settings(llm_max_retries=3), "small_only")
    chat = ScriptedChat([LLMError("model missing", retriable=False)])
    router = ModelRouter(routing, chat, sleep=_no_sleep)
    with pytest.raises(LLMError):
        await router.chat("triage", [], UsageTracker({}))
    assert len(chat.calls) == 1


async def test_structured_output_gets_one_repair_attempt():
    routing = load_routing(settings(), "routed")
    good = {
        "title": "Errors on checkout",
        "severity": "HIGH",
        "affected_services": ["checkout"],
        "summary": "Checkout fails.",
    }
    chat = ScriptedChat(['{"title": "x"}', good])
    router = ModelRouter(routing, chat, sleep=_no_sleep)
    result = await router.structured(
        "triage", [{"role": "user", "content": "go"}], TriageSummary, UsageTracker({})
    )
    assert result.title == "Errors on checkout"
    assert chat.calls[0]["schema"]["title"] == "TriageSummary"
    assert "invalid" in chat.calls[1]["messages"][-1]["content"]


def test_pricing_is_applied_per_model():
    usage = UsageTracker({"hosted": {"input": 3.0, "output": 15.0}})
    assert usage.cost("hosted", 1_000_000, 100_000) == pytest.approx(4.5)
    assert usage.cost("unknown-local", 10_000, 10_000) == 0.0

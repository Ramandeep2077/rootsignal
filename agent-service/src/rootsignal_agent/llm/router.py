"""Resilient, metered model calls: timeouts, retries with exponential backoff, fallback chain, usage tracking."""

from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from rootsignal_agent.llm.base import ChatModel, ChatResult, LLMError
from rootsignal_agent.routing import HEURISTIC, AgentRoute, Routing

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


@dataclass
class UsageRecord:
    agent: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    cost_usd: float
    ok: bool
    error: str | None = None


@dataclass
class UsageTracker:
    """Collects every model call made while handling one incident."""

    pricing: dict[str, dict[str, float]]
    records: list[UsageRecord] = field(default_factory=list)
    tool_calls: int = 0

    def cost(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        price = self.pricing.get(model, {"input": 0.0, "output": 0.0})
        return (prompt_tokens * price.get("input", 0.0) + completion_tokens * price.get("output", 0.0)) / 1e6

    def record(self, agent: str, result: ChatResult) -> None:
        self.records.append(
            UsageRecord(
                agent,
                result.model,
                result.prompt_tokens,
                result.completion_tokens,
                round(result.latency_ms, 1),
                self.cost(result.model, result.prompt_tokens, result.completion_tokens),
                ok=True,
            )
        )

    def record_failure(self, agent: str, model: str, error: str, latency_ms: float = 0.0) -> None:
        self.records.append(UsageRecord(agent, model, 0, 0, round(latency_ms, 1), 0.0, ok=False, error=error))

    def summary(self) -> dict[str, Any]:
        ok = [r for r in self.records if r.ok]
        by_agent: dict[str, dict[str, Any]] = {}
        for r in self.records:
            entry = by_agent.setdefault(
                r.agent, {"calls": 0, "failures": 0, "tokens": 0, "latency_ms": 0.0, "models": []}
            )
            entry["calls"] += 1
            entry["failures"] += 0 if r.ok else 1
            entry["tokens"] += r.prompt_tokens + r.completion_tokens
            entry["latency_ms"] = round(entry["latency_ms"] + r.latency_ms, 1)
            if r.model not in entry["models"]:
                entry["models"].append(r.model)
        prompt = sum(r.prompt_tokens for r in ok)
        completion = sum(r.completion_tokens for r in ok)
        return {
            "llm_calls": len(ok),
            "failed_calls": len(self.records) - len(ok),
            "tool_calls": self.tool_calls,
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
            "llm_latency_ms": round(sum(r.latency_ms for r in self.records), 1),
            "estimated_cost_usd": round(sum(r.cost_usd for r in ok), 6),
            "by_agent": by_agent,
            "calls": [asdict(r) for r in self.records],
        }


class ModelRouter:
    """Calls the model configured for an agent; on failure retries, then walks the fallback chain."""

    def __init__(
        self,
        routing: Routing,
        client: ChatModel | None,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.routing = routing
        self.client = client
        self._sleep = sleep

    def route(self, agent: str) -> AgentRoute:
        return self.routing[agent]

    def uses_llm(self, agent: str) -> bool:
        return self.routing[agent].model != HEURISTIC and self.client is not None

    async def chat(
        self,
        agent: str,
        messages: list[dict[str, Any]],
        usage: UsageTracker,
        *,
        tools: list[dict[str, Any]] | None = None,
        schema: dict[str, Any] | None = None,
        max_tokens: int | None = None,
    ) -> ChatResult:
        """Returns the first successful result along the chain; raises LLMError when only the heuristic is left."""
        route = self.routing[agent]
        errors: list[str] = []
        for model in route.chain:
            if model == HEURISTIC or self.client is None:
                break
            for attempt in range(route.max_retries + 1):
                try:
                    result = await self.client.chat(
                        model,
                        messages,
                        tools=tools,
                        schema=schema,
                        temperature=route.temperature,
                        max_tokens=max_tokens or route.max_tokens,
                        num_ctx=route.num_ctx,
                        timeout=route.timeout_seconds,
                    )
                    usage.record(agent, result)
                    return result
                except LLMError as exc:
                    usage.record_failure(agent, model, str(exc))
                    errors.append(f"{model}: {exc}")
                    log.warning("%s call to %s failed (attempt %d): %s", agent, model, attempt + 1, exc)
                    if not exc.retriable:
                        break
                    if attempt < route.max_retries:
                        await self._sleep(min(30.0, 2.0**attempt + random.uniform(0, 0.5)))
        raise LLMError("; ".join(errors) or "no LLM configured for this agent", retriable=False)

    async def structured(
        self,
        agent: str,
        messages: list[dict[str, Any]],
        output: type[T],
        usage: UsageTracker,
        *,
        max_tokens: int | None = None,
    ) -> T:
        """Chat with JSON-schema constrained decoding and validate into ``output`` (one repair attempt)."""
        schema = output.model_json_schema()
        result = await self.chat(agent, messages, usage, schema=schema, max_tokens=max_tokens)
        try:
            return output.model_validate_json(result.content)
        except ValidationError as first:
            repair = [
                *messages,
                {"role": "assistant", "content": result.content},
                {
                    "role": "user",
                    "content": "That JSON was invalid: "
                    f"{_short(first)}. Reply again with ONLY valid JSON matching the schema.",
                },
            ]
            retry = await self.chat(agent, repair, usage, schema=schema, max_tokens=max_tokens)
            try:
                return output.model_validate_json(retry.content)
            except ValidationError as second:
                raise LLMError(
                    f"invalid structured output from {retry.model}: {_short(second)}", retriable=False
                ) from second


def _short(error: ValidationError) -> str:
    return json.dumps([{"loc": e["loc"], "msg": e["msg"]} for e in error.errors()[:3]], default=str)

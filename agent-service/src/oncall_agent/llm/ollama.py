"""Ollama chat client using the native /api/chat endpoint.

Talking to Ollama directly (rather than through a framework wrapper) gives exact token counts
(``prompt_eval_count`` / ``eval_count``), native tool calling, and JSON-schema constrained decoding
(``format``) for structured outputs.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from oncall_agent.llm.base import ChatResult, LLMError, ToolCall
from oncall_common.telemetry import LLM, clip, span


class OllamaChat:
    def __init__(self, base_url: str, client: httpx.AsyncClient | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        schema: dict[str, Any] | None = None,
        temperature: float = 0.1,
        max_tokens: int = 400,
        num_ctx: int = 8192,
        timeout: float = 240.0,
    ) -> ChatResult:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "keep_alive": "30m",
            "options": {"temperature": temperature, "num_predict": max_tokens, "num_ctx": num_ctx},
        }
        if tools:
            payload["tools"] = tools
        if schema:
            payload["format"] = schema
        attributes = {
            "llm.model_name": model,
            "llm.provider": "ollama",
            "gen_ai.system": "ollama",
            "gen_ai.request.model": model,
            "gen_ai.request.max_tokens": max_tokens,
            "gen_ai.request.temperature": temperature,
            "llm.tools_offered": len(tools or []),
            "llm.structured_output": schema is not None,
            "input.value": clip(messages[-1].get("content", "") if messages else ""),
        }
        with span(f"chat {model}", kind=LLM, attributes=attributes) as current:
            result = await self._post(model, payload, timeout)
            current.set_attributes(
                {
                    "llm.token_count.prompt": result.prompt_tokens,
                    "llm.token_count.completion": result.completion_tokens,
                    "llm.token_count.total": result.prompt_tokens + result.completion_tokens,
                    "gen_ai.usage.input_tokens": result.prompt_tokens,
                    "gen_ai.usage.output_tokens": result.completion_tokens,
                    "output.value": clip(result.content or str([c.name for c in result.tool_calls])),
                    "llm.tool_calls": len(result.tool_calls),
                }
            )
            return result

    async def _post(self, model: str, payload: dict[str, Any], timeout: float) -> ChatResult:
        started = time.perf_counter()
        try:
            response = await self._client.post(f"{self.base_url}/api/chat", json=payload, timeout=timeout)
        except httpx.TimeoutException as exc:
            raise LLMError(f"{model} timed out after {timeout:.0f}s") from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"{model} request failed: {exc}") from exc
        if response.status_code == 404:
            raise LLMError(
                f"model '{model}' is not available in Ollama (run `ollama pull {model}`)", retriable=False
            )
        if response.status_code >= 400:
            raise LLMError(f"{model} returned HTTP {response.status_code}: {response.text[:200]}")
        data = response.json()
        message = data.get("message", {})
        calls = [
            ToolCall(call["function"]["name"], call["function"].get("arguments") or {})
            for call in message.get("tool_calls") or []
        ]
        return ChatResult(
            model=model,
            content=message.get("content", "") or "",
            tool_calls=calls,
            prompt_tokens=int(data.get("prompt_eval_count", 0)),
            completion_tokens=int(data.get("eval_count", 0)),
            latency_ms=(time.perf_counter() - started) * 1000,
        )

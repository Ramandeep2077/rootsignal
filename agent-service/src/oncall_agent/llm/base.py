"""Provider-neutral chat types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass
class ChatResult:
    model: str
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0


class LLMError(Exception):
    """A model call failed (timeout, HTTP error, invalid output). Retriable unless ``retriable`` is False."""

    def __init__(self, message: str, *, retriable: bool = True) -> None:
        super().__init__(message)
        self.retriable = retriable


class ChatModel(Protocol):
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
    ) -> ChatResult: ...

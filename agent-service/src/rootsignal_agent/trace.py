"""Step-by-step reasoning trace, stored with the incident and shown in the dashboard."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

MAX_DETAIL_CHARS = 1500


def _clip(value: Any) -> Any:
    if isinstance(value, str) and len(value) > MAX_DETAIL_CHARS:
        return value[:MAX_DETAIL_CHARS] + "…"
    if isinstance(value, dict):
        return {k: _clip(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clip(v) for v in value[:20]]
    return value


@dataclass
class Trace:
    steps: list[dict[str, Any]] = field(default_factory=list)
    started: float = field(default_factory=time.perf_counter)

    def add(self, agent: str, kind: str, title: str, /, **detail: Any) -> None:
        """``kind`` is one of: llm, tool, decision, guardrail, error."""
        self.steps.append(
            {
                "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
                "elapsed_ms": round((time.perf_counter() - self.started) * 1000),
                "agent": agent,
                "kind": kind,
                "title": title,
                "detail": _clip(detail),
            }
        )

"""Test doubles shared by the test suites and the eval harness: a scripted chat model, an in-memory alert service."""

from __future__ import annotations

import json
import uuid
from typing import Any

from rootsignal_agent.llm.base import ChatResult, LLMError, ToolCall


class ScriptedChat:
    """Returns queued responses in order. A response is a str (content), a list of ToolCall, or an exception."""

    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def chat(
        self,
        model,
        messages,
        *,
        tools=None,
        schema=None,
        temperature=0.1,
        max_tokens=400,
        num_ctx=8192,
        timeout=240.0,
    ) -> ChatResult:
        self.calls.append({"model": model, "messages": list(messages), "tools": tools, "schema": schema})
        if not self.responses:
            raise LLMError("script exhausted", retriable=False)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        if isinstance(response, list):
            return ChatResult(model, "", tool_calls=response, prompt_tokens=100, completion_tokens=10)
        if isinstance(response, dict):
            response = json.dumps(response)
        return ChatResult(model, response, prompt_tokens=120, completion_tokens=40, latency_ms=5.0)


def tool_call(name: str, **arguments: Any) -> ToolCall:
    return ToolCall(name, arguments)


class FakeAlertClient:
    def __init__(self) -> None:
        self.incidents: dict[str, dict[str, Any]] = {}
        self.calls: list[tuple[str, Any]] = []

    async def create_incident(self, title, severity, services, alert_ids):
        incident_id = str(uuid.uuid4())
        self.incidents[incident_id] = {
            "id": incident_id,
            "title": title,
            "severity": severity,
            "services": services,
            "alertIds": list(alert_ids),
            "status": "OPEN",
        }
        self.calls.append(("create", incident_id))
        return self.incidents[incident_id]

    async def attach_alerts(self, incident_id, alert_ids):
        self.incidents[incident_id]["alertIds"].extend(alert_ids)
        self.calls.append(("attach", alert_ids))
        return self.incidents[incident_id]

    async def set_status(self, incident_id, status):
        self.incidents[incident_id]["status"] = status
        return self.incidents[incident_id]

    async def record_analysis(self, incident_id, analysis):
        self.incidents[incident_id].update(analysis)
        self.calls.append(("analysis", analysis["status"]))
        return self.incidents[incident_id]

    async def mark_notified(self, incident_id):
        self.incidents[incident_id]["notified"] = True
        return self.incidents[incident_id]

    async def record_execution(self, incident_id, execution):
        self.incidents.setdefault(incident_id, {})["execution"] = execution
        return self.incidents[incident_id]

    async def get_incident(self, incident_id):
        return self.incidents.get(incident_id, {"rootCause": {"confidence": 0.9}})

    async def aclose(self):
        return None

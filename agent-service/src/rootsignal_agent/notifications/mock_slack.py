"""A stand-in for a Slack incoming webhook, so notifications work offline and at $0.

POST /webhook     accepts a Slack payload (returns "ok", like Slack)
GET  /messages    the received messages, newest last (for the demo and the eval harness)
DELETE /messages  clear
"""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse

app = FastAPI(title="mock slack webhook")
_messages: deque[dict[str, Any]] = deque(maxlen=500)


@app.post("/webhook", response_class=PlainTextResponse)
def webhook(payload: dict[str, Any]) -> str:
    _messages.append({"received_at": datetime.now(UTC).isoformat(), "payload": payload})
    return "ok"


@app.get("/messages")
def messages() -> list[dict[str, Any]]:
    return list(_messages)


@app.delete("/messages")
def clear() -> dict[str, int]:
    count = len(_messages)
    _messages.clear()
    return {"cleared": count}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8090, access_log=False)

"""FastAPI entry point: health/status endpoints around the long-running AgentService."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from rootsignal_agent.service import AgentService
from rootsignal_agent.settings import get_settings
from rootsignal_common.telemetry import setup_tracing

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
for noisy in ("httpx", "aiokafka", "mcp.client.streamable_http"):
    logging.getLogger(noisy).setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_tracing("agent-service")
    service = AgentService(get_settings())
    await service.start()
    app.state.service = service
    yield
    await service.stop()


app = FastAPI(title="rootsignal agent service", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/status")
def status() -> dict:
    return app.state.service.status()


def main() -> None:
    uvicorn.run("rootsignal_agent.app:app", host="0.0.0.0", port=8000, access_log=False)


if __name__ == "__main__":
    main()

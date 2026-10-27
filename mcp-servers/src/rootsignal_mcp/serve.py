"""Run the MCP servers.

rootsignal-mcp                 # all four over streamable HTTP on :8101-8104 (what docker compose runs)
rootsignal-mcp --stdio logs    # one server over stdio, e.g. for Claude Desktop / Claude Code
rootsignal-mcp --ingest        # (re)index runbooks and exit
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os

import uvicorn
from starlette.requests import Request
from starlette.responses import JSONResponse

from rootsignal_common.db import connection, ensure_schema
from rootsignal_common.embeddings import get_embedder
from rootsignal_common.telemetry import setup_tracing
from rootsignal_mcp.servers import SERVERS
from rootsignal_mcp.tools.runbooks import ingest_runbooks

log = logging.getLogger("rootsignal_mcp")


def prepare() -> None:
    with connection() as conn:
        ensure_schema(conn)
        chunks = ingest_runbooks(conn, get_embedder())
    log.info("runbook index ready: %d chunks", chunks)


async def serve_all(host: str) -> None:
    configs = []
    for name, (build, port) in SERVERS.items():
        server = build()

        @server.custom_route("/health", methods=["GET"])
        async def health(_: Request, name: str = name) -> JSONResponse:
            return JSONResponse({"status": "ok", "server": f"{name}-mcp"})

        # Containers are reached by service name, so DNS-rebinding protection must allow any Host header.
        app = server.streamable_http_app(stateless_http=True, json_response=True, host=host)
        configs.append(uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning")))
        log.info("%s-mcp listening on http://%s:%d/mcp", name, host, port)
    await asyncio.gather(*(server.serve() for server in configs))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    for noisy in ("mcp.server.streamable_http", "mcp.server.lowlevel.server", "httpx"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(description="rootsignal MCP servers")
    parser.add_argument("--stdio", choices=sorted(SERVERS), help="serve one server over stdio")
    parser.add_argument("--ingest", action="store_true", help="index runbooks and exit")
    parser.add_argument("--host", default=os.environ.get("MCP_HOST", "0.0.0.0"))
    args = parser.parse_args()

    setup_tracing("mcp-servers")
    if args.stdio:
        SERVERS[args.stdio][0]().run("stdio")
        return
    prepare()
    if args.ingest:
        return
    asyncio.run(serve_all(args.host))


if __name__ == "__main__":
    main()

from contextlib import contextmanager

import pytest

from rootsignal_common.db import connect
from rootsignal_common.embeddings import HashEmbedder
from rootsignal_mcp.servers import (
    build_deploys_server,
    build_logs_server,
    build_metrics_server,
    build_runbooks_server,
)
from rootsignal_mcp.tools.runbooks import ingest_runbooks


@pytest.fixture
def factory(pg_dsn):
    @contextmanager
    def make():
        with connect(pg_dsn) as conn:
            yield conn

    with connect(pg_dsn) as conn:
        ingest_runbooks(conn, HashEmbedder())
    return make


@pytest.fixture
def mcp_servers(factory):
    """The real MCP servers, in-process, backed by the test database."""
    return {
        "logs": build_logs_server(factory),
        "metrics": build_metrics_server(factory),
        "deploys": build_deploys_server(factory),
        "runbooks": build_runbooks_server(factory, embedder=HashEmbedder()),
    }

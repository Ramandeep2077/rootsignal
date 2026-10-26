"""The MCP layer: tool discovery, annotations and error reporting, through a real in-process MCP client."""

import json

import pytest
from mcp import Client

from oncall_common.embeddings import HashEmbedder
from oncall_mcp.servers import (
    build_deploys_server,
    build_logs_server,
    build_metrics_server,
    build_runbooks_server,
)
from oncall_mcp.tools.runbooks import ingest_runbooks
from oncall_sim.testing import load_scenario

EXPECTED_TOOLS = {
    build_logs_server: {"log_error_summary", "search_logs"},
    build_metrics_server: {"detect_metric_anomalies", "query_metric", "list_metrics"},
    build_deploys_server: {"list_recent_changes"},
    build_runbooks_server: {"search_runbooks", "get_runbook"},
}


@pytest.mark.parametrize("build", list(EXPECTED_TOOLS))
async def test_tools_are_listed_as_read_only(build):
    async with Client(build()) as client:
        tools = (await client.list_tools()).tools
    assert {t.name for t in tools} == EXPECTED_TOOLS[build]
    for tool in tools:
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
        assert tool.description


@pytest.mark.integration
async def test_tool_call_round_trip(pg_dsn, factory):
    load_scenario(pg_dsn, "tls_cert_expired")
    async with Client(build_logs_server(factory)) as client:
        result = await client.call_tool("search_logs", {"keyword": "x509", "since_minutes": 60, "limit": 3})
    assert not result.is_error
    payload = json.loads(result.content[0].text)
    assert payload["returned"] == 3
    assert all("x509" in line["message"] for line in payload["logs"])


@pytest.mark.integration
async def test_tool_errors_are_reported_to_the_model(factory):
    async with Client(build_metrics_server(factory)) as client:
        result = await client.call_tool("query_metric", {"service": "billing", "metric": "error_rate"})
    assert result.is_error
    assert "Known services" in result.content[0].text


@pytest.mark.integration
async def test_runbook_search_via_mcp(factory):
    with factory() as conn:
        ingest_runbooks(conn, HashEmbedder())
    async with Client(build_runbooks_server(factory, embedder=HashEmbedder())) as client:
        result = await client.call_tool("search_runbooks", {"query": "x509 certificate has expired", "k": 2})
    payload = json.loads(result.content[0].text)
    assert payload["results"][0]["runbook_id"] == "tls-certificate-expired"

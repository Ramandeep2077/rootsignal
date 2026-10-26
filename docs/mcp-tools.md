# MCP tools

Four read-only [Model Context Protocol](https://modelcontextprotocol.io) servers give the agents the same
views an on-call engineer uses: logs, metrics, change history and runbooks. They are built on the official
MCP Python SDK (v2, `MCPServer`) and served over **streamable HTTP** (stateless, JSON responses) on
ports 8101–8104, or over **stdio** for desktop MCP clients.

Every tool is annotated `readOnlyHint: true`, `destructiveHint: false`, and validates its inputs. Invalid
input returns an MCP error (`isError: true`) with a message the model can act on, for example
"Unknown service 'billing'. Known services: …". Time ranges accept either `since_minutes` (what LLMs prefer)
or absolute ISO-8601 `start`/`end`, capped at 7 days.

| Server | URL | Tool | Purpose |
|---|---|---|---|
| logs-mcp | `:8101/mcp` | `log_error_summary(service?, since_minutes=30)` | Top ERROR/WARN patterns (ids and numbers collapsed) with counts and first/last seen. The best first call. |
| | | `search_logs(service?, keyword?, level?, since_minutes=30, limit=20)` | Newest-first log lines filtered by service, case-insensitive keyword and level. |
| metrics-mcp | `:8102/mcp` | `detect_metric_anomalies(since_minutes=30, recent_minutes=10)` | Which service/metric pairs changed most recently versus the earlier window ("what changed, where?"). |
| | | `query_metric(service, metric, since_minutes=30)` | min/max/avg/first/last plus a downsampled series (≤12 points) to keep context small. |
| | | `list_metrics(service?)` | Metric names available. |
| deploys-mcp | `:8103/mcp` | `list_recent_changes(service?, kind?, since_minutes=120)` | Deploys, config changes and feature flags with author, description and diff. |
| runbooks-mcp | `:8104/mcp` | `search_runbooks(query, k=3)` | pgvector cosine search over runbook sections; returns runbook ids, the matching section and each runbook's allowlisted actions. |
| | | `get_runbook(runbook_id)` | Full markdown of a runbook. |

Each server also exposes `GET /health`.

Metrics available: `requests_per_sec`, `latency_p99_ms`, `error_rate`, `cpu_percent`, `cpu_throttled_percent`,
`memory_percent`, `disk_used_percent`, `http_429_rate`, `db_connections_in_use`, `db_connections_max`,
`kafka_consumer_lag`.

## Design notes

- **Aggregating tools first.** Small local models have limited context and get lost in raw logs. Tools like
  `log_error_summary` and `detect_metric_anomalies` return a compact answer in one call; the raw tools
  (`search_logs`, `query_metric`) are for confirming a hypothesis.
- **Runbook RAG.** `mcp-servers/runbooks/*.md` (13 runbooks with YAML front matter: `categories`, `services`,
  `actions`) are split into one chunk per `##` section, embedded locally with
  `sentence-transformers/all-MiniLM-L6-v2` (fastembed/ONNX, 384 dims) and stored in
  `knowledge.runbook_chunks` (pgvector). Indexing runs on server start and is skipped when the corpus hash
  and model haven't changed.
- **Actions come from runbooks, and runbooks can only name allowlisted actions.** A test fails if a runbook
  names an action outside `oncall_common.taxonomy.ActionType`.

## Using the tools from a desktop MCP client

Over stdio (e.g. Claude Desktop / Claude Code `mcpServers` config), with Postgres running (`make infra`):

```json
{
  "mcpServers": {
    "oncall-logs": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/oncall-copilot", "oncall-mcp", "--stdio", "logs"]
    }
  }
}
```

Or point any streamable-HTTP MCP client at `http://localhost:8101/mcp` after `make up`.

## Tests

`uv run pytest mcp-servers` covers time-window and service validation, each tool against real Postgres
loaded with simulator scenarios (for example, the disk-full scenario's top error pattern is
"No space left on device"), runbook metadata integrity (every scenario has its expected runbook; every
action is allowlisted), idempotent indexing, vector search ranking, and the MCP layer itself (tool listing,
read-only annotations, round-trip calls and error reporting through an in-process MCP client).

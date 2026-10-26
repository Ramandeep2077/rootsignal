# oncall-copilot

**An AI-native incident response copilot for SRE teams.** When production breaks, monitoring fires dozens of noisy,
duplicated alerts. oncall-copilot groups them into one incident, sends AI agents to investigate logs, metrics and recent
deploys, proposes a runbook-backed fix that **a human must approve**, and sends **one** clear summary instead of an
alert storm. An evaluation suite measures its accuracy, speed and cost on labelled incident scenarios.

Runs entirely locally at **$0**: open-weight models via Ollama, local embeddings, and LocalStack for the AWS deployment.

> Status: under active development. All metrics will come from `evals/EVALS.md` — **TBD** until the eval suite runs.

## Components

| Path | What | Stack |
|------|------|-------|
| `alert-service/` | Alert webhook, incidents API, approvals | Java 21, Spring Boot 4, JPA, PostgreSQL, Kafka |
| `agent-service/` | Triage → investigate → remediate agent graph | Python 3.12, FastAPI, LangGraph, Pydantic |
| `mcp-servers/` | Read-only tools: logs, metrics, deploys, runbooks | Python, MCP SDK, pgvector |
| `simulator/` | Fake microservices + labelled incident scenarios | Python |
| `dashboard/` | Incidents, reasoning trace, approve/reject, metrics | Next.js, TypeScript, Tailwind |
| `evals/` | Accuracy / noise reduction / latency / cost / guardrails | Python |
| `infra/` | Terraform (AWS via LocalStack), Postgres init | Terraform |

## Prerequisites

Docker Desktop, Java 21, Node 22, [uv](https://docs.astral.sh/uv/), GNU make, [Ollama](https://ollama.com).

## Quickstart

```bash
make models   # pull the local LLMs (one-off, ~6 GB)
make up       # build and start the whole stack
make test     # run all test suites
make down     # stop everything
```

More in [docs/decisions.md](docs/decisions.md).

## License

MIT

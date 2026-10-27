# Demo script (~5 minutes)

A walkthrough for a live demo or screen recording. On CPU an incident takes ~3-4 minutes to analyse, so fire the
live incident first and talk through the architecture while the agents work.

## Before you start

```bash
make demo SCENARIO=bad_deployment     # one finished incident to show in step 4, in case the live one is slow
```

Pick live scenarios the routed models got right in all 3 eval seeds: `bad_deployment`, `disk_full`,
`third_party_rate_limit`, `tls_cert_expired`, `upstream_outage`. For a quick run without the LLMs, use
`make demo-lite` (~20 s per incident).

Open four tabs: http://localhost:3000 (dashboard), http://localhost:8090/messages (mock Slack),
[README architecture diagram](../README.md#how-it-works), and [evals/EVALS.md](../evals/EVALS.md).

## 1. The problem (30 s)

> "When production breaks, on-call engineers get dozens of duplicated alerts from different tools across many
> services, and spend the first minutes just working out what's actually broken. RootSignal turns that alert
> storm into one incident with a root cause, evidence, and a proposed fix that a human has to approve."

## 2. Fire a live incident (30 s)

```bash
make sim SCENARIO=disk_full
```

> "This simulator models five microservices. It injects a fault, evaluates alert rules over the simulated metrics,
> and the failure propagates through the dependency graph, so we get a realistic storm: about 40 alerts from
> Prometheus, Datadog, Loki, synthetics and Kubernetes, plus background noise and red-herring deploys."

Show the dashboard: the alerts collapse into **one** incident in `INVESTIGATING`.

## 3. Architecture while it runs (90 s)

Use the diagram in the README.

> "A Java Spring Boot service ingests and fingerprints alerts, stores them in Postgres and publishes to Redpanda.
> The Python agent service groups them by fingerprint, embedding similarity and service topology. Then a LangGraph
> pipeline runs three agents: a small 1.5B model triages, a 7B model investigates through MCP tools for logs,
> metrics and deploys, and a remediation agent retrieves a runbook with pgvector and proposes one action."
>
> "Every proposal goes through guardrails: an action allowlist, runbook scope, a denylist for destructive commands
> and prompt injection, and a confidence floor. It can only ever end in `PENDING_APPROVAL`. Nothing runs
> automatically, and approved actions run as a dry run."
>
> "It all runs locally for $0: open-weight models in Ollama, local embeddings, and LocalStack to validate the
> Terraform for AWS."

## 4. The finished incident (90 s)

Open the incident (the live one if it's done, otherwise the `bad_deployment` one from setup).

- **Header tiles:** alerts grouped, time to summary, tokens, cost $0.00.
- **Root cause:** category, service, confidence, and evidence cited from deploys, logs and metrics.
- **Agent reasoning trace:** every LLM call and MCP tool call with timings and the model used. "This is fully
  inspectable, and the same spans are in Jaeger and Phoenix via OpenTelemetry."
- **Proposed action:** runbook-backed, with risk, steps, a rollback plan, and "Guardrails: passed".
- **Mock Slack tab:** one message for the whole storm instead of 40.

Approve it with your name. Show the status change and the dry-run execution in the trace.

## 5. How I know it works (60 s)

Open [evals/EVALS.md](../evals/EVALS.md).

> "I didn't want to just demo the happy path, so there's an evaluation harness: 12 labelled fault scenarios, several
> seeds, run end to end through the real stack, scored on root-cause accuracy, grouping, time to summary and
> cost, with an LLM judge for the free-text hypothesis. It compares the routed setup against a small-model-only
> setup and a rules-only baseline. There's also a guardrail suite with live prompt-injection attempts."

> "On the routed setup it gets the exact root cause 67% of the time and the originating service 83%, cuts 1,444
> alerts to 72 incidents, and blocks 100% of unsafe actions, including under live prompt injection. It's weakest on
> CPU throttling and Kafka consumer lag, where a 7B model confuses symptoms with causes. And I'm upfront that a
> keyword baseline scores 100% here, because it was written against the simulator's own logs; the LLM's value is
> the evidence, explanation and runbook-backed fix, and it would need a stronger model to beat rules on real data."

## Likely questions

- **Why not just one big model?** Separate agents keep each prompt small, which matters on CPU, and each step can
  fall back on its own (7B → 1.5B → rules). Model routing is one file, `agent-service/config/models.yaml`.
- **What if the model is wrong?** It can only recommend. A named human approves, guardrails run before approval and
  again before execution, and execution is dry-run only.
- **What would you do next?** A transactional outbox for alert publishing, OIDC/RBAC, real executors behind the same
  approval flow, and retrieval over past incidents.

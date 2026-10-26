# Design decisions

A running log of choices made while building oncall-copilot, with the reasoning behind each.
Newest phase last.

## Phase 0 — Project setup

| # | Decision | Why |
|---|----------|-----|
| D1 | **$0 operating cost**: local open-weight LLMs via **Ollama**, local embeddings, **LocalStack** instead of real AWS. | Portfolio project; anyone can clone and run it without an API key or cloud bill. |
| D2 | **Models sized for the dev laptop** (16 GB RAM, 12-core i5-13500H, integrated GPU only): `qwen2.5:1.5b` for triage, `qwen2.5:7b` for investigation/remediation/judging. | CPU-only inference. A 7B Q4 model (~4.7 GB) is the largest that leaves room for the Docker stack (~5 GB) in 16 GB. Qwen 2.5 has reliable native tool calling in Ollama, which the investigator needs. All names are configuration, not code (`.env` / `agent-service/config/models.yaml`). |
| D3 | **Ollama runs natively on the host**, not in Docker. | On Windows the Docker VM adds overhead and has no GPU passthrough for an Intel iGPU; native Ollama is faster and its memory is outside the Docker VM's 8 GB budget. Containers reach it via `host.docker.internal`. |
| D4 | **Mock mode** (`LLM_PROVIDER=mock`, `EMBEDDINGS_PROVIDER=hash`) for tests and CI. | Deterministic, fast, offline tests; CI never needs a model. |
| D5 | **Redpanda** instead of Apache Kafka. | Single container, no ZooKeeper/KRaft tuning, ~1 GB RAM. Kafka wire-compatible, so the Java and Python code use plain Kafka clients and could switch back by changing a bootstrap URL. |
| D6 | **Spring Boot 4.1.2** (Java 21) instead of the Spring Boot 3 named in the brief. | start.spring.io no longer offers 3.x and the 3.x line is past OSS support. 4.x keeps the same programming model (controllers, Spring Data JPA, Spring Kafka). |
| D7 | **uv workspace** for all Python components (one lockfile, one venv; each component is still its own package). | Reproducible installs, fast CI, and shared code (`common/`) without publishing packages. |
| D8 | Added a small `common/` Python package beyond the suggested layout. | Settings, DB access and embeddings are needed by the simulator, MCP servers, agents and evals; duplicating them would drift. |
| D9 | **Docker Compose profiles** (`app`, `observability`, `tools`, `aws`). | Keeps the default footprint small on a 16 GB laptop; heavy extras are opt-in. |
| D10 | **Testcontainers uses the same images as Compose** (pgvector Postgres 17, Redpanda). | Tests exercise real infrastructure with no "works in test, fails in prod" gap. |
| D11 | **GNU make** (installed via winget on Windows) with recipes that work in both `sh` and `cmd`. | One entry point (`make up`, `make test`, `make eval`) on every OS and in CI. |
| D12 | Every image and GitHub Action is **pinned to an exact version**. | Reproducible builds; upgrades are deliberate. |

## Phase 1 — Alert ingestion service

| # | Decision | Why |
|---|----------|-----|
| D13 | **Feature packages** (`alert`, `incident`, `metrics`) each layered controller → service → repository. | Keeps related code together; layering inside each feature keeps HTTP, business rules and persistence separate. |
| D14 | **Kafka publish after commit** (`@TransactionalEventListener(AFTER_COMMIT)`). | Consumers never see an alert that a rolled-back transaction discarded. Trade-off: if Kafka is down right after commit the event is lost; a transactional outbox is the production fix (noted as future work). |
| D15 | Events are **plain JSON strings** keyed by service. | Language-neutral for the Python consumer; per-service ordering within a partition. |
| D16 | **Incident state machine in the domain** (`IncidentStatus.allowedNext`). The only path into `APPROVED` is from `PENDING_APPROVAL` via a human call, and this is unit-tested for every status. | The core safety guarantee lives in one tested place, not scattered across controllers. |
| D17 | Agent output (root cause, evidence, proposed action, reasoning trace, usage) is stored as **JSONB**. | Agent schemas evolve faster than the relational core; the alert service displays them but doesn't interpret them, apart from requiring a proposed action for `PENDING_APPROVAL`. |
| D18 | **Separate internal API** (`/api/internal/**`), guarded by a shared token with constant-time comparison. | Agents can write analysis, but browser clients can't forge it. A shared token is enough for a local demo; mTLS or OAuth2 client credentials would be the production choice. Public approve/reject has no auth in the local demo; noted as future work. |
| D19 | **Time to summary is measured from when the alert service first received an alert** (`received_at`), not the sender's timestamp. | Immune to clock skew between monitoring tools. |
| D20 | **Fingerprints** normalise ids, hex and numbers before hashing. | Cheap exact-duplicate detection before any AI is involved; triage uses it as a first-pass grouping signal. |
| D21 | Errors are **RFC 9457 `ProblemDetail`** responses, with field-level `errors` for validation. | One predictable error shape for every client. |
| D22 | Integration tests (`*IT`) run in `mvn verify` via Failsafe, against Testcontainers Postgres and Redpanda. | Fast `mvn test` loop locally; full-stack confidence in CI. |

## Phase 2 — Simulator

| # | Decision | Why |
|---|----------|-----|
| D23 | The "fake microservices" are a **discrete-time simulation** (30 s ticks, 30 min window), not five running HTTP servers. | Deterministic (seeded), fast (a whole scenario simulates in milliseconds), easy to test, and light enough for a 16 GB laptop. The agents only see telemetry and alerts, which look the same either way. |
| D24 | **Alerts emerge from rules over simulated metrics** (Prometheus-style `for:` + repeat interval, several sources), and failures **propagate through the dependency graph**. | Duplicates and cross-service symptom alerts come from the simulation instead of being hand-written, so noise reduction is measured on realistic storms. |
| D25 | **Red herrings and near-miss pairs**: unrelated routine changes, one background alert per run, and confusable pairs (deploy vs config change, outage vs 429, slow dependency vs pool exhaustion). | Without these, root-cause accuracy would be inflated by trivially separable scenarios. |
| D26 | **Ground truth never reaches the agents.** Alerts carry only an opaque `sim_run` id; tests assert scenario names never appear in alerts. | The eval would be meaningless if the answer leaked. |
| D27 | **Telemetry is replaced per run**, and tools query by time range like real backends. | Sequential runs have overlapping 30-minute windows; isolation by truncation keeps runs independent without leaking a run id into tool queries. |
| D28 | Alert timestamps are the simulated (backdated) time; the storm is replayed over ~12 s of wall-clock time. | Realistic alert timestamps for the agents, while keeping eval runs fast. |
| D29 | The eval harness reads the alert service's tables directly (read-only) to map `sim_run` → incident. | The public API intentionally doesn't expose label search; the harness is test infrastructure, not a client. |

## Phase 3 — MCP servers

| # | Decision | Why |
|---|----------|-----|
| D30 | **MCP Python SDK v2** (`MCPServer`, `mcp.Client`), pinned to `>=2.3,<3`. | Current major version; v2 renamed `FastMCP` and changed the client API, so the pin prevents accidental drift. |
| D31 | **Four separate servers in one process** (ports 8101–8104), streamable HTTP in stateless JSON mode. | Mirrors how teams split tool ownership (logs vs metrics vs change tracking vs knowledge) while costing one container. Stateless mode means no session affinity and easy horizontal scaling. |
| D32 | **Aggregating tools** (`log_error_summary`, `detect_metric_anomalies`) alongside raw ones. | Small local models do much better with one compact, pre-aggregated answer than with pages of raw logs; fewer tool calls also means lower latency on CPU inference. |
| D33 | Tool logic is plain functions over a DB connection; the MCP layer is thin. | Logic is testable without MCP plumbing, and the MCP layer is still tested end to end with an in-process client. |
| D34 | Tools raise `ToolError` for bad input; unexpected exceptions are masked by the SDK. | The model gets actionable messages ("Known services: …"), but internals never leak. |
| D35 | **fastembed (ONNX) for `all-MiniLM-L6-v2`** rather than `sentence-transformers` + PyTorch. | Same sentence-transformers model and vectors, about 2 GB smaller images, faster CPU startup. |
| D36 | Runbooks are **markdown with front matter**, chunked per section, re-indexed only when the corpus hash changes. | Humans can edit runbooks in git; section-level chunks give precise retrieval; startup stays fast. |
| D37 | DB tests use a dedicated `oncall_test` database created on demand; CI runs a pgvector service. | Tests never clobber dev data, and integration tests run in CI rather than being skipped. |

## Phase 4 — Agent workflow

| # | Decision | Why |
|---|----------|-----|
| D38 | **Ollama runs on the Intel Iris Xe iGPU via Vulkan** (`OLLAMA_IGPU_ENABLE=1`, set as a user env var). | Measured on this laptop with a 3.9k-token prompt to qwen2.5:7b: prompt processing 17 → 64 tok/s, generation 2.8 → 5.1 tok/s (240 s → 100 s). |
| D39 | **LangGraph state machine** `triage → investigate → (remediate → guardrails) → persist → notify`, with typed runtime context (`Runtime[RunContext]`) for dependencies. | Explicit, inspectable control flow with a conditional failure edge; dependency injection keeps nodes pure and testable. The graph can only reach `PENDING_APPROVAL`; it never executes anything. |
| D40 | **Direct Ollama `/api/chat` client** rather than a framework model wrapper. | Exact token counts (`prompt_eval_count`/`eval_count`), native tool calling, and JSON-schema constrained decoding (`format`) for structured outputs, without version coupling to wrapper libraries. |
| D41 | **Investigator = deterministic evidence pack + bounded agentic follow-up + schema-constrained verdict.** | Small local models do better when the first three SRE questions (errors, metric changes, recent changes) are already answered; up to 3 model-chosen tool calls then confirm or refute. The free-text turn is capped at 160 tokens because generation runs at ~5 tok/s. |
| D42 | **Compact text tool results** instead of pretty JSON. | Each prompt token costs ~15 ms here; dense lines carry the same facts with 3–5x fewer tokens. |
| D43 | **Model routing in one file** (`agent-service/config/models.yaml`): profiles `routed` (1.5B triage, 7B RCA/remediation), `small_only`, `large_only`, `heuristic`; per-agent env overrides. | One place to change models; the eval suite compares profiles without code changes. |
| D44 | **Resilience:** per-model timeout, retries with exponential backoff and jitter, fallback chain (7B → 1.5B → rules); non-retriable errors (e.g. missing model) skip retries; one repair attempt for invalid JSON. | An incident always gets an analysis, even with Ollama down. |
| D45 | **Rules ("heuristic") implementation for every agent.** | Last-resort fallback, deterministic mock for CI, and a no-LLM baseline for evals. It was written knowing the simulator's log vocabulary, so its accuracy is reported as an optimistic keyword baseline, not a fair competitor. |
| D46 | **Remediation `action` is a free string, validated afterwards by guardrails** (allowlist, runbook scope, known target, destructive-pattern denylist including prompt-injection phrases, confidence floor, forced dry run). Any violation → `escalate_to_human` + `NEEDS_HUMAN`. | Constraining the action at decode time would hide unsafe intents instead of catching them; validating afterwards lets the eval measure the block rate. |
| D47 | **Guardrails run twice**: at proposal time and again at (dry-run) execution after approval. | Defence in depth against a tampered stored proposal or a tightened policy. There is no live executor. |
| D48 | **Runbook retrieval = vector search (top 5) + metadata filter on category**, with category tags embedded in chunks and the query expanded with the category description. | Pure similarity occasionally ranked the wrong runbook first; "retrieve, then filter by metadata" is robust and still uses pgvector. |
| D49 | **Grouping = fingerprint OR embedding similarity ≥ 0.55 OR topology adjacency (MEDIUM+ only)**; groups close after 6 s quiet or 20 s total; late alerts attach to the incident for 10 min. | Duplicates, re-worded duplicates from other tools, and cascading symptoms all merge; low-severity background alerts don't get absorbed by adjacency alone (a test checks this on all 12 scenarios). Limitation: two simultaneous independent failures in adjacent services would merge. |
| D50 | Low/INFO-only groups skip LLM investigation and go straight to `NEEDS_HUMAN`. | Saves several minutes of CPU inference per informational alert. |
| D51 | One investigation at a time (`MAX_CONCURRENT_INVESTIGATIONS=1`). | A single CPU/iGPU serialises inference anyway; parallel requests would just thrash. |

## Phase 5 — Notifications

| # | Decision | Why |
|---|----------|-----|
| D52 | **One notification per incident**, sent by the graph's final node after the analysis is persisted; late-attached alerts never re-notify. | The point of the system is replacing an alert storm with one actionable message. |
| D53 | **Informational-only incidents aren't announced.** | They stay visible on the dashboard; paging people for them is noise. |
| D54 | **Slack Block Kit via incoming webhook, then SMTP email as fallback** (`FallbackNotifier`: first channel to succeed wins). | Slack is where on-call lives; email covers a Slack outage. Delivery failure never fails the incident pipeline; it's logged and the incident is simply not marked notified. |
| D55 | **Bundled mock Slack webhook** (`mock-slack`, `GET :8090/messages`) and **Mailpit** (`:8025`) in Compose. | Notifications work offline at $0; set `SLACK_WEBHOOK_URL` to a real webhook to use real Slack. |
| D56 | The message carries title, severity, services, alert count, root-cause hypothesis and confidence, proposed action with risk, a link to the dashboard (approve/reject happens there, not in Slack) and token/cost usage. | Approving from a chat button would bypass the authenticated review UI; the link keeps the human decision in one audited place. |

## Phase 6 — Dashboard

| # | Decision | Why |
|---|----------|-----|
| D57 | **Next.js 16 (App Router, Cache Components) as a static shell + client-side polling** of the alert service every 3–5 s. | Incident state changes every few seconds and approve/reject are client mutations, so there's nothing useful to prerender with data. The shell prerenders (static/PPR), data streams in live, and the build doesn't need the backend. |
| D58 | Under Cache Components, URL-reading pieces (`usePathname` for the active nav link; `params` on the detail page) are wrapped in `<Suspense>`. | Required by Next 16: URL data is runtime data. Only the nav highlight and the detail body are dynamic; the rest of the layout stays static. |
| D59 | **Design tokens from the dataviz reference palette**, with light *and* dark selected (not auto-inverted), a system/light/dark toggle applied by an inline pre-paint script. | No theme flash on load, consistent ink/surface roles, and chart colours validated for both modes. |
| D60 | **Status and severity are always colour + text label**; status colours are reserved for state. | Accessibility: never colour alone. |
| D61 | Metrics: one hero figure (noise reduction), stat tiles, and two single-series bar charts with direct value labels, hover tooltips and a table view. No legends (single series), no dual axes. | Follows the dataviz method: the headline number is a tile, not a chart; every chart has a table alternative. |
| D62 | **Approve/Reject require a name**; buttons only render in `PENDING_APPROVAL`, and the panel states that approval triggers a dry run only. | Attributable decisions; the UI mirrors the backend state machine instead of trusting the client. |
| D63 | Vitest + Testing Library for units (formatting, duplicate collapsing, badge labels, approval flow); Playwright for screenshots. | Fast unit tests in CI; real-browser rendering for visual checks and README images. |

## Phase 7 — Observability

| # | Decision | Why |
|---|----------|-----|
| D64 | **Jaeger for distributed traces + Arize Phoenix for LLM traces**, instead of Langfuse. | Both are single containers that take plain OTLP. Self-hosted Langfuse v3 needs ClickHouse, Redis and object storage, too heavy next to a 7B model on 16 GB. Phoenix gives the LLM-specific view (token counts, prompt/response, span hierarchy) from the same spans. |
| D65 | **One incident trace linked (not parented) to N alert traces.** | Correct OTel modelling of fan-in batch processing; each alert's own trace still runs end to end from Java through Kafka to Python. |
| D66 | **OpenInference + GenAI semantic-convention attributes** on LLM/tool spans. | Vendor-neutral: Phoenix, Jaeger's GenAI view and other OTel backends all read them. |
| D67 | **Reuse the MCP SDK's OTel middleware** and propagate context via MCP `_meta`. | MCP's own convention; no custom wire format. |
| D68 | Tracing export is **opt-in** (`make up-obs`); spans are still created so context propagates. | No exporter-error noise or overhead in the default stack; one switch turns on full traces. |
| D69 | Root sampler drops health checks. | FastAPI now emits its own spans; container healthchecks every 10 s otherwise bury the interesting traces. |

## Phase 8 — Evaluation suite

| # | Decision | Why |
|---|----------|-----|
| D70 | **The harness exercises the real path** (simulator → Java alert service over HTTP → Kafka → agent service → MCP/Ollama → write-back → notification), running the agent service in-process so the model profile can be switched per run. | Measures the system that ships, including grouping latency and Kafka, not a unit-level shortcut. |
| D71 | Scores per run: exact category match, LLM-as-judge (1–5, local 7B, temperature 0), service, action, runbook, grouping recall/precision, noise absorbed, time to summary/notification, tokens, cost, and "unsafe proposal pending approval". Results are written as JSONL per run, and the report is generated from them. | Every number in EVALS.md is reproducible from committed raw records; interrupted evals resume. |
| D72 | Guardrail eval = static adversarial suite + safe controls (false positives) + execution-time tampering + **live prompt injection** against the real remediation model. | "Blocked 100%" is only meaningful if the model is actually tempted; the live test measures how often it falls for injections and checks that none get through. Writing the injections also found two denylist gaps (`replicas to 0`, `purge the topic`), now fixed and tested. |

## Phase 9 — Deployment and CI

| # | Decision | Why |
|---|----------|-----|
| D73 | AWS: ECS Fargate Spot, public subnets without NAT, Redpanda container, single-AZ `db.t4g.micro` RDS, one ALB, dashboard on Fargate (not S3/CloudFront). | Lowest-cost shape that still runs the whole system. The dashboard's dynamic incident route needs a server (or a URL scheme change) for a static export; one ALB serves both API and UI on the same origin. |
| D74 | **One Terraform codebase, two targets** (`target = aws|localstack`) with per-module feature flags. | LocalStack's free tier lacks ECS/RDS/ECR/ELBv2: the full stack is *planned* there and the free subset *applied*, so CI checks the infrastructure without an AWS account or bill. |
| D75 | **LocalStack pinned to 4.14.** | Releases since 2026.03 require an account auth token; the pinned version keeps the $0, no-signup setup (and CI) working. Upgrading means adding `LOCALSTACK_AUTH_TOKEN`. |
| D76 | Generated secrets in Secrets Manager, injected as ECS task secrets; execution role may read only those two secrets. | No credentials in images, env files or Terraform outputs; least privilege. |
| D77 | Cost guardrails: Budget alerts, 7-day logs, Container Insights off, and a teardown script that verifies nothing tagged is left. | "Don't pay for idle resources" is enforced by tooling, not memory. |
| D78 | CI: Java verify (Testcontainers), Python lint + tests (pgvector service), dashboard lint/test/build, compose config, Docker image builds (cached, not pushed), Terraform fmt/validate + plan/apply against LocalStack on PRs. | Every artefact that ships is built and checked on every change. |

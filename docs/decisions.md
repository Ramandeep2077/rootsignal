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

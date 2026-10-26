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

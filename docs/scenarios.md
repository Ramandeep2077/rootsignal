# Incident scenarios

Generated from `simulator/src/rootsignal_sim/scenarios.py` (seed 1). Each scenario injects one fault into a
30-minute, 30-second-tick simulation of five services (`api-gateway → auth, checkout`; `checkout → inventory,
payments`). Alert rules (Prometheus, Datadog-style monitor, Loki log alerts, synthetics, Kubernetes events)
fire and re-fire on the resulting metrics, so each scenario produces a noisy, duplicated, multi-service storm
plus one unrelated background alert. Three routine changes are added as red herrings.

| Scenario | What happens | Ground-truth root cause service | Alerts (seed 1) | Services alerting | Expected runbook | Expected actions |
|---|---|---|---|---|---|---|
| `bad_deployment` | Payments v4.2.0 deploy throws NullPointerException | `payments` | 42 | 3 | `bad-deployment-rollback` | `rollback_deployment` |
| `config_error` | Gateway routes checkout traffic to a non-existent cluster | `api-gateway` | 26 | 3 | `bad-config-change` | `revert_config_change` |
| `cpu_throttling` | Auth CPU throttled at its limit | `auth` | 22 | 2 | `cpu-throttling` | `increase_cpu_limit`, `scale_out` |
| `db_pool_exhaustion` | Checkout DB connection pool exhausted during a traffic surge | `checkout` | 51 | 3 | `db-connection-pool-exhaustion` | `increase_connection_pool`, `scale_out` |
| `disk_full` | Payments log volume full | `payments` | 49 | 3 | `disk-full` | `free_disk_space` |
| `dns_failure` | Cluster DNS lookups timing out | `coredns` | 61 | 3 | `dns-resolution-failure` | `restart_dns` |
| `kafka_consumer_lag` | Inventory order consumer falling behind | `inventory` | 25 | 4 | `kafka-consumer-lag` | `scale_consumers`, `restart_service` |
| `memory_leak` | Inventory heap grows until OOMKilled | `inventory` | 28 | 4 | `memory-leak-oom` | `restart_service`, `increase_memory_limit` |
| `slow_dependency` | Inventory slow queries cause checkout timeouts | `inventory` | 51 | 3 | `slow-dependency-latency` | `enable_circuit_breaker`, `scale_out` |
| `third_party_rate_limit` | Fraud-scoring API rate limiting payments | `fraudscore-api` | 44 | 3 | `third-party-rate-limit` | `reduce_request_rate`, `enable_circuit_breaker` |
| `tls_cert_expired` | auth.internal TLS certificate expired | `auth` | 27 | 3 | `tls-certificate-expired` | `renew_certificate` |
| `upstream_outage` | Payment provider outage | `payment-provider` | 60 | 3 | `upstream-provider-outage` | `failover_provider`, `enable_circuit_breaker` |

The agents never see the scenario name or ground truth. Alerts carry only an opaque `sim_run` label, which the
evaluation harness uses to map incidents back to runs. Every scenario's `evidence_keywords` are asserted (by
tests) to be discoverable in the telemetry, so every scenario can be solved from the tools alone.

```bash
uv run python simulator/run.py --list
uv run python simulator/run.py --scenario db_pool_exhaustion            # write telemetry + post alerts
uv run python simulator/run.py --scenario db_pool_exhaustion --dry-run  # simulate only
uv run python simulator/run.py --all                                    # sequential, waits for analysis
```

---
id: slow-dependency-latency
title: Latency spike from a slow dependency
categories: [slow_dependency]
services: [checkout, inventory, payments, api-gateway]
actions: [enable_circuit_breaker, scale_out]
---
# Latency spike from a slow dependency

## Symptoms
- A caller (e.g. checkout) logs `timeout calling <dependency> after 2000ms` and its error rate rises.
- The dependency is **up and answering** — its own error rate is low — but its p99 latency is high.
- Dependency logs show slow work, e.g. `slow query 2734ms ... (Seq Scan ...)`.
- Unlike an outage there are no connection refusals, and unlike pool exhaustion the caller's own DB pool
  is not saturated.

## Diagnosis
1. Compare `latency_p99_ms` of the caller and each of its dependencies; the earliest one to degrade is the
   likely source.
2. Search the dependency's logs for slow queries, lock waits or index problems (`INVALID` index,
   failed `REINDEX`).
3. Check recent changes on the dependency (deploys, migrations, feature flags).

## Remediation
- **enable_circuit_breaker** on the caller for the slow dependency so requests fail fast and degrade
  gracefully (e.g. show cached stock). Low risk.
- **scale_out** the dependency if the slowness is load-driven.
- Fix the underlying cause (rebuild the invalid index, kill the blocking query).

## Rollback
Disable the circuit breaker override once dependency latency is back under SLO.

## Escalation
Page the dependency's owning team (and the database on-call for query plan regressions).

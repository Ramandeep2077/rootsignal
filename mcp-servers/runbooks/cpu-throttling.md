---
id: cpu-throttling
title: CPU throttling at the container limit
categories: [cpu_throttling]
services: [auth, checkout, payments, inventory, api-gateway]
actions: [increase_cpu_limit, scale_out]
---
# CPU throttling at the container limit

## Symptoms
- `CPUThrottlingHigh`: a large share of CFS periods throttled; `cpu_percent` pinned near 100% of the limit.
- Latency rises sharply while errors stay low; logs show queueing (`request queue depth 412 exceeds 256`)
  and CPU-bound work slowing down (`bcrypt verify took 800ms`).
- Callers see slow responses rather than failures.

## Diagnosis
1. Query `cpu_percent` and `cpu_throttled_percent` for the service. Throttling above 25% sustained is
   significant.
2. Check traffic (`requests_per_sec`): organic growth versus a sudden spike.
3. Check the configured CPU limit (startup logs, e.g. `cpu limit 500m`) and any recent change to it.

## Remediation
- **increase_cpu_limit** (e.g. 500m → 1000m) if nodes have capacity. Low risk.
- **scale_out** to more replicas to spread CPU-bound work. Low risk with an HPA in place.

## Rollback
Restore the previous CPU limit or replica count.

## Escalation
Capacity planning review if traffic growth is sustained.

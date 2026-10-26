---
id: memory-leak-oom
title: Memory leak and OOMKilled containers
categories: [memory_leak]
services: [inventory, checkout, payments, auth, api-gateway]
actions: [restart_service, increase_memory_limit]
---
# Memory leak and OOMKilled containers

## Symptoms
- `ContainerMemoryHigh` alerts with memory climbing steadily (a straight line, not a step) toward the limit.
- Long GC pauses in logs (`GC pause 1.4s ... old gen not reclaimed`) followed by
  `java.lang.OutOfMemoryError: Java heap space`.
- Kubernetes events: `container <name> OOMKilled (exit code 137)`, restart count increasing.
- Latency rises as GC thrashes; callers time out.

## Diagnosis
1. Plot `memory_percent` for the service over the last 30–60 minutes. A linear climb unrelated to traffic
   indicates a leak; a step right after a deploy points to *bad-deployment-rollback* instead.
2. Check the deploy history: leaks usually ship days earlier and only surface under sustained load.
3. Capture a heap dump from one replica before restarting (`jcmd <pid> GC.heap_dump`).
4. Look for unbounded caches or collections in the stack traces (e.g. `StockCache.put`).

## Remediation
- **restart_service**: rolling restart to reclaim memory and buy time. Low risk, but the leak returns.
- **increase_memory_limit**: temporarily raise the container memory limit to extend time between restarts.
  Medium risk: node capacity must allow it.
- Long term: fix the leak (bounded cache with eviction) and redeploy.

## Rollback
Revert the memory limit to its previous value. Restarts need no rollback.

## Escalation
Escalate to the owning team with the heap dump if restarts are needed more than once per hour.

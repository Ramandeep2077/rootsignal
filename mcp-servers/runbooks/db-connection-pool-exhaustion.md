---
id: db-connection-pool-exhaustion
title: Database connection pool exhaustion
categories: [db_pool_exhaustion]
services: [checkout, inventory]
actions: [increase_connection_pool, scale_out]
---
# Database connection pool exhaustion

## Symptoms
- `DBConnectionPoolSaturated` alerts: active connections at or near the pool maximum (e.g. 50/50).
- Application logs: `HikariPool-1 - Connection is not available, request timed out after 3000ms` with
  `active=<max>, idle=0, waiting=<n>`.
- p99 latency close to the pool acquisition timeout (≈3 s) and a jump in 5xx; callers (api-gateway) see
  upstream 503s.
- Often triggered by a traffic surge (campaign, retry storm) or by slow queries holding connections.

## Diagnosis
1. Query `db_connections_in_use` vs `db_connections_max` for the service over the last 30 minutes.
2. Check `requests_per_sec`: a surge with flat query latency means the pool is simply too small.
3. Check the database itself (CPU, slow query log). If queries got slower, see *slow-dependency-latency*.
4. Look for recent deploys or config changes that lowered `db.pool.max` or added long transactions.

## Remediation
- **increase_connection_pool**: raise `db.pool.max` (e.g. 50 → 100) if the database has headroom
  (`max_connections` minus other clients). Low risk; takes effect on rolling restart.
- **scale_out**: add replicas to spread load, *only* if the database can accept the extra connections
  (replicas × pool size).
- Shed non-critical traffic at the gateway if neither is possible.

## Rollback
Restore the previous `db.pool.max` value / replica count from the config history and roll the pods.

## Escalation
Page the database on-call if the database is above 80% CPU or near `max_connections`.

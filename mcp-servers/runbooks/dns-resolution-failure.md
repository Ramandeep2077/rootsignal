---
id: dns-resolution-failure
title: DNS resolution failures
categories: [dns_failure]
services: [api-gateway, checkout, payments, coredns]
actions: [restart_dns]
---
# DNS resolution failures

## Symptoms
- Errors appear in **several services at the same time**, all failing to resolve names:
  `dial tcp: lookup <host> on 10.96.0.10:53: ... i/o timeout` or `server misbehaving (SERVFAIL)`.
- Both internal (`*.svc.cluster.local`) and external hostnames fail.
- No single service has a deploy, resource problem or config change that explains it.

## Diagnosis
1. Search logs across services for `lookup` and `10.96.0.10:53` (the cluster DNS service IP).
2. Check CoreDNS pods: restarts, CPU throttling, `SERVFAIL` counts, upstream resolver reachability.
3. Rule out a NetworkPolicy change blocking UDP/TCP 53.

## Remediation
- **restart_dns**: rolling restart of the CoreDNS deployment (and scale it out if it is CPU-throttled).
  Low risk: clients retry lookups.
- Temporarily raise client-side DNS cache TTLs if restarts don't help.

## Rollback
No rollback for a restart; revert any NetworkPolicy or CoreDNS ConfigMap change that preceded the incident.

## Escalation
Platform/network on-call immediately: DNS failures affect every service.

---
id: upstream-provider-outage
title: Upstream or third-party provider outage
categories: [upstream_outage]
services: [payments]
actions: [failover_provider, enable_circuit_breaker]
---
# Upstream or third-party provider outage

## Symptoms
- Calls to an external provider fail with `503 Service Unavailable`, `connection reset by peer` or
  connection refused (e.g. `api.payprovider.example`).
- The calling service (payments) shows high error rate and retry-inflated latency; its CPU, memory and
  deploys are normal.
- Distinguish from rate limiting: an outage returns **5xx / connection errors**, rate limiting returns
  **429 with Retry-After** (see *third-party-rate-limit*).

## Diagnosis
1. Search the caller's logs for the provider hostname and the HTTP status / socket errors.
2. Check the provider's public status page and recent incident announcements.
3. Confirm no recent deploy or config change on the caller changed the provider URL or credentials.

## Remediation
- **failover_provider**: switch traffic to the secondary provider if one is configured. Medium risk:
  verify the secondary's capacity and fees.
- **enable_circuit_breaker** for the provider so requests fail fast, and queue charges for retry.

## Rollback
Switch back to the primary provider once its status is green and error rates are normal for 15 minutes.

## Escalation
Open a ticket with the provider; inform customer support about delayed payments.

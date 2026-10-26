---
id: general-incident-triage
title: General incident triage
categories: [unknown]
services: [api-gateway, auth, checkout, inventory, payments]
actions: [escalate_to_human]
---
# General incident triage

## Symptoms
Use this runbook when the alerts don't clearly match a specific runbook, or the evidence is contradictory.

## Diagnosis
1. **Find the origin.** Symptoms propagate from callees to callers (`api-gateway → checkout → payments`).
   The deepest degraded service is usually closest to the cause.
2. **Check what changed.** List deploys, config changes and feature flags in the hour before the first alert.
   Correlate change timestamps with the first error.
3. **Check resources.** CPU and throttling, memory, disk, connection pools and consumer lag of the origin.
4. **Read the errors.** Search the origin's logs for the most frequent ERROR message in the incident window.
5. **Rule out shared infrastructure.** Failures in many services at once suggest DNS, network or a shared
   dependency.

## Remediation
- **escalate_to_human**: page the owning team with the evidence gathered so far. No automated action is
  safe without a confident diagnosis.

## Rollback
Not applicable.

## Escalation
Incident commander for any customer-facing SEV1/SEV2.

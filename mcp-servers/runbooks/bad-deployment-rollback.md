---
id: bad-deployment-rollback
title: Bad deployment — roll back
categories: [bad_deployment]
services: [payments, checkout, inventory, auth, api-gateway]
actions: [rollback_deployment]
---
# Bad deployment — roll back

## Symptoms
- Error rate jumps sharply at a specific moment that **coincides with a deployment** of the service.
- New exception types in logs that did not exist before, often tagged with the new version
  (e.g. `NullPointerException ... [version=4.2.0]`).
- CPU, memory and traffic are normal: the problem is the code, not capacity.

## Diagnosis
1. List recent deployments for the affected service and compare the deploy timestamp with the first error.
   A gap of more than a few minutes makes a bad deploy less likely.
2. Search logs for exceptions with the new version tag and confirm they are absent before the deploy.
3. Distinguish from a **configuration** change (kind `config_change`): that is *bad-config-change*.
4. Check whether only the new version's pods are failing (canary vs full rollout).

## Remediation
- **rollback_deployment** to the previous known-good version (e.g. 4.2.0 → 4.1.3). Low risk when the
  release has no irreversible schema migration; check the release notes first.
- Freeze further deploys of the service until the fix is reviewed.

## Rollback
Re-deploy the rolled-back version once fixed. If the rollback itself fails, scale the old ReplicaSet up
manually.

## Escalation
Notify the author of the change and the owning team; open a post-incident review.

---
id: bad-config-change
title: Faulty configuration change
categories: [config_error]
services: [api-gateway, checkout, payments, inventory, auth]
actions: [revert_config_change]
---
# Faulty configuration change

## Symptoms
- Errors start right after a **configuration change** (kind `config_change` or `feature_flag`), with no
  code deployment.
- Gateway-style errors such as `no healthy upstream for cluster '<name>'`, wrong hostnames or ports, or
  missing credentials.
- The service that *should* receive the traffic is healthy, but its request rate drops (traffic sent
  elsewhere).

## Diagnosis
1. List recent changes for the failing service and look for config changes whose timestamp matches the
   first error.
2. Read the change diff (e.g. `routes.yaml: cluster: checkout → checkout-v2`) and check that the target
   exists and is healthy.
3. Distinguish from a code deploy (*bad-deployment-rollback*): there is no new version and no new
   exception types.

## Remediation
- **revert_config_change** to the last known-good revision. Low risk, applies in seconds through hot reload.
- Add validation to the config pipeline (e.g. reject routes to clusters with zero healthy hosts).

## Rollback
Re-apply the change once the target cluster is deployed and healthy.

## Escalation
Notify the author of the change; review the config change process in the post-incident review.

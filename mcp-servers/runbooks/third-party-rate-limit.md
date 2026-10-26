---
id: third-party-rate-limit
title: Third-party API rate limiting
categories: [third_party_rate_limit]
services: [payments]
actions: [reduce_request_rate, enable_circuit_breaker]
---
# Third-party API rate limiting

## Symptoms
- Outbound calls to a vendor API return `429 Too Many Requests`, usually with a `Retry-After` header
  (e.g. `api.fraudscore.example`).
- `UpstreamRateLimited` alerts on the calling service; error rate rises as retries are exhausted.
- **Immediate retries make it worse** (retry storm): request volume to the vendor goes up while success
  goes down.

## Diagnosis
1. Search the caller's logs for `429` and `Retry-After`; note which vendor host and endpoint.
2. Compare our outbound request rate with the vendor's published quota.
3. Check for traffic spikes or retry-policy changes (backoff set to 0) in recent changes.

## Remediation
- **reduce_request_rate**: enable client-side rate limiting and honour `Retry-After` with exponential
  backoff and jitter. Low risk.
- **enable_circuit_breaker** for the vendor so the service degrades gracefully (e.g. queue fraud checks or
  apply a fallback rule for low-value charges). Medium risk: check with the business owner.
- Request a temporary quota increase from the vendor.

## Rollback
Remove the temporary rate limit once traffic is back within quota.

## Escalation
Vendor account manager for quota; payments product owner for fallback risk decisions.

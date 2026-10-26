---
id: tls-certificate-expired
title: Expired TLS certificate
categories: [tls_cert_expired]
services: [auth, api-gateway, payments]
actions: [renew_certificate]
---
# Expired TLS certificate

## Symptoms
- Clients log `x509: certificate has expired or is not yet valid: current time ... is after ...`.
- The server side logs `TLS handshake error ... remote error: tls: bad certificate`.
- The affected server looks *idle* (traffic drop) rather than failing, because requests never complete the
  handshake. Callers' error rates spike all at once at the expiry time.

## Diagnosis
1. Search caller logs for `x509` / `certificate has expired` and note the `is after <timestamp>` value; that is
   the certificate's `notAfter`.
2. Check the server's logs for certificate warnings (`not valid after`) and the renewal job's last success.
3. Confirm with `openssl s_client -connect <host>:443 -servername <host>` if you have shell access.

## Remediation
- **renew_certificate**: issue and deploy a new certificate (cert-manager: delete the expired secret's
  `Certificate` to force re-issue; manual: rotate the secret and reload). Low risk.
- Fix the renewal automation so it alerts at 21/14/7 days before expiry.

## Rollback
No rollback needed for a renewal; if the new chain is wrong, restore the previous secret and fix the chain.

## Escalation
Security on-call if the certificate authority is unavailable or the private key may be compromised.

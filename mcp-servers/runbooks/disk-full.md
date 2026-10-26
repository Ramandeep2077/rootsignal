---
id: disk-full
title: Disk or volume full
categories: [disk_full]
services: [payments, checkout, inventory, auth, api-gateway]
actions: [free_disk_space]
---
# Disk or volume full

## Symptoms
- `DiskSpaceCritical` alerts (volume above 92%, often reaching 100%).
- Writes fail: `No space left on device (errno 28)`. Services that must write (audit logs, uploads, temp
  files) start rejecting requests.
- Frequently preceded by a failing log rotation (`logrotate ... failed`).

## Diagnosis
1. Query `disk_used_percent` over the last hour: a steady climb means growth (logs); a step means a large
   file or dump.
2. Search logs for `logrotate`, `No space left on device`, and large dump creation.
3. Identify the biggest directories (`du -xh /var/log | sort -h | tail`).

## Remediation
- **free_disk_space**: compress or delete rotated logs and temporary files, then fix log rotation. Low risk
  when limited to rotated logs; **never** delete active data files or database directories.
- Expand the volume if growth is legitimate.

## Rollback
Deleted rotated logs cannot be restored; archive them to object storage first if they are needed for audits.

## Escalation
Platform on-call if the volume cannot be expanded or the node itself is out of space.

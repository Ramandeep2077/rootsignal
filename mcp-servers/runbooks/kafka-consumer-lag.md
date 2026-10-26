---
id: kafka-consumer-lag
title: Kafka consumer lag
categories: [kafka_consumer_lag]
services: [inventory]
actions: [scale_consumers, restart_service]
---
# Kafka consumer lag

## Symptoms
- `KafkaConsumerLagHigh`: consumer group lag growing steadily (e.g. `inventory-orders` on topic `orders`).
- Consumer logs: `processing batch ... took 312s; exceeded max.poll.interval.ms=300000, leaving group`
  and repeated `Consumer group ... rebalancing`.
- Downstream symptoms: data that depends on the events goes stale (orders stuck `PENDING`, reservations
  cancelled).

## Diagnosis
1. Query `kafka_consumer_lag` over time: linear growth means consumption is slower than production.
2. Search consumer logs for `max.poll.interval.ms`, `rebalancing` and per-batch processing times.
3. Check whether production rate spiked (upstream retry storm) or consumption slowed (slow downstream call,
   larger batches after a config change).

## Remediation
- **scale_consumers**: add consumer instances, up to the topic's partition count. Low risk.
- **restart_service**: restart stuck consumers to break a rebalance loop. Low risk.
- Reduce `max.poll.records` or speed up per-record processing so batches finish within the poll interval.

## Rollback
Scale consumers back down once lag is near zero.

## Escalation
Owning team if lag keeps growing after scaling; data team if events must be replayed.

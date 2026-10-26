-- Runs once when the Postgres volume is first created.
-- The alert service owns the `public` schema (managed by Flyway).
-- The Python side owns `telemetry` (simulated logs/metrics/deploys) and `knowledge` (runbook embeddings).
CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS telemetry;
CREATE SCHEMA IF NOT EXISTS knowledge;

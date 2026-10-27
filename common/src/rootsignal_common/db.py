"""Postgres access and the schema owned by the Python side.

The alert service (Java/Flyway) owns ``public``. Python owns:
- ``telemetry``: simulated logs, metrics and deployments that the MCP tools query
- ``knowledge``: runbook chunks + embeddings for vector search
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from rootsignal_common.settings import common_settings

EMBEDDING_DIM = 384  # all-MiniLM-L6-v2

SCHEMA_DDL = f"""
CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS telemetry;
CREATE SCHEMA IF NOT EXISTS knowledge;

CREATE TABLE IF NOT EXISTS telemetry.logs (
    id       BIGSERIAL PRIMARY KEY,
    run_id   TEXT        NOT NULL,
    ts       TIMESTAMPTZ NOT NULL,
    service  TEXT        NOT NULL,
    level    TEXT        NOT NULL,
    message  TEXT        NOT NULL,
    attrs    JSONB       NOT NULL DEFAULT '{{}}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_logs_service_ts ON telemetry.logs (service, ts DESC);
CREATE INDEX IF NOT EXISTS idx_logs_ts ON telemetry.logs (ts DESC);

CREATE TABLE IF NOT EXISTS telemetry.metrics (
    run_id   TEXT             NOT NULL,
    ts       TIMESTAMPTZ      NOT NULL,
    service  TEXT             NOT NULL,
    metric   TEXT             NOT NULL,
    value    DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_metrics_lookup ON telemetry.metrics (service, metric, ts DESC);

CREATE TABLE IF NOT EXISTS telemetry.deployments (
    id          BIGSERIAL PRIMARY KEY,
    run_id      TEXT        NOT NULL,
    ts          TIMESTAMPTZ NOT NULL,
    service     TEXT        NOT NULL,
    kind        TEXT        NOT NULL,
    version     TEXT,
    author      TEXT        NOT NULL,
    description TEXT        NOT NULL,
    diff        JSONB       NOT NULL DEFAULT '{{}}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_deployments_ts ON telemetry.deployments (ts DESC);

CREATE TABLE IF NOT EXISTS knowledge.runbooks (
    runbook_id   TEXT PRIMARY KEY,
    title        TEXT  NOT NULL,
    categories   JSONB NOT NULL,
    services     JSONB NOT NULL,
    actions      JSONB NOT NULL,
    body         TEXT  NOT NULL,
    content_hash TEXT  NOT NULL
);

CREATE TABLE IF NOT EXISTS knowledge.runbook_chunks (
    id          BIGSERIAL PRIMARY KEY,
    runbook_id  TEXT    NOT NULL REFERENCES knowledge.runbooks (runbook_id) ON DELETE CASCADE,
    title       TEXT    NOT NULL,
    section     TEXT    NOT NULL,
    content     TEXT    NOT NULL,
    embedding   vector({EMBEDDING_DIM}) NOT NULL,
    model       TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runbook_chunks_runbook ON knowledge.runbook_chunks (runbook_id);
"""


def connect(dsn: str | None = None, **kwargs) -> psycopg.Connection:
    return psycopg.connect(dsn or common_settings().dsn, row_factory=dict_row, **kwargs)


@contextmanager
def connection(dsn: str | None = None) -> Iterator[psycopg.Connection]:
    with connect(dsn) as conn:
        yield conn


def ensure_schema(conn: psycopg.Connection) -> None:
    """Idempotently create the telemetry/knowledge tables."""
    with conn.cursor() as cur:
        cur.execute(SCHEMA_DDL)
    conn.commit()

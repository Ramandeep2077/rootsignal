"""Shared pytest fixtures for all Python packages.

Database tests use a dedicated ``rootsignal_test`` database (created on demand) so they never touch dev data.
They are skipped automatically when Postgres isn't reachable.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import psycopg
import pytest

from rootsignal_common.db import connect, ensure_schema
from rootsignal_common.settings import BaseServiceSettings

# Tests must be deterministic and offline unless a test opts in explicitly.
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("EMBEDDINGS_PROVIDER", "hash")

TEST_DB = "rootsignal_test"


def _admin_dsn() -> str:
    return (
        BaseServiceSettings(database_url=None).dsn
        if not os.environ.get("TEST_ADMIN_DSN")
        else os.environ["TEST_ADMIN_DSN"]
    )


@pytest.fixture(scope="session")
def pg_dsn() -> str:
    settings = BaseServiceSettings(database_url=None)
    admin = _admin_dsn()
    try:
        with psycopg.connect(admin, autocommit=True, connect_timeout=3) as conn:
            exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", [TEST_DB]).fetchone()
            if not exists:
                conn.execute(f'CREATE DATABASE "{TEST_DB}"')
    except psycopg.OperationalError:
        pytest.skip("Postgres not reachable (start it with `make infra`)")
    dsn = (
        f"postgresql://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{TEST_DB}"
    )
    with connect(dsn) as conn:
        ensure_schema(conn)
    return dsn


@pytest.fixture
def pg_conn(pg_dsn: str) -> Iterator[psycopg.Connection]:
    with connect(pg_dsn) as conn:
        yield conn

"""Writes a simulation into a real Postgres (skipped when none is reachable)."""

import psycopg
import pytest

from oncall_common.db import connect, ensure_schema
from oncall_sim.engine import simulate
from oncall_sim.scenarios import get_scenario
from oncall_sim.sink import write_telemetry


@pytest.fixture
def conn():
    try:
        connection = connect(connect_timeout=2)
    except psycopg.OperationalError:
        pytest.skip("Postgres not reachable")
    ensure_schema(connection)
    yield connection
    connection.close()


@pytest.mark.integration
def test_write_telemetry_replaces_previous_run(conn):
    out = simulate(get_scenario("disk_full"), seed=1)
    write_telemetry(conn, "it-run-1", out)
    write_telemetry(conn, "it-run-2", out)
    with conn.cursor() as cur:
        cur.execute("select count(*) as n, count(distinct run_id) as runs from telemetry.logs")
        row = cur.fetchone()
    assert row["runs"] == 1
    assert row["n"] == len(out.logs)

from contextlib import contextmanager

import pytest

from oncall_common.db import connect
from oncall_sim.engine import simulate
from oncall_sim.scenarios import get_scenario
from oncall_sim.sink import write_telemetry


def load_scenario(dsn: str, name: str):
    out = simulate(get_scenario(name), seed=1)
    with connect(dsn) as conn:
        write_telemetry(conn, f"test-{name}", out)
    return out


@pytest.fixture
def factory(pg_dsn):
    @contextmanager
    def make():
        with connect(pg_dsn) as conn:
            yield conn

    return make

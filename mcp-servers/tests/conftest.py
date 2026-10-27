from contextlib import contextmanager

import pytest

from rootsignal_common.db import connect


@pytest.fixture
def factory(pg_dsn):
    @contextmanager
    def make():
        with connect(pg_dsn) as conn:
            yield conn

    return make

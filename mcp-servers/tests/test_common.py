from datetime import UTC, datetime, timedelta

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from rootsignal_mcp.tools.common import check_service, resolve_window


def test_relative_window_defaults_to_now():
    start, end = resolve_window(15, None, None)
    assert timedelta(minutes=14) < end - start <= timedelta(minutes=15)
    assert abs((datetime.now(UTC) - end).total_seconds()) < 5


def test_absolute_window_accepts_z_suffix():
    start, end = resolve_window(None, "2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z")
    assert end - start == timedelta(hours=1)


@pytest.mark.parametrize(
    ("since", "start", "end", "message"),
    [
        (-5, None, None, "positive"),
        (None, "2026-01-02T00:00:00Z", "2026-01-01T00:00:00Z", "before"),
        (None, "yesterday", None, "ISO-8601"),
        (None, "2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z", "7 days"),
    ],
)
def test_invalid_windows_raise_tool_errors(since, start, end, message):
    with pytest.raises(ToolError, match=message):
        resolve_window(since, start, end)


def test_service_validation():
    assert check_service(" Checkout ") == "checkout"
    assert check_service(None) is None
    with pytest.raises(ToolError, match="Known services"):
        check_service("billing")
    assert check_service("coredns", allow_external=True) == "coredns"

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from oncall_common.db import connect
from oncall_mcp.tools import deploys, logs, metrics

from .conftest import load_scenario

pytestmark = pytest.mark.integration


@pytest.fixture
def disk_full(pg_dsn):
    load_scenario(pg_dsn, "disk_full")
    with connect(pg_dsn) as conn:
        yield conn


def test_error_summary_surfaces_the_root_cause_first(disk_full):
    result = logs.error_summary(disk_full, since_minutes=60)
    top = result["patterns"][0]
    assert top["service"] == "payments"
    assert "No space left on device" in top["example"]
    assert top["count"] > 10


def test_search_logs_filters_by_keyword_level_and_service(disk_full):
    result = logs.search_logs(disk_full, service="payments", keyword="logrotate", since_minutes=60)
    assert result["total_matches"] == 1
    assert result["logs"][0]["level"] == "WARN"

    errors = logs.search_logs(disk_full, service="payments", level="error", since_minutes=60, limit=5)
    assert errors["returned"] == 5
    assert errors["total_matches"] > 5
    assert all(line["level"] == "ERROR" for line in errors["logs"])


def test_search_logs_validates_arguments(disk_full):
    with pytest.raises(ToolError, match="level"):
        logs.search_logs(disk_full, level="FATAL")
    with pytest.raises(ToolError, match="limit"):
        logs.search_logs(disk_full, limit=1000)


def test_query_metric_summarises_and_downsamples(disk_full):
    result = metrics.query_metric(
        disk_full, service="payments", metric="disk_used_percent", since_minutes=40, max_points=10
    )
    assert result["summary"]["max"] == 100.0
    assert result["summary"]["last"] == 100.0
    assert len(result["points"]) <= 11


def test_query_metric_rejects_unknown_metric(disk_full):
    with pytest.raises(ToolError, match="Available"):
        metrics.query_metric(disk_full, service="payments", metric="happiness")


def test_anomalies_point_at_the_failing_service(disk_full):
    result = metrics.detect_anomalies(disk_full, since_minutes=30, recent_minutes=10)
    top_services = {a["service"] for a in result["anomalies"][:4]}
    assert "payments" in top_services
    assert any(a["metric"] == "disk_used_percent" and a["service"] == "payments" for a in result["anomalies"])


def test_list_metrics_for_service(disk_full):
    names = {m["name"] for m in metrics.list_metrics(disk_full, service="checkout")["metrics"]}
    assert {"latency_p99_ms", "db_connections_in_use"} <= names
    assert "kafka_consumer_lag" not in names


def test_changes_show_the_causal_deploy(pg_dsn):
    load_scenario(pg_dsn, "bad_deployment")
    with connect(pg_dsn) as conn:
        result = deploys.list_changes(conn, service="payments", kind="deploy", since_minutes=60)
    assert [c["version"] for c in result["changes"]] == ["4.2.0"]
    assert "currency" in result["changes"][0]["description"]


def test_changes_validate_kind(pg_dsn):
    with connect(pg_dsn) as conn, pytest.raises(ToolError, match="kind"):
        deploys.list_changes(conn, kind="hotfix")

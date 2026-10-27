import pytest
from mcp.server.mcpserver.exceptions import ToolError

from rootsignal_common.embeddings import HashEmbedder
from rootsignal_common.taxonomy import ActionType, RootCauseCategory
from rootsignal_mcp.tools.runbooks import (
    get_runbook,
    ingest_runbooks,
    load_runbooks,
    parse_runbook,
    search_runbooks,
)
from rootsignal_sim.scenarios import SCENARIOS


def test_at_least_ten_runbooks_with_valid_metadata():
    runbooks = load_runbooks()
    assert len(runbooks) >= 10
    for rb in runbooks:
        assert {s for s, _ in rb.sections()} >= {"Symptoms", "Diagnosis", "Remediation", "Rollback"}, rb.id
        for action in rb.actions:
            ActionType(action)  # raises if a runbook recommends a non-allowlisted action
        for category in rb.categories:
            RootCauseCategory(category)


def test_every_category_and_scenario_has_a_runbook():
    runbooks = {rb.id: rb for rb in load_runbooks()}
    covered = {c for rb in runbooks.values() for c in rb.categories}
    assert covered == {c.value for c in RootCauseCategory}
    for scenario in SCENARIOS.values():
        gt = scenario.ground_truth
        assert gt.expected_runbook in runbooks, scenario.name
        assert {a.value for a in gt.expected_actions} <= set(runbooks[gt.expected_runbook].actions)


def test_front_matter_is_required():
    with pytest.raises(ValueError, match="front matter"):
        parse_runbook("# no front matter")


@pytest.mark.integration
def test_ingest_is_idempotent_and_search_ranks_relevant_runbook(pg_conn):
    embedder = HashEmbedder()
    n = ingest_runbooks(pg_conn, embedder)
    assert n == ingest_runbooks(pg_conn, embedder)  # unchanged corpus -> no re-index

    result = search_runbooks(
        pg_conn, embedder, query="writes fail: No space left on device, logrotate failed", k=3
    )
    assert result["results"][0]["runbook_id"] == "disk-full"
    assert result["results"][0]["allowed_actions"] == ["free_disk_space"]


@pytest.mark.integration
def test_get_runbook_and_unknown_id(pg_conn):
    ingest_runbooks(pg_conn, HashEmbedder())
    runbook = get_runbook(pg_conn, runbook_id="tls-certificate-expired")
    assert "x509" in runbook["markdown"]
    with pytest.raises(ToolError, match="Available"):
        get_runbook(pg_conn, runbook_id="nope")

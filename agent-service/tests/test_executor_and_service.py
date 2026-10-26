import pytest

from oncall_agent.executor import DryRunExecutor
from oncall_agent.guardrails import GuardrailPolicy
from oncall_agent.service import AgentService
from oncall_agent.settings import AgentSettings
from oncall_agent.testing import FakeAlertClient
from oncall_common.embeddings import HashEmbedder
from oncall_sim.testing import as_events
from oncall_sim.testing import load_scenario as load

SAFE = {
    "action": "renew_certificate",
    "target": "auth",
    "risk_level": "low",
    "steps": ["Renew the cert."],
    "rollback_plan": "Restore old secret.",
    "rationale": "Expired.",
    "runbook_id": "tls-certificate-expired",
    "dry_run": True,
    "guardrail": {"allowed": True},
}


async def test_approved_action_is_simulated_never_executed():
    client = FakeAlertClient()
    execution = await DryRunExecutor(client, GuardrailPolicy()).handle_decision(
        {"incidentId": "i1", "decision": "APPROVED", "decidedBy": "alice", "proposedAction": SAFE}
    )
    assert execution["status"] == "simulated" and execution["dry_run"] is True
    assert execution["plan"] == ["[dry-run] Renew the cert."]
    assert client.incidents["i1"]["execution"] == execution


async def test_tampered_proposal_is_blocked_at_execution_time():
    client = FakeAlertClient()
    tampered = {**SAFE, "steps": ["kubectl delete namespace prod"]}
    execution = await DryRunExecutor(client, GuardrailPolicy()).handle_decision(
        {"incidentId": "i2", "decision": "APPROVED", "decidedBy": "mallory", "proposedAction": tampered}
    )
    assert execution["status"] == "blocked"


async def test_rejection_executes_nothing():
    client = FakeAlertClient()
    result = await DryRunExecutor(client, GuardrailPolicy()).handle_decision(
        {"incidentId": "i3", "decision": "REJECTED", "proposedAction": SAFE}
    )
    assert result is None and "i3" not in client.incidents


@pytest.mark.integration
async def test_service_groups_storm_creates_one_incident_and_analyses_it(pg_dsn, mcp_servers):
    out = load(pg_dsn, "config_error")
    client = FakeAlertClient()
    service = AgentService(
        AgentSettings(
            _env_file=None, llm_provider="mock", triage_quiet_seconds=0.0, triage_window_seconds=0.0
        ),
        tool_servers=mcp_servers,
        embedder=HashEmbedder(),
        alert_client=client,
        consume_kafka=False,
    )
    await service.start()
    try:
        for event in as_events(out):
            await service.handle_alert(event)
        await service.flush_due()
        await service.queue.join()
    finally:
        await service.stop()

    statuses = sorted(i.get("status") for i in client.incidents.values())
    assert len(client.incidents) == 2, "storm -> 1 incident, background alert -> 1 incident"
    assert statuses == ["NEEDS_HUMAN", "PENDING_APPROVAL"]
    main = max(client.incidents.values(), key=lambda i: len(i["alertIds"]))
    assert main["rootCause"]["category"] == "config_error"
    assert service.stats.alerts_received == len(out.alerts)

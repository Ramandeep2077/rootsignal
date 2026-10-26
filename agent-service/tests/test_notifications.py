import httpx
import pytest
from fastapi.testclient import TestClient

from oncall_agent.notifications import (
    EmailNotifier,
    FallbackNotifier,
    IncidentNotice,
    LogNotifier,
    NotificationError,
    SlackNotifier,
    build_notifier,
    email_message,
    slack_payload,
)
from oncall_agent.notifications.mock_slack import app as mock_slack
from oncall_agent.settings import AgentSettings

STATE = {
    "incident_id": "inc-42",
    "alerts": [{"id": str(i)} for i in range(41)],
    "status": "PENDING_APPROVAL",
    "triage": {
        "title": "Payments errors after deploy",
        "severity": "CRITICAL",
        "affected_services": ["payments", "checkout", "api-gateway"],
        "summary": "...",
    },
    "hypothesis": {
        "category": "bad_deployment",
        "root_cause_service": "payments",
        "confidence": 0.95,
        "hypothesis": "v4.2.0 throws NullPointerException in PaymentMapper.",
    },
    "proposal": {"action": "rollback_deployment", "target": "payments", "risk_level": "low"},
}
USAGE = {"llm_calls": 6, "tool_calls": 7, "total_tokens": 11124, "estimated_cost_usd": 0.0}


def notice() -> IncidentNotice:
    return IncidentNotice.from_state(STATE, "http://dash.example/", USAGE)


def test_notice_carries_everything_the_on_call_needs():
    n = notice()
    assert n.approval_url == "http://dash.example/incidents/inc-42"
    assert n.alert_count == 41
    assert n.confidence_text == "95%"
    assert "needs approval" in n.action_text


def test_slack_payload_has_summary_fields_and_approval_button():
    payload = slack_payload(notice())
    text = str(payload)
    for expected in (
        "Payments errors after deploy",
        "CRITICAL",
        "payments, checkout, api-gateway",
        "41",
        "bad_deployment",
        "95%",
        "rollback_deployment",
        "NullPointerException",
    ):
        assert expected in text, expected
    (button,) = next(b for b in payload["blocks"] if b["type"] == "actions")["elements"]
    assert button["url"] == "http://dash.example/incidents/inc-42"
    assert button["style"] == "primary"


def test_email_body_mirrors_the_slack_message():
    message = email_message(notice(), "from@example.test", "to@example.test")
    assert message["Subject"] == "[CRITICAL] Payments errors after deploy (PENDING_APPROVAL)"
    assert "http://dash.example/incidents/inc-42" in message.get_content()


async def test_slack_failure_falls_back_to_email():
    sent = []
    failing_slack = SlackNotifier(
        "http://slack.invalid/hook",
        client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500, text="boom"))),
    )
    email = EmailNotifier("smtp", 25, "a@example.test", "b@example.test", send=sent.append)
    channel = await FallbackNotifier([failing_slack, email]).notify(notice())
    assert channel == "email"
    assert len(sent) == 1


async def test_all_channels_failing_raises():
    def broken(_):
        raise OSError("smtp down")

    with pytest.raises(NotificationError, match="smtp down"):
        await FallbackNotifier([EmailNotifier("h", 1, "a", "b", send=broken)]).notify(notice())


def test_build_notifier_picks_channels_from_settings():
    assert isinstance(build_notifier(AgentSettings(_env_file=None)), LogNotifier)
    notifier = build_notifier(
        AgentSettings(_env_file=None, slack_webhook_url="http://x/hook", smtp_host="mail")
    )
    assert [c.name for c in notifier.channels] == ["slack", "email"]


async def test_slack_notifier_against_the_mock_webhook():
    client = TestClient(mock_slack)
    client.delete("/messages")
    transport = httpx.MockTransport(
        lambda r: httpx.Response(
            200,
            text=client.post(
                "/webhook", content=r.content, headers={"content-type": "application/json"}
            ).text,
        )
    )
    await SlackNotifier("http://mock/webhook", client=httpx.AsyncClient(transport=transport)).notify(notice())
    (message,) = client.get("/messages").json()
    assert message["payload"]["text"].startswith("[CRITICAL] Payments errors after deploy")

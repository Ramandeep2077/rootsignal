"""Incident notifications: exactly one summary message per incident, never one per alert.

Slack (incoming webhook, Block Kit) is the primary channel; email (SMTP) is the fallback when Slack fails or
isn't configured. Informational-only incidents are not announced at all; they stay on the dashboard.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any, Protocol

import httpx

log = logging.getLogger(__name__)

SEVERITY_EMOJI = {
    "CRITICAL": ":red_circle:",
    "HIGH": ":large_orange_circle:",
    "MEDIUM": ":large_yellow_circle:",
    "LOW": ":large_blue_circle:",
    "INFO": ":white_circle:",
}


class NotificationError(Exception):
    pass


@dataclass(frozen=True)
class IncidentNotice:
    incident_id: str
    title: str
    severity: str
    services: list[str]
    alert_count: int
    status: str
    root_cause: str
    category: str | None
    confidence: float | None
    action: str | None
    target: str | None
    risk_level: str | None
    approval_url: str
    usage: str

    @classmethod
    def from_state(
        cls, state: dict[str, Any], dashboard_url: str, usage: dict[str, Any] | None = None
    ) -> IncidentNotice:
        triage, hypothesis, proposal = (
            state["triage"],
            state.get("hypothesis") or {},
            state.get("proposal") or {},
        )
        usage = usage or {}
        return cls(
            incident_id=str(state.get("incident_id")),
            title=triage["title"],
            severity=triage["severity"],
            services=triage["affected_services"],
            alert_count=len(state.get("alerts", [])),
            status=state.get("status", "UNKNOWN"),
            root_cause=hypothesis.get("hypothesis")
            or state.get("error")
            or "Investigation did not complete.",
            category=hypothesis.get("category"),
            confidence=hypothesis.get("confidence"),
            action=proposal.get("action"),
            target=proposal.get("target"),
            risk_level=proposal.get("risk_level"),
            approval_url=f"{dashboard_url.rstrip('/')}/incidents/{state.get('incident_id')}",
            usage=(
                f"{usage.get('llm_calls', 0)} LLM calls, {usage.get('tool_calls', 0)} tool calls, "
                f"{usage.get('total_tokens', 0):,} tokens, ${usage.get('estimated_cost_usd', 0.0):.4f}"
            ),
        )

    @property
    def confidence_text(self) -> str:
        return f"{self.confidence:.0%}" if self.confidence is not None else "n/a"

    @property
    def action_text(self) -> str:
        if not self.action:
            return "None"
        if self.status == "PENDING_APPROVAL":
            return f"{self.action} on {self.target} (risk {self.risk_level}, dry run, needs approval)"
        return f"{self.action} on {self.target}"


class Notifier(Protocol):
    async def notify(self, notice: IncidentNotice) -> str:
        """Send the notice; return the channel name. Raise NotificationError on failure."""
        ...


def slack_payload(n: IncidentNotice) -> dict[str, Any]:
    cause = "*Likely root cause*"
    if n.category:
        cause += f" (`{n.category}`, {n.confidence_text} confidence)"
    button = "Review & approve" if n.status == "PENDING_APPROVAL" else "Open incident"
    return {
        "text": f"[{n.severity}] {n.title} - {n.status}",  # notification/fallback text
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": f"{n.severity}: {n.title}"[:150]}},
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Severity*\n{SEVERITY_EMOJI.get(n.severity, '')} {n.severity}",
                    },
                    {"type": "mrkdwn", "text": f"*Status*\n{n.status}"},
                    {"type": "mrkdwn", "text": f"*Affected services*\n{', '.join(n.services)}"},
                    {"type": "mrkdwn", "text": f"*Alerts grouped*\n{n.alert_count}"},
                ],
            },
            {"type": "section", "text": {"type": "mrkdwn", "text": f"{cause}\n{n.root_cause[:1500]}"}},
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*Proposed action*\n{n.action_text}"}},
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": button},
                        "url": n.approval_url,
                        **({"style": "primary"} if n.status == "PENDING_APPROVAL" else {}),
                    },
                ],
            },
            {"type": "context", "elements": [{"type": "mrkdwn", "text": f"oncall-copilot · {n.usage}"}]},
        ],
    }


class SlackNotifier:
    name = "slack"

    def __init__(self, webhook_url: str, client: httpx.AsyncClient | None = None) -> None:
        self.webhook_url = webhook_url
        self._client = client or httpx.AsyncClient(timeout=10)

    async def notify(self, notice: IncidentNotice) -> str:
        try:
            response = await self._client.post(self.webhook_url, json=slack_payload(notice))
        except httpx.HTTPError as exc:
            raise NotificationError(f"slack unreachable: {exc}") from exc
        if response.status_code >= 300:
            raise NotificationError(f"slack returned {response.status_code}: {response.text[:200]}")
        return self.name


def email_message(n: IncidentNotice, sender: str, recipient: str) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = f"[{n.severity}] {n.title} ({n.status})"
    message["From"], message["To"] = sender, recipient
    message.set_content(
        f"{n.title}\n\nSeverity: {n.severity}\nStatus: {n.status}\nAffected services: {', '.join(n.services)}\n"
        f"Alerts grouped: {n.alert_count}\n\nLikely root cause ({n.category or 'unknown'}, {n.confidence_text} "
        f"confidence):\n{n.root_cause}\n\nProposed action: {n.action_text}\n\nReview: {n.approval_url}\n\n"
        f"-- oncall-copilot ({n.usage})\n"
    )
    return message


class EmailNotifier:
    name = "email"

    def __init__(
        self,
        host: str,
        port: int,
        sender: str,
        recipient: str,
        send: Callable[[EmailMessage], None] | None = None,
    ) -> None:
        self.host, self.port, self.sender, self.recipient = host, port, sender, recipient
        self._send = send or self._smtp_send

    def _smtp_send(self, message: EmailMessage) -> None:
        with smtplib.SMTP(self.host, self.port, timeout=10) as smtp:
            smtp.send_message(message)

    async def notify(self, notice: IncidentNotice) -> str:
        try:
            await asyncio.to_thread(self._send, email_message(notice, self.sender, self.recipient))
        except (OSError, smtplib.SMTPException) as exc:
            raise NotificationError(f"email failed: {exc}") from exc
        return self.name


class LogNotifier:
    name = "log"

    async def notify(self, notice: IncidentNotice) -> str:
        log.info(
            "incident %s [%s] %s: %s", notice.incident_id, notice.severity, notice.title, notice.action_text
        )
        return self.name


class FallbackNotifier:
    """Try channels in order; the first that succeeds wins (Slack, then email)."""

    def __init__(self, channels: Sequence[Notifier]) -> None:
        self.channels = list(channels)

    async def notify(self, notice: IncidentNotice) -> str:
        errors = []
        for channel in self.channels:
            try:
                return await channel.notify(notice)
            except NotificationError as exc:
                log.warning("notification channel failed, trying next: %s", exc)
                errors.append(str(exc))
        raise NotificationError("; ".join(errors) or "no notification channel configured")


def build_notifier(settings: Any) -> Notifier:
    channels: list[Notifier] = []
    if settings.slack_webhook_url:
        channels.append(SlackNotifier(settings.slack_webhook_url))
    if settings.smtp_host:
        channels.append(
            EmailNotifier(
                settings.smtp_host, settings.smtp_port, settings.notify_email_from, settings.notify_email_to
            )
        )
    return FallbackNotifier(channels) if channels else LogNotifier()

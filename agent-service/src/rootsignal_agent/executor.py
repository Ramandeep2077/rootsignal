"""Runs approved remediations — always as a dry run in this project.

Triggered only by an ``APPROVED`` event on ``incidents.decisions``, which the alert service emits only after
a human approves an incident in ``PENDING_APPROVAL``. The guardrails run again here (defence in depth: the
stored proposal could have been tampered with, or the policy could have tightened since it was proposed).
There is deliberately no code path that performs a live action.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from rootsignal_agent import guardrails
from rootsignal_agent.schemas import ProposedAction

log = logging.getLogger(__name__)


class DryRunExecutor:
    def __init__(self, alert_client: Any, policy: guardrails.GuardrailPolicy) -> None:
        self.alert_client = alert_client
        self.policy = policy

    async def handle_decision(self, event: dict[str, Any]) -> dict[str, Any] | None:
        if event.get("decision") != "APPROVED":
            log.info(
                "incident %s %s by %s; nothing to execute",
                event.get("incidentId"),
                event.get("decision"),
                event.get("decidedBy"),
            )
            return None
        incident_id = event["incidentId"]
        raw = dict(event.get("proposedAction") or {})
        raw.pop("guardrail", None)
        now = datetime.now(UTC).isoformat()
        try:
            proposal = ProposedAction(**raw)
            incident = await self.alert_client.get_incident(incident_id)
            confidence = float((incident.get("rootCause") or {}).get("confidence", 0.0))
            final, verdict = guardrails.check(
                proposal, confidence=confidence, runbook_actions=None, policy=self.policy
            )
        except Exception as exc:
            execution = {
                "status": "blocked",
                "dry_run": True,
                "reason": f"invalid proposal: {exc}",
                "at": now,
            }
        else:
            if not verdict.allowed:
                execution = {
                    "status": "blocked",
                    "dry_run": True,
                    "violations": verdict.violations,
                    "at": now,
                }
            else:
                execution = {
                    "status": "simulated",
                    "dry_run": True,
                    "action": final.action,
                    "target": final.target,
                    "approved_by": event.get("decidedBy"),
                    "plan": [f"[dry-run] {step}" for step in final.steps],
                    "rollback_plan": final.rollback_plan,
                    "note": "Dry-run mode: no change was made to any system.",
                    "at": now,
                }
        await self.alert_client.record_execution(incident_id, execution)
        log.info("incident %s execution recorded: %s", incident_id, execution["status"])
        return execution

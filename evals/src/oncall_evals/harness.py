"""Runs labelled scenarios through the real system and scores each run against ground truth.

Path under test (nothing mocked): simulator -> telemetry in Postgres + alerts over HTTP -> alert service (Java) ->
Kafka -> agent service (in-process here, so the model profile can be switched) -> MCP servers / Ollama ->
analysis written back to the alert service -> one notification. The harness then reads the incidents back
through the public API and compares them with the scenario's ground truth.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from oncall_agent.llm.ollama import OllamaChat
from oncall_agent.llm.router import ModelRouter, UsageTracker
from oncall_agent.routing import load_routing
from oncall_agent.schemas import ProposedAction
from oncall_agent.service import AgentService
from oncall_agent.settings import AgentSettings
from oncall_evals.guardrail_suite import final_is_safe
from oncall_evals.judge import judge
from oncall_sim.runner import ANALYSIS_DONE, incidents_for_run, run_scenario

log = logging.getLogger("oncall_evals")


def run_key(record: dict[str, Any]) -> tuple[str, str, int]:
    return record["profile"], record["scenario"], record["seed"]


def load_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _parse(ts: str | None) -> datetime | None:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None


def score_run(result: dict[str, Any], incidents: list[dict[str, Any]], *, timed_out: bool) -> dict[str, Any]:
    """Pure scoring of one run (unit-tested): grouping, diagnosis, remediation, latency and usage."""
    gt = result["ground_truth"]
    noise = set(result["noise_alert_ids"])
    real = set(result["alert_ids"]) - noise
    run_alerts = set(result["alert_ids"])
    record: dict[str, Any] = {
        "raw_alerts": len(run_alerts),
        "real_alerts": len(real),
        "incidents_created": len(incidents),
        "timed_out": timed_out,
    }
    if not incidents:
        return {**record, "analysed": False}

    def members(incident):
        return {a["id"] for a in incident["alerts"]} & run_alerts

    primary = max(incidents, key=lambda i: len(members(i) & real))
    in_primary = members(primary)
    root, proposal, usage = (
        primary.get("rootCause") or {},
        primary.get("proposedAction") or {},
        primary.get("llmUsage") or {},
    )
    accepted_services = {gt["root_cause_service"], *gt["acceptable_services"]}
    first, notified = _parse(primary.get("firstAlertAt")), _parse(primary.get("notifiedAt"))
    safe = True
    if proposal:
        try:
            safe = final_is_safe(ProposedAction(**{k: v for k, v in proposal.items() if k != "guardrail"}))
        except Exception:
            safe = False
    return {
        **record,
        "analysed": primary["status"] in ANALYSIS_DONE or primary["status"] in ("APPROVED", "REJECTED"),
        "primary_incident_id": primary["id"],
        "status": primary["status"],
        "grouping_recall": len(in_primary & real) / len(real) if real else None,
        "grouping_precision": len(in_primary & real) / len(in_primary) if in_primary else None,
        "noise_absorbed": bool(in_primary & noise),
        "predicted_category": root.get("category"),
        "predicted_service": root.get("root_cause_service"),
        "confidence": root.get("confidence"),
        "hypothesis": root.get("hypothesis"),
        "category_correct": root.get("category") == gt["category"],
        "service_correct": root.get("root_cause_service") in accepted_services,
        "proposed_action": proposal.get("action"),
        "action_correct": proposal.get("action") in gt["expected_actions"]
        and primary["status"] == "PENDING_APPROVAL",
        "runbook_correct": proposal.get("runbook_id") == gt["expected_runbook"],
        "guardrail_allowed": (proposal.get("guardrail") or {}).get("allowed"),
        "unsafe_pending_approval": primary["status"] == "PENDING_APPROVAL" and not safe,
        "time_to_summary_s": primary.get("timeToSummarySeconds"),
        "time_to_notification_s": (notified - first).total_seconds() if notified and first else None,
        "notified": notified is not None,
        "total_tokens": usage.get("total_tokens", 0),
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        "llm_calls": usage.get("llm_calls", 0),
        "failed_llm_calls": usage.get("failed_calls", 0),
        "tool_calls": usage.get("tool_calls", 0),
        "llm_latency_ms": usage.get("llm_latency_ms", 0.0),
        "cost_usd": usage.get("estimated_cost_usd", 0.0),
        "models": sorted({m for a in (usage.get("by_agent") or {}).values() for m in a.get("models", [])}),
    }


class Harness:
    def __init__(
        self, *, out: Path, timeout: float = 900.0, burst_seconds: float = 12.0, use_judge: bool = True
    ):
        self.out = out
        self.timeout = timeout
        self.burst_seconds = burst_seconds
        self.use_judge = use_judge
        self.base = AgentSettings()
        self.http = httpx.AsyncClient(base_url=self.base.alert_service_url, timeout=15)
        self.done = {run_key(r) for r in load_records(out)}

    def judge_router(self) -> ModelRouter | None:
        if not self.use_judge:
            return None
        return ModelRouter(
            load_routing(self.base.model_copy(update={"llm_provider": "ollama"}), "routed"),
            OllamaChat(self.base.ollama_base_url),
        )

    async def run_profile(self, profile: str, scenarios: Iterable[str], runs: int) -> None:
        todo = [
            (scenario, seed)
            for seed in range(1, runs + 1)
            for scenario in scenarios
            if (profile, scenario, seed) not in self.done
        ]
        if not todo:
            log.info("[%s] nothing to do (all runs already recorded)", profile)
            return
        settings = self.base.model_copy(
            update={
                "model_profile": profile,
                "llm_provider": "ollama",
                "consumer_group": f"eval-{profile}-{uuid.uuid4().hex[:6]}",
                "slack_webhook_url": self.base.slack_webhook_url or "http://localhost:8090/webhook",
                "smtp_host": self.base.smtp_host or "localhost",
            }
        )
        service = AgentService(settings, routing=load_routing(settings, profile))
        judge_router = self.judge_router()
        await service.start()
        try:
            await service.wait_ready()
            for scenario, seed in todo:
                record = await self.run_one(service, profile, scenario, seed, judge_router)
                with self.out.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(record, default=str) + "\n")
                self.done.add((profile, scenario, seed))
                log.info(
                    "[%s] %s seed=%d -> %s (truth %s) tts=%s",
                    profile,
                    scenario,
                    seed,
                    record.get("predicted_category"),
                    record["ground_truth"]["category"],
                    record.get("time_to_summary_s"),
                )
        finally:
            await service.stop()
            if judge_router and isinstance(judge_router.client, OllamaChat):
                await judge_router.client.aclose()

    async def run_one(
        self, service: AgentService, profile: str, scenario: str, seed: int, judge_router: ModelRouter | None
    ) -> dict[str, Any]:
        service.reset_grouping()
        started = time.time()
        result = (
            await asyncio.to_thread(run_scenario, scenario, seed=seed, burst_seconds=self.burst_seconds)
        ).to_dict()
        incidents, timed_out = await self._wait(result["run_id"], len(result["alert_ids"]))
        await self._wait_idle(service)
        details = [(await self.http.get(f"/api/incidents/{i['id']}")).json() for i in incidents]
        record = {
            "profile": profile,
            "scenario": scenario,
            "seed": seed,
            "run_id": result["run_id"],
            "started_at": datetime.fromtimestamp(started).isoformat(timespec="seconds"),
            "wall_seconds": round(time.time() - started, 1),
            "ground_truth": result["ground_truth"],
            **score_run(result, details, timed_out=timed_out),
        }
        if judge_router and record.get("hypothesis"):
            primary = next(d for d in details if d["id"] == record["primary_incident_id"])
            usage = UsageTracker({})
            verdict = await judge(judge_router, result["ground_truth"], primary.get("rootCause"), usage)
            record["judge_score"] = verdict.score if verdict else None
            record["judge_correct"] = verdict.correct if verdict else None
            record["judge_rationale"] = verdict.rationale if verdict else None
        return record

    async def _wait(self, run_id: str, expected: int) -> tuple[list[dict[str, Any]], bool]:
        deadline = time.monotonic() + self.timeout
        incidents: list[dict[str, Any]] = []
        while time.monotonic() < deadline:
            incidents = await asyncio.to_thread(incidents_for_run, run_id)
            grouped = sum(int(i["run_alerts"]) for i in incidents)
            if incidents and grouped >= expected and all(i["status"] in ANALYSIS_DONE for i in incidents):
                # The notification is sent right after the analysis is stored; give it a moment to land.
                for _ in range(20):
                    if all(i["notified_at"] or i["status"] == "NEEDS_HUMAN" for i in incidents):
                        break
                    await asyncio.sleep(0.5)
                    incidents = await asyncio.to_thread(incidents_for_run, run_id)
                return incidents, False
            await asyncio.sleep(2.0)
        return incidents, True

    @staticmethod
    async def _wait_idle(service: AgentService, timeout: float = 120.0) -> None:
        deadline = time.monotonic() + timeout
        while not service.idle and time.monotonic() < deadline:
            await asyncio.sleep(0.5)

    async def aclose(self) -> None:
        await self.http.aclose()

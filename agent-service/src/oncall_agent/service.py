"""The agent service runtime: Kafka consumers -> alert grouping -> incident creation -> agent graph.

Everything runs on one asyncio loop:
- ``_consume_alerts``     reads ``alerts.raw`` and feeds the grouper
- ``_flush_loop``         turns due groups into incidents and queues them for investigation
- ``_worker``             runs the LangGraph workflow (bounded concurrency; CPU inference is the bottleneck)
- ``_consume_decisions``  reads ``incidents.decisions`` and runs approved actions as dry runs
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from aiokafka import AIOKafkaConsumer
from mcp.server.mcpserver import MCPServer
from opentelemetry import context as otel_context
from opentelemetry.trace import SpanKind

from oncall_agent.agents import RunContext, max_severity
from oncall_agent.agents.triage import heuristic_summary
from oncall_agent.alert_client import AlertServiceClient
from oncall_agent.executor import DryRunExecutor
from oncall_agent.graph import build_graph
from oncall_agent.grouping import AlertGroup, AlertGrouper
from oncall_agent.guardrails import GuardrailPolicy
from oncall_agent.llm.base import ChatModel
from oncall_agent.llm.ollama import OllamaChat
from oncall_agent.llm.router import ModelRouter, UsageTracker
from oncall_agent.notifications import Notifier, build_notifier
from oncall_agent.routing import Routing, load_routing
from oncall_agent.settings import AgentSettings
from oncall_agent.tools import Toolbox
from oncall_agent.trace import Trace
from oncall_common.embeddings import Embedder, get_embedder
from oncall_common.telemetry import AGENT, extract_context, inject_context, link_from, span

log = logging.getLogger(__name__)
LOW_ONLY = {"LOW", "INFO"}


@dataclass
class Stats:
    alerts_received: int = 0
    groups_created: int = 0
    alerts_attached_late: int = 0
    incidents_analyzed: int = 0
    incidents_failed: int = 0
    notifications_sent: int = 0
    last_error: str | None = None
    started_at: float = field(default_factory=time.time)


class AgentService:
    def __init__(
        self,
        settings: AgentSettings,
        *,
        routing: Routing | None = None,
        chat_client: ChatModel | None = None,
        tool_servers: dict[str, str | MCPServer] | None = None,
        embedder: Embedder | None = None,
        notifier: Notifier | None = None,
        alert_client: AlertServiceClient | None = None,
        consume_kafka: bool = True,
    ) -> None:
        self.settings = settings
        self.routing = routing or load_routing(settings)
        self._owns_chat = chat_client is None and settings.llm_provider != "mock"
        self.chat_client = (
            chat_client
            if chat_client is not None
            else (OllamaChat(settings.ollama_base_url) if self._owns_chat else None)
        )
        self.router = ModelRouter(self.routing, self.chat_client)
        self.tool_servers = tool_servers or {
            "logs": settings.logs_mcp_url,
            "metrics": settings.metrics_mcp_url,
            "deploys": settings.deploys_mcp_url,
            "runbooks": settings.runbooks_mcp_url,
        }
        self.embedder = embedder
        self.notifier = notifier or build_notifier(settings)
        self.alert_client = alert_client or AlertServiceClient(
            settings.alert_service_url, settings.internal_api_token
        )
        self.policy = GuardrailPolicy(
            min_confidence=settings.min_confidence_for_action, dry_run=settings.remediation_dry_run
        )
        self.executor = DryRunExecutor(self.alert_client, self.policy)
        self.consume_kafka = consume_kafka
        self.graph = build_graph()
        self.stats = Stats()
        self.queue: asyncio.Queue[tuple[str, list[dict[str, Any]]]] = asyncio.Queue()
        self.toolbox: Toolbox | None = None
        self.grouper: AlertGrouper | None = None
        self._tasks: list[asyncio.Task] = []
        self._busy = 0
        self.ready: dict[str, asyncio.Event] = {}

    # ---- lifecycle ----

    async def start(self) -> None:
        self.embedder = self.embedder or await asyncio.to_thread(get_embedder)
        self.grouper = AlertGrouper(
            self.embedder,
            similarity_threshold=self.settings.similarity_threshold,
            window_seconds=self.settings.triage_window_seconds,
            quiet_seconds=self.settings.triage_quiet_seconds,
            attach_seconds=self.settings.attach_window_minutes * 60,
        )
        self.toolbox = await Toolbox(self.tool_servers).__aenter__()
        self._tasks.append(asyncio.create_task(self._flush_loop(), name="flush"))
        for i in range(self.settings.max_concurrent_investigations):
            self._tasks.append(asyncio.create_task(self._worker(), name=f"worker-{i}"))
        if self.consume_kafka:
            self._tasks.append(asyncio.create_task(self._consume_alerts(), name="alerts-consumer"))
            self._tasks.append(asyncio.create_task(self._consume_decisions(), name="decisions-consumer"))
        log.info("agent service started; routing=%s", self.routing.describe())

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._tasks.clear()
        if self.toolbox:
            await self.toolbox.__aexit__(None, None, None)
        await self.alert_client.aclose()
        if self._owns_chat and isinstance(self.chat_client, OllamaChat):
            await self.chat_client.aclose()

    @property
    def idle(self) -> bool:
        return self.queue.empty() and self._busy == 0 and self.grouper is not None and not self.grouper.open

    def status(self) -> dict[str, Any]:
        return {
            "routing": self.routing.describe(),
            "queue_depth": self.queue.qsize(),
            "investigations_in_progress": self._busy,
            "open_groups": len(self.grouper.open) if self.grouper else 0,
            "stats": self.stats.__dict__,
        }

    # ---- alert path ----

    async def handle_alert(self, alert: dict[str, Any]) -> None:
        assert self.grouper is not None
        self.stats.alerts_received += 1
        placement = self.grouper.add(alert)
        if placement.kind == "attach" and placement.group.incident_id:
            await self._attach_pending(placement.group)

    async def _attach_pending(self, group: AlertGroup) -> None:
        pending, group.pending_attach = group.pending_attach, []
        if not pending or not group.incident_id:
            group.pending_attach.extend(pending)
            return
        try:
            await self.alert_client.attach_alerts(group.incident_id, [a["id"] for a in pending])
            self.stats.alerts_attached_late += len(pending)
        except Exception as exc:
            log.warning("could not attach late alerts to %s: %s", group.incident_id, exc)

    async def flush_due(self) -> None:
        assert self.grouper is not None
        for group in self.grouper.due():
            await self._create_incident(group)

    async def _create_incident(self, group: AlertGroup) -> None:
        summary = heuristic_summary(group.alerts)
        try:
            incident = await self.alert_client.create_incident(
                summary.title,
                max_severity(group.alerts),
                summary.affected_services,
                [a["id"] for a in group.alerts],
            )
        except Exception as exc:
            self.stats.last_error = f"create incident: {exc}"
            log.error("could not create incident for group %s: %s", group.id, exc)
            return
        group.incident_id = incident["id"]
        self.stats.groups_created += 1
        await self._attach_pending(group)
        log.info(
            "incident %s created from %d alerts (%s)",
            group.incident_id,
            len(group.alerts),
            ", ".join(sorted(group.services)),
        )
        await self.queue.put((group.incident_id, list(group.alerts)))

    async def _flush_loop(self) -> None:
        while True:
            try:
                await self.flush_due()
            except Exception as exc:
                log.exception("flush failed")
                self.stats.last_error = str(exc)
            await asyncio.sleep(1.0)

    # ---- investigation path ----

    async def _worker(self) -> None:
        while True:
            incident_id, alerts = await self.queue.get()
            self._busy += 1
            try:
                await self.investigate(incident_id, alerts)
            finally:
                self._busy -= 1
                self.queue.task_done()

    async def investigate(self, incident_id: str | None, alerts: list[dict[str, Any]]) -> dict[str, Any]:
        assert self.toolbox is not None
        ctx = RunContext(
            router=self.router,
            toolbox=self.toolbox,
            trace=Trace(),
            usage=UsageTracker(self.routing.pricing),
            policy=self.policy,
            alert_client=self.alert_client,
            notifier=self.notifier,
            dashboard_url=self.settings.dashboard_url,
        )
        if all(a["severity"] in LOW_ONLY for a in alerts):
            return await self._record_low_severity(incident_id, alerts, ctx)
        # One trace per incident, linked to the traces of the alerts it groups (many-to-one: links, not parents).
        links = [link for a in alerts[:32] if (link := link_from(a.get("_trace")))]
        attributes = {
            "incident.id": incident_id,
            "incident.alert_count": len(alerts),
            "llm.routing_profile": self.routing.profile,
        }
        with span("incident.investigate", kind=AGENT, links=links, attributes=attributes) as current:
            state = await self._run_graph(incident_id, alerts, ctx)
            usage = ctx.usage.summary()
            current.set_attributes(
                {
                    "incident.status": str(state.get("status")),
                    "llm.token_count.total": usage["total_tokens"],
                    "incident.cost_usd": usage["estimated_cost_usd"],
                }
            )
            return state

    async def _run_graph(
        self, incident_id: str | None, alerts: list[dict[str, Any]], ctx: RunContext
    ) -> dict[str, Any]:
        try:
            state = await self.graph.ainvoke({"incident_id": incident_id, "alerts": alerts}, context=ctx)
            self.stats.incidents_analyzed += 1
            if state.get("notified"):
                self.stats.notifications_sent += 1
            return state
        except Exception as exc:
            log.exception("graph failed for incident %s", incident_id)
            self.stats.incidents_failed += 1
            self.stats.last_error = str(exc)
            return {"incident_id": incident_id, "status": "ERROR", "error": str(exc)}

    async def _record_low_severity(
        self, incident_id: str | None, alerts: list[dict[str, Any]], ctx: RunContext
    ) -> dict[str, Any]:
        """Informational-only groups don't justify an LLM investigation; record them for humans instead."""
        summary = heuristic_summary(alerts)
        ctx.trace.add("triage", "decision", "Low-severity alerts only; skipped automated investigation")
        if incident_id:
            await self.alert_client.record_analysis(
                incident_id,
                {
                    "status": "NEEDS_HUMAN",
                    "title": summary.title,
                    "severity": summary.severity,
                    "summary": summary.summary + " Informational only; no investigation run.",
                    "reasoningTrace": ctx.trace.steps,
                    "llmUsage": ctx.usage.summary(),
                },
            )
        self.stats.incidents_analyzed += 1
        return {"incident_id": incident_id, "status": "NEEDS_HUMAN", "summary": summary.summary}

    # ---- Kafka ----

    def _consumer(self, topic: str, group_suffix: str) -> AIOKafkaConsumer:
        return AIOKafkaConsumer(
            topic,
            bootstrap_servers=self.settings.kafka_bootstrap_servers,
            group_id=f"{self.settings.consumer_group}-{group_suffix}",
            auto_offset_reset="latest",
            enable_auto_commit=True,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        )

    async def _consume_alerts(self) -> None:
        await self._consume(self.settings.alerts_topic, "triage", self.handle_alert)

    async def _consume_decisions(self) -> None:
        await self._consume(self.settings.decisions_topic, "executor", self.executor.handle_decision)

    async def _await_assignment(self, consumer: AIOKafkaConsumer, topic: str) -> None:
        """Partitions are assigned asynchronously after start(); flag readiness once they are."""
        for _ in range(300):
            if consumer.assignment():
                break
            await asyncio.sleep(0.1)
        self.ready.setdefault(topic, asyncio.Event()).set()
        log.info("consuming %s (partitions %s)", topic, sorted(p.partition for p in consumer.assignment()))

    async def wait_ready(self, timeout: float = 60.0) -> None:
        """Block until every Kafka consumer has partitions (callers then know no alert will be missed)."""
        topics = [self.settings.alerts_topic, self.settings.decisions_topic] if self.consume_kafka else []
        for topic in topics:
            await asyncio.wait_for(self.ready.setdefault(topic, asyncio.Event()).wait(), timeout)

    def reset_grouping(self) -> None:
        """Forget closed groups so the next alert storm can't attach to a previous incident (eval isolation)."""
        if self.grouper:
            self.grouper.closed.clear()

    async def _consume(self, topic: str, suffix: str, handler) -> None:
        while True:
            consumer = self._consumer(topic, suffix)
            try:
                await consumer.start()
                await self._await_assignment(consumer, topic)
                async for message in consumer:
                    # Continue the producer's trace: Spring Kafka puts traceparent in the record headers.
                    token = otel_context.attach(extract_context(message.headers))
                    try:
                        with span(
                            f"{topic} process",
                            span_kind=SpanKind.CONSUMER,
                            attributes={"messaging.system": "kafka", "messaging.destination.name": topic},
                        ):
                            value = message.value
                            if isinstance(value, dict):
                                value["_trace"] = inject_context()
                            await handler(value)
                    except Exception as exc:
                        log.exception("handler for %s failed", topic)
                        self.stats.last_error = str(exc)
                    finally:
                        otel_context.detach(token)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("kafka consumer for %s failed (%s); reconnecting in 5s", topic, exc)
                await asyncio.sleep(5)
            finally:
                with contextlib.suppress(Exception):
                    await consumer.stop()

"""OpenTelemetry setup shared by the Python services.

Tracing is opt-in: it's enabled when ``OTEL_TRACES_EXPORTER=otlp`` (what ``make up-obs`` sets). Spans go to
the OTLP endpoint (Jaeger) and, when ``PHOENIX_COLLECTOR_ENDPOINT`` is set, also to Arize Phoenix, which
renders the LLM/tool spans (OpenInference attributes) as an LLM trace view with token counts.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any

from opentelemetry import context as otel_context
from opentelemetry import propagate, trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ALWAYS_ON, Decision, ParentBased, Sampler, SamplingResult
from opentelemetry.trace import Link, Span, SpanKind, Status, StatusCode

log = logging.getLogger(__name__)
_configured = False

# OpenInference span kinds (understood by Phoenix).
LLM, TOOL, CHAIN, AGENT = "LLM", "TOOL", "CHAIN", "AGENT"


class DropHealthChecks(Sampler):
    """Root sampler that drops container health-check requests (children follow via ParentBased)."""

    NOISE = frozenset({"GET /health", "GET /status"})

    def should_sample(self, parent_context, trace_id, name, kind=None, attributes=None, links=None):
        if name in self.NOISE or (attributes or {}).get("http.route") == "/health":
            return SamplingResult(Decision.DROP)
        return ALWAYS_ON.should_sample(parent_context, trace_id, name, kind, attributes, links)

    def get_description(self) -> str:
        return "DropHealthChecks"


def tracing_enabled() -> bool:
    return os.environ.get("OTEL_TRACES_EXPORTER", "none").lower() == "otlp"


def setup_tracing(service_name: str) -> None:
    """Install a tracer provider with OTLP exporters (idempotent; a no-op unless tracing is enabled)."""
    global _configured
    if _configured or not tracing_enabled():
        return
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

    resource = Resource.create(
        {
            "service.name": os.environ.get("OTEL_SERVICE_NAME", service_name),
            "openinference.project.name": "oncall-copilot",
        }
    )
    provider = TracerProvider(resource=resource, sampler=ParentBased(root=DropHealthChecks()))
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318").rstrip("/")
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces")))
    phoenix = os.environ.get("PHOENIX_COLLECTOR_ENDPOINT")
    if phoenix:
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{phoenix.rstrip('/')}/v1/traces"))
        )
    trace.set_tracer_provider(provider)
    # Propagates traceparent on every httpx call (alert service, Ollama, MCP over HTTP).
    HTTPXClientInstrumentor().instrument()
    _configured = True
    log.info("tracing enabled: service=%s otlp=%s phoenix=%s", service_name, endpoint, phoenix or "off")


def tracer(name: str = "oncall"):
    return trace.get_tracer(name)


@contextmanager
def span(
    name: str,
    *,
    kind: str | None = None,
    attributes: Mapping[str, Any] | None = None,
    links: Sequence[Link] | None = None,
    span_kind: SpanKind = SpanKind.INTERNAL,
    tracer_name: str = "oncall",
) -> Iterator[Span]:
    """Start a span; ``kind`` sets the OpenInference span kind. Exceptions mark the span as errored."""
    attrs = {k: v for k, v in (attributes or {}).items() if v is not None}
    if kind:
        attrs["openinference.span.kind"] = kind
    with tracer(tracer_name).start_as_current_span(
        name, kind=span_kind, attributes=attrs, links=list(links or []), record_exception=True
    ) as current:
        try:
            yield current
        except Exception as exc:
            current.set_status(Status(StatusCode.ERROR, str(exc)))
            raise


def inject_context() -> dict[str, str]:
    """W3C trace context of the current span, as a carrier dict."""
    carrier: dict[str, str] = {}
    propagate.inject(carrier)
    return carrier


def extract_context(headers: Mapping[str, str] | Sequence[tuple[str, bytes]] | None) -> otel_context.Context:
    """Context from W3C headers: a dict, or Kafka-style ``[(key, bytes)]`` record headers."""
    if not headers:
        return otel_context.Context()
    if not isinstance(headers, Mapping):
        headers = {k: (v.decode() if isinstance(v, bytes) else str(v)) for k, v in headers}
    return propagate.extract(dict(headers))


def link_from(carrier: Mapping[str, str] | None) -> Link | None:
    """A span link to the span described by ``carrier`` (used to link an incident to its alerts' traces)."""
    if not carrier:
        return None
    span_context = trace.get_current_span(propagate.extract(dict(carrier))).get_span_context()
    return Link(span_context) if span_context.is_valid else None


def clip(value: Any, limit: int = 4000) -> str:
    text = value if isinstance(value, str) else repr(value)
    return text if len(text) <= limit else text[:limit] + "…"

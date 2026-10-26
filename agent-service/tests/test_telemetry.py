"""Spans carry the OpenInference/GenAI attributes Phoenix needs, and trace context crosses process boundaries."""

import httpx
import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from oncall_agent.llm.ollama import OllamaChat
from oncall_common.telemetry import extract_context, inject_context, link_from, span

EXPORTER = InMemorySpanExporter()


@pytest.fixture(autouse=True)
def spans():
    if not isinstance(trace.get_tracer_provider(), TracerProvider):
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(EXPORTER))
        trace.set_tracer_provider(provider)
    EXPORTER.clear()
    yield EXPORTER


async def test_llm_call_becomes_an_llm_span_with_token_counts(spans):
    def ollama(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"message": {"content": "pool exhausted"}, "prompt_eval_count": 812, "eval_count": 64}
        )

    chat = OllamaChat("http://ollama", client=httpx.AsyncClient(transport=httpx.MockTransport(ollama)))
    await chat.chat("qwen2.5:7b", [{"role": "user", "content": "why?"}], max_tokens=100)

    (llm,) = [s for s in spans.get_finished_spans() if s.name == "chat qwen2.5:7b"]
    attrs = llm.attributes
    assert attrs["openinference.span.kind"] == "LLM"
    assert attrs["llm.model_name"] == "qwen2.5:7b"
    assert attrs["llm.token_count.prompt"] == 812
    assert attrs["gen_ai.usage.output_tokens"] == 64
    assert attrs["input.value"] == "why?"
    assert attrs["output.value"] == "pool exhausted"


def test_trace_context_round_trips_through_kafka_style_headers(spans):
    with span("producer") as producer:
        carrier = inject_context()
    headers = [(key, value.encode()) for key, value in carrier.items()]
    with span("consumer", attributes={}) as _:
        pass
    ctx = extract_context(headers)
    restored = trace.get_current_span(ctx).get_span_context()
    assert restored.trace_id == producer.get_span_context().trace_id

    link = link_from(carrier)
    assert link is not None and link.context.span_id == producer.get_span_context().span_id


def test_failed_span_is_marked_as_error(spans):
    with pytest.raises(RuntimeError), span("boom"):
        raise RuntimeError("kaput")
    (failed,) = [s for s in spans.get_finished_spans() if s.name == "boom"]
    assert failed.status.status_code.name == "ERROR"

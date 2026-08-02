import pytest
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from app.core.telemetry import Telemetry


def test_telemetry_exports_nested_business_spans_and_trace_id() -> None:
    exporter = InMemorySpanExporter()
    telemetry = Telemetry(
        service_name="evalops-test",
        span_processors=(SimpleSpanProcessor(exporter),),
    )

    with telemetry.start_as_current_span(
        "job.process",
        attributes={"job.id": "job-1"},
    ):
        trace_id = telemetry.current_trace_id()
        with telemetry.start_as_current_span("target.call"):
            pass

    spans = exporter.get_finished_spans()
    by_name = {span.name: span for span in spans}
    assert set(by_name) == {"job.process", "target.call"}
    assert trace_id is not None
    assert len(trace_id) == 32
    assert by_name["target.call"].parent is not None
    assert by_name["target.call"].parent.span_id == by_name["job.process"].context.span_id
    attributes = by_name["job.process"].attributes
    assert attributes is not None
    assert attributes["job.id"] == "job-1"


def test_telemetry_captures_traceparent_and_links_a_new_root_trace() -> None:
    exporter = InMemorySpanExporter()
    telemetry = Telemetry(
        service_name="evalops-test",
        span_processors=(SimpleSpanProcessor(exporter),),
    )

    with telemetry.start_as_current_span("run.create") as origin_span:
        origin_context = origin_span.get_span_context()
        traceparent = telemetry.capture_traceparent()

    assert traceparent == (
        f"00-{origin_context.trace_id:032x}-{origin_context.span_id:016x}"
        f"-{int(origin_context.trace_flags):02x}"
    )

    with telemetry.start_as_current_span(
        "job.process",
        links=telemetry.links_from_traceparent(traceparent),
    ):
        pass

    spans = {span.name: span for span in exporter.get_finished_spans()}
    worker_span = spans["job.process"]
    assert worker_span.parent is None
    assert worker_span.context.trace_id != origin_context.trace_id
    assert len(worker_span.links) == 1
    assert worker_span.links[0].context.trace_id == origin_context.trace_id
    assert worker_span.links[0].context.span_id == origin_context.span_id


def test_missing_or_invalid_traceparent_produces_no_links() -> None:
    telemetry = Telemetry(service_name="evalops-test")

    assert telemetry.links_from_traceparent(None) == ()
    assert telemetry.links_from_traceparent("not-a-traceparent") == ()
    with telemetry.start_as_current_span("ambient"):
        assert telemetry.links_from_traceparent("still-not-a-traceparent") == ()


def test_traceparent_capture_failure_degrades_to_missing_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    telemetry = Telemetry(service_name="evalops-test")

    def fail_injection(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("propagator unavailable")

    monkeypatch.setattr(TraceContextTextMapPropagator, "inject", fail_injection)

    with telemetry.start_as_current_span("run.create"):
        assert telemetry.capture_traceparent() is None


def test_disabled_telemetry_has_no_trace_identifier() -> None:
    telemetry = Telemetry(service_name="evalops-test", enabled=False)

    with telemetry.start_as_current_span("disabled"):
        assert telemetry.current_trace_id() is None
        assert telemetry.capture_traceparent() is None

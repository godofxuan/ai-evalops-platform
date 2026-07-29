from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

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
    assert len(trace_id) == 32
    assert by_name["target.call"].parent is not None
    assert by_name["target.call"].parent.span_id == by_name["job.process"].context.span_id
    assert by_name["job.process"].attributes["job.id"] == "job-1"


def test_disabled_telemetry_has_no_trace_identifier() -> None:
    telemetry = Telemetry(service_name="evalops-test", enabled=False)

    with telemetry.start_as_current_span("disabled"):
        assert telemetry.current_trace_id() is None

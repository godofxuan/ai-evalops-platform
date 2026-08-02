from collections.abc import Iterable, Mapping, Sequence
from contextlib import AbstractContextManager
from typing import Any

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.propagators.textmap import CarrierT
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Link, NoOpTracerProvider, Span
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator


class Telemetry:
    """Process-local tracer provider with optional OTLP/HTTP export."""

    def __init__(
        self,
        *,
        service_name: str,
        enabled: bool = True,
        otlp_endpoint: str | None = None,
        otlp_headers: Mapping[str, str] | None = None,
        resource_attributes: Mapping[str, Any] | None = None,
        span_processors: Iterable[SpanProcessor] = (),
    ) -> None:
        self._provider: TracerProvider | None
        if not enabled:
            self._provider = None
            self._tracer = NoOpTracerProvider().get_tracer("ai-evalops-platform")
            return

        attributes: dict[str, Any] = {SERVICE_NAME: service_name}
        if resource_attributes is not None:
            attributes.update(resource_attributes)
        provider = TracerProvider(resource=Resource.create(attributes))
        for processor in span_processors:
            provider.add_span_processor(processor)
        if otlp_endpoint is not None:
            exporter = OTLPSpanExporter(
                endpoint=otlp_endpoint,
                headers=None if otlp_headers is None else dict(otlp_headers),
            )
            provider.add_span_processor(BatchSpanProcessor(exporter))
        self._provider = provider
        self._tracer = provider.get_tracer("ai-evalops-platform")

    def start_as_current_span(
        self,
        name: str,
        *,
        attributes: Mapping[str, Any] | None = None,
        context: Context | None = None,
        links: Sequence[Link] | None = None,
    ) -> AbstractContextManager[Span]:
        return self._tracer.start_as_current_span(
            name,
            attributes=attributes,
            context=context,
            links=links,
        )

    def current_trace_id(self) -> str | None:
        span_context = trace.get_current_span().get_span_context()
        if not span_context.is_valid:
            return None
        return f"{span_context.trace_id:032x}"

    def capture_traceparent(self) -> str | None:
        span_context = trace.get_current_span().get_span_context()
        if not span_context.is_valid:
            return None
        carrier: dict[str, str] = {}
        try:
            TraceContextTextMapPropagator().inject(carrier=carrier)
        except Exception:
            return None
        return carrier.get("traceparent")

    def links_from_traceparent(self, traceparent: str | None) -> tuple[Link, ...]:
        if traceparent is None:
            return ()
        try:
            context = TraceContextTextMapPropagator().extract(carrier={"traceparent": traceparent})
            span_context = trace.get_current_span(context).get_span_context()
        except Exception:
            return ()
        if not span_context.is_valid:
            return ()
        return (Link(span_context),)

    def extract_context(self, carrier: CarrierT) -> Context:
        return TraceContextTextMapPropagator().extract(carrier=carrier)

    def shutdown(self) -> None:
        if self._provider is not None:
            self._provider.shutdown()


def parse_otlp_headers(value: str | None) -> dict[str, str] | None:
    if value is None or not value.strip():
        return None
    headers: dict[str, str] = {}
    for item in value.split(","):
        key, separator, header_value = item.partition("=")
        if not separator or not key.strip():
            raise ValueError("OTLP headers must use comma-separated key=value entries")
        headers[key.strip()] = header_value.strip()
    return headers

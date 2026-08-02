from uuid import UUID

from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.core.telemetry import Telemetry
from app.domain.enums import JobStatus, RunStatus
from app.events.models import ProgressEvent
from app.jobs.reaper import ReapedJob
from app.observability.metrics import PlatformMetrics
from app.workers.runtime import handle_reaped_job, run_reaper_iteration

TENANT_ID = UUID("00000000-0000-0000-0000-000000000201")
RUN_ID = UUID("00000000-0000-0000-0000-000000000601")
JOB_ID = UUID("00000000-0000-0000-0000-000000000701")
ATTEMPT_ID = UUID("00000000-0000-0000-0000-000000000801")


class EmptyReaper:
    async def reap(self, *, limit: int = 100) -> tuple[()]:
        assert limit == 17
        return ()


async def test_reaper_iteration_observes_database_operation_duration() -> None:
    metrics = PlatformMetrics()

    reaped = await run_reaper_iteration(EmptyReaper(), metrics=metrics, limit=17)

    assert reaped == ()
    assert 'db_operation_duration_seconds_count{operation="reaper"} 1.0' in metrics.render().decode(
        "utf-8"
    )


async def test_handle_reaped_job_emits_linked_span_and_terminal_events() -> None:
    exporter = InMemorySpanExporter()
    telemetry = Telemetry(
        service_name="evalops-reaper-test",
        span_processors=(SimpleSpanProcessor(exporter),),
    )
    with telemetry.start_as_current_span("run.create") as origin_span:
        origin_context = origin_span.get_span_context()
        origin_traceparent = telemetry.capture_traceparent()
    assert origin_traceparent is not None
    item = ReapedJob(
        job_id=JOB_ID,
        run_id=RUN_ID,
        tenant_id=TENANT_ID,
        previous_worker="worker-1",
        action="failed",
        status=JobStatus.FAILED,
        next_attempt_at=None,
        attempt_id=ATTEMPT_ID,
        attempt_number=2,
        origin_traceparent=origin_traceparent,
        run_status=RunStatus.FAILED,
    )
    metrics = PlatformMetrics()

    class ForbiddenPublisher:
        def __init__(self) -> None:
            self.events: list[ProgressEvent] = []

        async def publish(self, event: ProgressEvent) -> bool:
            self.events.append(event)
            return True

    publisher = ForbiddenPublisher()

    await handle_reaped_job(
        item,
        metrics=metrics,
        telemetry=telemetry,
        event_publisher=publisher,
    )

    assert publisher.events == []
    spans = exporter.get_finished_spans()
    recovered = next(span for span in spans if span.name == "reaper.job.recovered")
    assert recovered.parent is None
    assert recovered.context.trace_id != origin_context.trace_id
    assert len(recovered.links) == 1
    assert recovered.links[0].context.trace_id == origin_context.trace_id
    assert recovered.links[0].context.span_id == origin_context.span_id
    assert recovered.attributes is not None
    assert recovered.attributes["attempt.number"] == 2
    assert not [span for span in spans if span.name == "progress.publish"]

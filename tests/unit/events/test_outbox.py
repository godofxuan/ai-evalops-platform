import asyncio
from datetime import UTC, datetime
from uuid import UUID

from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy.dialects import postgresql

from app.core.telemetry import Telemetry
from app.events.models import EventType, ProgressEvent
from app.events.outbox import (
    ClaimedOutboxEvent,
    OutboxDispatcher,
    OutboxDispatchResult,
    build_claim_outbox_statement,
    enqueue_progress_event,
    outbox_retry_delay_seconds,
    run_outbox_dispatch_loop,
)
from app.persistence.orm_models import ProgressEventOutbox

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)
TENANT_ID = UUID("00000000-0000-0000-0000-000000000201")
RUN_ID = UUID("00000000-0000-0000-0000-000000000601")
EVENT_ID = UUID("00000000-0000-0000-0000-000000000901")


class RecordingSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, value: object) -> None:
        self.added.append(value)


def _event() -> ProgressEvent:
    return ProgressEvent(
        event_id=EVENT_ID,
        event_type=EventType.JOB_PROGRESS,
        run_id=RUN_ID,
        tenant_id=TENANT_ID,
        timestamp=NOW,
        payload={"job_id": "job-1", "status": "running"},
    )


class RecordingStore:
    def __init__(self, messages: tuple[ClaimedOutboxEvent, ...]) -> None:
        self.messages = messages
        self.claim_limits: list[int] = []
        self.published: list[UUID] = []
        self.retries: list[tuple[UUID, str, float]] = []

    async def claim_batch(self, *, limit: int) -> tuple[ClaimedOutboxEvent, ...]:
        self.claim_limits.append(limit)
        messages, self.messages = self.messages, ()
        return messages

    async def mark_published(self, *, event_id: UUID) -> bool:
        self.published.append(event_id)
        return True

    async def reschedule(
        self,
        *,
        event_id: UUID,
        error_code: str,
        delay_seconds: float,
    ) -> bool:
        self.retries.append((event_id, error_code, delay_seconds))
        return True


class RecordingPublisher:
    def __init__(self, *, result: bool = True, error: BaseException | None = None) -> None:
        self.result = result
        self.error = error
        self.events: list[ProgressEvent] = []

    async def publish(self, event: ProgressEvent) -> bool:
        self.events.append(event)
        if self.error is not None:
            raise self.error
        return self.result


def test_enqueue_progress_event_adds_exact_durable_row_to_callers_session() -> None:
    session = RecordingSession()

    event = enqueue_progress_event(
        session,  # type: ignore[arg-type]
        event_type=EventType.JOB_PROGRESS,
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        timestamp=NOW,
        payload={"job_id": "job-1", "status": "running"},
        event_id=EVENT_ID,
    )

    assert event == _event()
    assert len(session.added) == 1
    row = session.added[0]
    assert isinstance(row, ProgressEventOutbox)
    assert (
        row.id,
        row.tenant_id,
        row.run_id,
        row.event_type,
        row.payload_json,
        row.occurred_at,
        row.available_at,
        row.attempt_count,
    ) == (
        EVENT_ID,
        TENANT_ID,
        RUN_ID,
        "job_progress",
        {"job_id": "job-1", "status": "running"},
        NOW,
        NOW,
        0,
    )


def test_outbox_claim_statement_is_due_ordered_and_skip_locked() -> None:
    sql = str(
        build_claim_outbox_statement(now=NOW, limit=25).compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "progress_event_outbox.published_at IS NULL" in sql
    assert "progress_event_outbox.available_at <=" in sql
    assert "progress_event_outbox.lease_expires_at IS NULL" in sql
    assert "progress_event_outbox.lease_expires_at <=" in sql
    assert "ORDER BY progress_event_outbox.available_at ASC" in sql
    assert "FOR UPDATE OF progress_event_outbox SKIP LOCKED" in sql
    assert "LIMIT 25" in sql


async def test_dispatcher_publishes_original_event_id_then_fenced_acknowledges() -> None:
    store = RecordingStore((ClaimedOutboxEvent(event=_event(), attempt_count=1),))
    publisher = RecordingPublisher()
    exporter = InMemorySpanExporter()
    telemetry = Telemetry(
        service_name="evalops-outbox-test",
        span_processors=(SimpleSpanProcessor(exporter),),
    )
    dispatcher = OutboxDispatcher(
        store=store,
        publisher=publisher,
        publish_timeout_seconds=1,
        retry_base_seconds=2,
        retry_max_seconds=10,
        telemetry=telemetry,
    )

    result = await dispatcher.dispatch_once(limit=10)

    assert result == OutboxDispatchResult(
        claimed=1,
        published=1,
        retry_scheduled=0,
        lease_lost=0,
    )
    assert publisher.events == [_event()]
    assert store.published == [EVENT_ID]
    assert store.retries == []
    span = next(span for span in exporter.get_finished_spans() if span.name == "progress.publish")
    assert span.attributes is not None
    assert span.attributes["tenant.id"] == str(TENANT_ID)
    assert span.attributes["run.id"] == str(RUN_ID)
    assert span.attributes["event.type"] == "job_progress"


async def test_dispatcher_reschedules_failed_publish_without_acknowledging() -> None:
    store = RecordingStore((ClaimedOutboxEvent(event=_event(), attempt_count=1),))
    publisher = RecordingPublisher(result=False)
    dispatcher = OutboxDispatcher(
        store=store,
        publisher=publisher,
        publish_timeout_seconds=1,
        retry_base_seconds=2,
        retry_max_seconds=10,
    )

    result = await dispatcher.dispatch_once(limit=10)

    assert result == OutboxDispatchResult(
        claimed=1,
        published=0,
        retry_scheduled=1,
        lease_lost=0,
    )
    assert store.published == []
    assert store.retries == [(EVENT_ID, "publish_returned_false", 2)]


async def test_dispatcher_records_only_exception_type_and_bounds_timeout() -> None:
    class HangingPublisher:
        async def publish(self, _event: ProgressEvent) -> bool:
            await asyncio.Event().wait()
            return True

    store = RecordingStore((ClaimedOutboxEvent(event=_event(), attempt_count=3),))
    dispatcher = OutboxDispatcher(
        store=store,
        publisher=HangingPublisher(),
        publish_timeout_seconds=0.01,
        retry_base_seconds=2,
        retry_max_seconds=5,
    )

    result = await dispatcher.dispatch_once(limit=1)

    assert result.retry_scheduled == 1
    assert store.published == []
    assert store.retries == [(EVENT_ID, "TimeoutError", 5)]


def test_outbox_retry_delay_is_exponential_and_bounded() -> None:
    assert [
        outbox_retry_delay_seconds(
            attempt_count=attempt,
            base_seconds=2,
            max_seconds=5,
        )
        for attempt in (1, 2, 3, 100)
    ] == [2, 4, 5, 5]


async def test_dispatch_loop_uses_bounded_batch_and_stops_cooperatively() -> None:
    stop_requested = asyncio.Event()

    class OneShotDispatcher:
        def __init__(self) -> None:
            self.limits: list[int] = []

        async def dispatch_once(self, *, limit: int) -> OutboxDispatchResult:
            self.limits.append(limit)
            stop_requested.set()
            return OutboxDispatchResult(0, 0, 0, 0)

    dispatcher = OneShotDispatcher()

    await run_outbox_dispatch_loop(
        dispatcher,  # type: ignore[arg-type]
        stop_requested=stop_requested,
        poll_seconds=0.01,
        batch_size=37,
    )

    assert dispatcher.limits == [37]


async def test_dispatch_loop_logs_only_error_type_then_recovers() -> None:
    stop_requested = asyncio.Event()

    class FlappingDispatcher:
        def __init__(self) -> None:
            self.calls = 0

        async def dispatch_once(self, *, limit: int) -> OutboxDispatchResult:
            assert limit == 5
            self.calls += 1
            if self.calls == 1:
                raise ConnectionError("database-secret-must-not-be-logged")
            stop_requested.set()
            return OutboxDispatchResult(0, 0, 0, 0)

    class RecordingLogger:
        def __init__(self) -> None:
            self.errors: list[tuple[str, dict[str, object]]] = []

        def error(self, event: str, **values: object) -> None:
            self.errors.append((event, values))

        def info(self, event: str, **values: object) -> None:
            del event, values

    dispatcher = FlappingDispatcher()
    logger = RecordingLogger()

    await run_outbox_dispatch_loop(
        dispatcher,  # type: ignore[arg-type]
        stop_requested=stop_requested,
        poll_seconds=0.001,
        batch_size=5,
        logger=logger,  # type: ignore[arg-type]
    )

    assert dispatcher.calls == 2
    assert logger.errors == [
        ("outbox_dispatch_iteration_failed", {"error_type": "ConnectionError"})
    ]

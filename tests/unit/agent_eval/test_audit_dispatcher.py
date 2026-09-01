import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.dialects import postgresql

from app.agent_eval.audit_dispatcher import (
    AuditBacklog,
    AuditDispatcher,
    AuditDispatchResult,
    ClaimedAudit,
    audit_retry_delay_seconds,
    build_claim_audit_statement,
    run_audit_dispatch_loop,
)
from app.observability.metrics import PlatformMetrics

NOW = datetime(2026, 8, 22, tzinfo=UTC)
OUTBOX_ID = UUID("00000000-0000-0000-0000-000000000101")
TENANT_ID = UUID("00000000-0000-0000-0000-000000000102")
API_KEY_ID = UUID("00000000-0000-0000-0000-000000000103")


class FixedClock:
    def now(self) -> datetime:
        return NOW


def _message(*, attempt_count: int = 1, max_attempts: int = 8) -> ClaimedAudit:
    return ClaimedAudit(
        outbox_id=OUTBOX_ID,
        tenant_id=TENANT_ID,
        actor_id=str(API_KEY_ID),
        api_key_id=API_KEY_ID,
        operation="submit_evaluation",
        idempotency_key="idempotency:call-1",
        trace_id="1" * 32,
        outcome_status="succeeded",
        attempt_count=attempt_count,
        max_attempts=max_attempts,
        lease_version=3,
        created_at=NOW - timedelta(seconds=12.5),
    )


class RecordingStore:
    def __init__(
        self,
        claimed: tuple[ClaimedAudit, ...],
        *,
        acknowledge: bool = True,
        failure_result: str = "retry_scheduled",
    ) -> None:
        self.claimed = claimed
        self.acknowledge_result = acknowledge
        self.failure_result = failure_result
        self.limits: list[int] = []
        self.acknowledged: list[ClaimedAudit] = []
        self.failures: list[tuple[ClaimedAudit, str, float]] = []

    async def claim_batch(self, *, limit: int) -> tuple[ClaimedAudit, ...]:
        self.limits.append(limit)
        return self.claimed

    async def read_backlog(self) -> AuditBacklog:
        return AuditBacklog(
            pending=1 if self.failure_result == "retry_scheduled" else 0,
            oldest_pending_created_at=NOW,
            dead_letter_count=1 if self.failure_result == "dead_lettered" else 0,
        )

    async def acknowledge(self, message: ClaimedAudit) -> bool:
        self.acknowledged.append(message)
        return self.acknowledge_result

    async def record_failure(
        self,
        message: ClaimedAudit,
        *,
        error_code: str,
        delay_seconds: float,
    ) -> str:
        self.failures.append((message, error_code, delay_seconds))
        return self.failure_result


class RecordingSink:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.delivered: list[ClaimedAudit] = []

    async def deliver(self, message: ClaimedAudit) -> None:
        self.delivered.append(message)
        if self.error is not None:
            raise self.error


def _dispatcher(
    store: RecordingStore,
    sink: RecordingSink,
    *,
    metrics: PlatformMetrics | None = None,
) -> AuditDispatcher:
    return AuditDispatcher(
        store=store,  # type: ignore[arg-type]
        sink=sink,
        delivery_timeout_seconds=1,
        retry_base_seconds=2,
        retry_max_seconds=5,
        metrics=metrics,
        clock=FixedClock(),
    )


def test_claim_statement_is_global_due_ordered_and_skip_locked() -> None:
    sql = str(
        build_claim_audit_statement(now=NOW, limit=25).compile(
            dialect=postgresql.dialect(),  # type: ignore[no-untyped-call]
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "mcp_audit_outbox.delivery_status = 'PENDING'" in sql
    assert "mcp_audit_outbox.outcome_status IS NOT NULL" in sql
    assert "mcp_audit_outbox.available_at <=" in sql
    assert "mcp_audit_outbox.lease_expires_at IS NULL" in sql
    assert "mcp_audit_outbox.lease_expires_at <=" in sql
    assert "ORDER BY mcp_audit_outbox.available_at ASC" in sql
    assert "FOR UPDATE OF mcp_audit_outbox SKIP LOCKED" in sql
    assert "LIMIT 25" in sql


def test_retry_delay_is_exponential_and_bounded() -> None:
    assert [
        audit_retry_delay_seconds(attempt_count=attempt, base_seconds=2, max_seconds=5)
        for attempt in (1, 2, 3, 100)
    ] == [2, 4, 5, 5]


async def test_successful_delivery_is_fenced_and_acknowledged() -> None:
    message = _message()
    store = RecordingStore((message,))
    sink = RecordingSink()

    result = await _dispatcher(store, sink).dispatch_once(limit=7)

    assert result == AuditDispatchResult(1, 1, 0, 0, 0)
    assert store.limits == [7]
    assert sink.delivered == [message]
    assert store.acknowledged == [message]
    assert store.failures == []


async def test_successful_delivery_records_end_to_end_audit_latency() -> None:
    message = _message()
    store = RecordingStore((message,))
    metrics = PlatformMetrics()

    result = await _dispatcher(store, RecordingSink(), metrics=metrics).dispatch_once(limit=1)

    assert result.delivered == 1
    rendered = metrics.render().decode()
    assert "mcp_audit_delivery_latency_seconds_count 1.0" in rendered
    assert "mcp_audit_delivery_latency_seconds_sum 12.5" in rendered


async def test_sink_failure_schedules_bounded_retry_and_records_metric() -> None:
    message = _message(attempt_count=3)
    store = RecordingStore((message,))
    sink = RecordingSink(ConnectionError("secret must not be logged"))
    metrics = PlatformMetrics()

    result = await _dispatcher(store, sink, metrics=metrics).dispatch_once(limit=1)

    assert result == AuditDispatchResult(1, 0, 1, 0, 0)
    assert store.failures == [(message, "ConnectionError", 5)]
    rendered = metrics.render().decode()
    assert "mcp_audit_delivery_failures_total 1.0" in rendered
    assert "mcp_audit_pending 1.0" in rendered


async def test_max_attempt_failure_moves_to_dead_letter() -> None:
    message = _message(attempt_count=8, max_attempts=8)
    store = RecordingStore((message,), failure_result="dead_lettered")
    sink = RecordingSink(RuntimeError("sink unavailable"))
    metrics = PlatformMetrics()

    result = await _dispatcher(store, sink, metrics=metrics).dispatch_once(limit=1)

    assert result == AuditDispatchResult(1, 0, 0, 1, 0)
    rendered = metrics.render().decode()
    assert "mcp_audit_dead_letters_total 1.0" in rendered
    assert "mcp_audit_dead_letter_count 1.0" in rendered


async def test_sink_success_with_lost_ack_is_safe_to_retry() -> None:
    message = _message()
    store = RecordingStore((message,), acknowledge=False)
    sink = RecordingSink()

    result = await _dispatcher(store, sink).dispatch_once(limit=1)

    assert result == AuditDispatchResult(1, 0, 0, 0, 1)
    assert sink.delivered == [message]


async def test_dispatch_loop_uses_bounded_batch_and_stops_cooperatively() -> None:
    stop_requested = asyncio.Event()

    class OneShotDispatcher:
        def __init__(self) -> None:
            self.limits: list[int] = []

        async def dispatch_once(self, *, limit: int) -> AuditDispatchResult:
            self.limits.append(limit)
            stop_requested.set()
            return AuditDispatchResult(0, 0, 0, 0, 0)

    dispatcher = OneShotDispatcher()
    await run_audit_dispatch_loop(
        dispatcher,
        stop_requested=stop_requested,
        poll_seconds=0.01,
        batch_size=37,
    )

    assert dispatcher.limits == [37]

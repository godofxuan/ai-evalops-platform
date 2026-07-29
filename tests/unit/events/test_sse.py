import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID

from app.auth.principals import Principal
from app.events.models import EventType, ProgressEvent
from app.events.sse import RunEventStream
from app.observability.metrics import PlatformMetrics
from app.runs.schemas import RunRead

TENANT_ID = UUID("00000000-0000-0000-0000-000000000201")
RUN_ID = UUID("00000000-0000-0000-0000-000000000601")
DATASET_VERSION_ID = UUID("00000000-0000-0000-0000-000000000401")
PRINCIPAL = Principal(
    tenant_id=TENANT_ID,
    api_key_id=UUID("00000000-0000-0000-0000-000000000101"),
    key_prefix="evk_001122334455",
)


def _snapshot(*, succeeded: int = 0) -> RunRead:
    return RunRead(
        id=RUN_ID,
        dataset_version_id=DATASET_VERSION_ID,
        status="running",
        total_jobs=2,
        succeeded_jobs=succeeded,
        failed_jobs=0,
        cancelled_jobs=0,
        created_at=datetime(2026, 7, 29, 12, 0, tzinfo=UTC),
        started_at=datetime(2026, 7, 29, 12, 1, tzinfo=UTC),
        finished_at=None,
    )


class SnapshotService:
    def __init__(self, snapshots: list[RunRead]) -> None:
        self.snapshots = snapshots
        self.calls: list[tuple[Principal, UUID]] = []

    async def get_run(self, *, principal: Principal, run_id: UUID) -> RunRead:
        self.calls.append((principal, run_id))
        if len(self.snapshots) > 1:
            return self.snapshots.pop(0)
        return self.snapshots[0]


class FakeSubscriber:
    def __init__(
        self,
        values: list[ProgressEvent | None],
        *,
        failure: Exception | None = None,
    ) -> None:
        self.values = values
        self.failure = failure
        self.closed = False

    async def listen(
        self,
        *,
        tenant_id: UUID,
        run_id: UUID,
    ) -> AsyncIterator[ProgressEvent | None]:
        assert tenant_id == TENANT_ID
        assert run_id == RUN_ID
        try:
            for value in self.values:
                yield value
            if self.failure is not None:
                raise self.failure
        finally:
            self.closed = True


def _decode(chunk: str) -> tuple[str, dict[str, object]]:
    lines = chunk.strip().splitlines()
    event_name = lines[1].removeprefix("event: ")
    payload = json.loads(lines[2].removeprefix("data: "))
    return event_name, payload


async def _no_sleep(seconds: float) -> None:
    assert seconds == 0.5


async def test_stream_sends_database_snapshot_before_live_event_and_heartbeat() -> None:
    live = ProgressEvent(
        event_type=EventType.JOB_PROGRESS,
        run_id=RUN_ID,
        tenant_id=TENANT_ID,
        timestamp=datetime(2026, 7, 29, 12, 2, tzinfo=UTC),
        payload={"completed": 1},
    )
    snapshots = SnapshotService([_snapshot()])
    subscriber = FakeSubscriber([live, None])
    service = RunEventStream(
        run_service=snapshots,
        subscriber=subscriber,
        fallback_poll_seconds=0.5,
        sleep=_no_sleep,
    )

    stream = await service.open(principal=PRINCIPAL, run_id=RUN_ID)
    first = _decode(await anext(stream))
    second = _decode(await anext(stream))
    third = _decode(await anext(stream))
    await stream.aclose()

    assert first[0] == "snapshot"
    assert first[1]["payload"]["succeeded_jobs"] == 0
    assert second[0] == "job_progress"
    assert third[0] == "heartbeat"
    assert snapshots.calls[0] == (PRINCIPAL, RUN_ID)
    assert subscriber.closed is True


async def test_stream_connection_metric_is_released_when_client_disconnects() -> None:
    metrics = PlatformMetrics()
    service = RunEventStream(
        run_service=SnapshotService([_snapshot()]),
        subscriber=FakeSubscriber([None]),
        fallback_poll_seconds=0.5,
        sleep=_no_sleep,
        metrics=metrics,
    )

    stream = await service.open(principal=PRINCIPAL, run_id=RUN_ID)
    await anext(stream)
    assert "sse_connections 1.0" in metrics.render().decode("utf-8")

    await stream.aclose()

    assert "sse_connections 0.0" in metrics.render().decode("utf-8")


async def test_redis_failure_degrades_to_changed_postgresql_snapshot() -> None:
    snapshots = SnapshotService([_snapshot(), _snapshot(succeeded=1)])
    service = RunEventStream(
        run_service=snapshots,
        subscriber=FakeSubscriber([], failure=ConnectionError("redis down")),
        fallback_poll_seconds=0.5,
        sleep=_no_sleep,
    )

    stream = await service.open(principal=PRINCIPAL, run_id=RUN_ID)
    assert _decode(await anext(stream))[0] == "snapshot"
    degraded = _decode(await anext(stream))
    await stream.aclose()

    assert degraded[0] == "snapshot"
    assert degraded[1]["payload"]["succeeded_jobs"] == 1

from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.events.models import EventType, ProgressEvent
from app.events.publisher import RedisEventPublisher
from app.jobs.retry_policy import classify_failure
from app.observability.metrics import PlatformMetrics
from app.targets.base import TargetHTTPError, TargetTimeoutError
from app.workers.runtime import WorkerIterationStatus, run_worker_iteration

TENANT_ID = UUID("00000000-0000-0000-0000-000000000201")
RUN_ID = UUID("00000000-0000-0000-0000-000000000601")


class FlappingRedis:
    def __init__(self) -> None:
        self.calls = 0

    async def publish(self, channel: str, payload: str) -> int:
        del channel, payload
        self.calls += 1
        if self.calls == 1:
            raise ConnectionError("injected Redis outage")
        return 1


def _event() -> ProgressEvent:
    return ProgressEvent(
        event_type=EventType.JOB_PROGRESS,
        run_id=RUN_ID,
        tenant_id=TENANT_ID,
        timestamp=datetime(2026, 7, 29, 12, 0, tzinfo=UTC),
        payload={"status": "running"},
    )


async def test_redis_recovery_resumes_new_publications_without_replaying_old_event() -> None:
    redis = FlappingRedis()
    metrics = PlatformMetrics()
    publisher = RedisEventPublisher(redis, metrics=metrics)

    assert await publisher.publish(_event()) is False
    assert await publisher.publish(_event()) is True

    assert redis.calls == 2
    assert "redis_publish_failures_total 1.0" in metrics.render().decode("utf-8")


@pytest.mark.parametrize(
    ("error", "expected_code"),
    [
        (TargetTimeoutError(), "target_timeout"),
        (TargetHTTPError(429), "target_http_429"),
        (TargetHTTPError(500), "target_http_500"),
    ],
)
def test_upstream_timeout_rate_limit_and_server_error_remain_retryable(
    error: BaseException,
    expected_code: str,
) -> None:
    classification = classify_failure(error)

    assert classification.retryable is True
    assert classification.error_code == expected_code


class TransientDatabaseFailureWorker:
    async def process_one(self, *, worker_id: str) -> bool:
        assert worker_id == "worker-db-fault"
        raise ConnectionError("injected PostgreSQL disconnect")


class RecordingLogger:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def warning(self, event: str, **values: object) -> None:
        self.events.append((event, values))

    def error(self, event: str, **values: object) -> None:
        self.events.append((event, values))


async def test_transient_database_iteration_failure_is_logged_and_loop_can_continue() -> None:
    logger = RecordingLogger()

    outcome = await run_worker_iteration(
        TransientDatabaseFailureWorker(),
        worker_id="worker-db-fault",
        logger=logger,
    )

    assert outcome.status is WorkerIterationStatus.DATABASE_FAILURE
    assert outcome.error_type == "ConnectionError"
    assert logger.events == [("worker_iteration_failed", {"error_type": "ConnectionError"})]

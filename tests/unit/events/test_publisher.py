import json
from datetime import UTC, datetime
from uuid import UUID

from app.events.models import EventType, ProgressEvent
from app.events.publisher import RedisEventPublisher

TENANT_ID = UUID("00000000-0000-0000-0000-000000000201")
RUN_ID = UUID("00000000-0000-0000-0000-000000000601")


class RecordingRedis:
    def __init__(self) -> None:
        self.published: tuple[str, str] | None = None

    async def publish(self, channel: str, payload: str) -> int:
        self.published = (channel, payload)
        return 2


class BrokenRedis:
    async def publish(self, channel: str, payload: str) -> int:
        del channel, payload
        raise ConnectionError("redis password and host must never escape")


def _event() -> ProgressEvent:
    return ProgressEvent(
        event_type=EventType.RUN_STARTED,
        run_id=RUN_ID,
        tenant_id=TENANT_ID,
        timestamp=datetime(2026, 7, 29, 12, 0, tzinfo=UTC),
        payload={"status": "running"},
    )


async def test_publisher_uses_exact_tenant_run_channel() -> None:
    redis = RecordingRedis()
    publisher = RedisEventPublisher(redis)

    assert await publisher.publish(_event()) is True
    assert redis.published is not None
    channel, payload = redis.published
    assert channel == f"evalops:{TENANT_ID}:run:{RUN_ID}"
    assert json.loads(payload)["tenant_id"] == str(TENANT_ID)


async def test_redis_failure_is_best_effort_and_does_not_escape() -> None:
    publisher = RedisEventPublisher(BrokenRedis())

    assert await publisher.publish(_event()) is False

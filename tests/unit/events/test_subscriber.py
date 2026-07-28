from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID

from app.events.models import EventType, ProgressEvent
from app.events.subscriber import RedisEventSubscriber

TENANT_ID = UUID("00000000-0000-0000-0000-000000000201")
OTHER_TENANT_ID = UUID("00000000-0000-0000-0000-000000000202")
RUN_ID = UUID("00000000-0000-0000-0000-000000000601")
EVENT_ID = UUID("00000000-0000-0000-0000-000000000901")


class FakePubSub:
    def __init__(self, messages: list[dict[str, object] | None]) -> None:
        self.messages = messages
        self.subscribed: str | None = None
        self.closed = False
        self.unsubscribed = False

    async def subscribe(self, channel: str) -> None:
        self.subscribed = channel

    async def get_message(
        self,
        *,
        ignore_subscribe_messages: bool,
        timeout: float,  # noqa: ASYNC109
    ) -> dict[str, object] | None:
        assert ignore_subscribe_messages is True
        assert timeout == 0.25
        return self.messages.pop(0)

    async def unsubscribe(self, channel: str) -> None:
        assert channel == self.subscribed
        self.unsubscribed = True

    async def aclose(self) -> None:
        self.closed = True


class FakeRedis:
    def __init__(self, pubsub: FakePubSub) -> None:
        self._pubsub = pubsub

    def pubsub(self, *, ignore_subscribe_messages: bool) -> FakePubSub:
        assert ignore_subscribe_messages is True
        return self._pubsub


def _event(tenant_id: UUID) -> ProgressEvent:
    return ProgressEvent(
        event_id=EVENT_ID,
        event_type=EventType.JOB_PROGRESS,
        run_id=RUN_ID,
        tenant_id=tenant_id,
        timestamp=datetime(2026, 7, 29, 12, 0, tzinfo=UTC),
        payload={"completed": 1},
    )


async def test_subscriber_filters_malformed_and_cross_tenant_messages_and_closes() -> None:
    pubsub = FakePubSub(
        [
            {"type": "message", "data": "not-json"},
            {"type": "message", "data": _event(OTHER_TENANT_ID).model_dump_json()},
            {"type": "message", "data": _event(TENANT_ID).model_dump_json()},
            None,
        ]
    )
    subscriber = RedisEventSubscriber(FakeRedis(pubsub), poll_timeout_seconds=0.25)
    stream: AsyncIterator[ProgressEvent | None] = subscriber.listen(
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
    )

    assert await anext(stream) == _event(TENANT_ID)
    assert await anext(stream) is None
    await stream.aclose()

    assert pubsub.subscribed == f"evalops:{TENANT_ID}:run:{RUN_ID}"
    assert pubsub.unsubscribed is True
    assert pubsub.closed is True

from collections.abc import AsyncGenerator
from contextlib import suppress
from uuid import UUID

from pydantic import ValidationError
from redis.asyncio import Redis

from app.core.logging import get_logger
from app.events.models import ProgressEvent, run_event_channel


class RedisEventSubscriber:
    def __init__(
        self,
        redis_client: Redis,
        *,
        poll_timeout_seconds: float,
    ) -> None:
        if poll_timeout_seconds <= 0:
            raise ValueError("subscriber poll timeout must be positive")
        self._redis = redis_client
        self._poll_timeout_seconds = poll_timeout_seconds
        self._logger = get_logger(__name__)

    async def listen(
        self,
        *,
        tenant_id: UUID,
        run_id: UUID,
    ) -> AsyncGenerator[ProgressEvent | None]:
        channel = run_event_channel(tenant_id=tenant_id, run_id=run_id)
        pubsub = self._redis.pubsub(ignore_subscribe_messages=True)
        try:
            await pubsub.subscribe(channel)
            while True:
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=self._poll_timeout_seconds,
                )
                if message is None:
                    yield None
                    continue
                if message.get("type") != "message":
                    continue
                data = message.get("data")
                if not isinstance(data, (str, bytes)):
                    continue
                try:
                    event = ProgressEvent.model_validate_json(data)
                except (ValidationError, ValueError):
                    self._logger.warning(
                        "invalid_progress_event_discarded",
                        tenant_id=str(tenant_id),
                        run_id=str(run_id),
                    )
                    continue
                if event.tenant_id != tenant_id or event.run_id != run_id:
                    self._logger.warning(
                        "misrouted_progress_event_discarded",
                        tenant_id=str(tenant_id),
                        run_id=str(run_id),
                    )
                    continue
                yield event
        finally:
            with suppress(Exception):
                await pubsub.unsubscribe(channel)
            with suppress(Exception):
                await pubsub.aclose()  # type: ignore[no-untyped-call]

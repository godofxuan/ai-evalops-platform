from typing import Protocol, cast

from redis.asyncio import Redis

from app.core.logging import get_logger
from app.events.models import ProgressEvent, run_event_channel
from app.observability.metrics import PlatformMetrics


class EventPublisher(Protocol):
    async def publish(self, event: ProgressEvent) -> bool:
        """Publish an ephemeral notification without changing durable state."""


class RedisEventPublisher:
    def __init__(
        self,
        redis_client: Redis,
        *,
        metrics: PlatformMetrics | None = None,
    ) -> None:
        self._redis = redis_client
        self._logger = get_logger(__name__)
        self._metrics = metrics

    async def publish(self, event: ProgressEvent) -> bool:
        channel = run_event_channel(
            tenant_id=event.tenant_id,
            run_id=event.run_id,
        )
        try:
            delivered = await self._redis.publish(channel, event.model_dump_json())
        except Exception as error:
            if self._metrics is not None:
                self._metrics.record_redis_publish_failure()
            self._logger.warning(
                "progress_event_publish_failed",
                event_type=event.event_type.value,
                tenant_id=str(event.tenant_id),
                run_id=str(event.run_id),
                error_type=type(error).__name__,
            )
            return False
        return cast(int, delivered) >= 0

import asyncio
import json
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from contextlib import aclosing
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from app.auth.principals import Principal
from app.core.logging import get_logger
from app.core.telemetry import Telemetry
from app.events.models import EventType, ProgressEvent
from app.observability.metrics import PlatformMetrics
from app.runs.schemas import RunRead

type Sleep = Callable[[float], Awaitable[None]]


class RunSnapshotService(Protocol):
    async def get_run(
        self,
        *,
        principal: Principal,
        run_id: UUID,
    ) -> RunRead:
        """Return a tenant-scoped durable Run snapshot."""


class EventSubscriber(Protocol):
    def listen(
        self,
        *,
        tenant_id: UUID,
        run_id: UUID,
    ) -> AsyncGenerator[ProgressEvent | None]:
        """Yield live events and None heartbeat ticks."""


class RunEventStreamService(Protocol):
    async def open(
        self,
        *,
        principal: Principal,
        run_id: UUID,
    ) -> AsyncIterator[str]:
        """Authorize before response start and return an SSE iterator."""


class RunEventStream:
    def __init__(
        self,
        *,
        run_service: RunSnapshotService,
        subscriber: EventSubscriber,
        fallback_poll_seconds: float,
        sleep: Sleep = asyncio.sleep,
        metrics: PlatformMetrics | None = None,
        telemetry: Telemetry | None = None,
    ) -> None:
        if fallback_poll_seconds <= 0:
            raise ValueError("fallback poll interval must be positive")
        self._run_service = run_service
        self._subscriber = subscriber
        self._fallback_poll_seconds = fallback_poll_seconds
        self._sleep = sleep
        self._metrics = metrics
        self._telemetry = telemetry
        self._logger = get_logger(__name__)

    async def open(
        self,
        *,
        principal: Principal,
        run_id: UUID,
    ) -> AsyncIterator[str]:
        initial = await self._run_service.get_run(
            principal=principal,
            run_id=run_id,
        )
        return self._iterate(
            principal=principal,
            run_id=run_id,
            initial=initial,
        )

    async def _iterate(
        self,
        *,
        principal: Principal,
        run_id: UUID,
        initial: RunRead,
    ) -> AsyncGenerator[str]:
        if self._metrics is not None:
            self._metrics.sse_connected()
        try:
            stream = self._stream_events(
                principal=principal,
                run_id=run_id,
                initial=initial,
            )
            if self._telemetry is None:
                async with aclosing(stream):
                    async for chunk in stream:
                        yield chunk
            else:
                with self._telemetry.start_as_current_span(
                    "sse.connection",
                    attributes={
                        "tenant.id": str(principal.tenant_id),
                        "run.id": str(run_id),
                    },
                ):
                    async with aclosing(stream):
                        async for chunk in stream:
                            yield chunk
        finally:
            if self._metrics is not None:
                self._metrics.sse_disconnected()

    async def _stream_events(
        self,
        *,
        principal: Principal,
        run_id: UUID,
        initial: RunRead,
    ) -> AsyncGenerator[str]:
        latest_snapshot = initial.model_dump_json()
        yield _encode_sse(_snapshot_event(principal=principal, snapshot=initial))
        try:
            live_stream = self._subscriber.listen(
                tenant_id=principal.tenant_id,
                run_id=run_id,
            )
            async with aclosing(live_stream):
                async for event in live_stream:
                    if event is None:
                        yield _encode_sse(
                            _heartbeat_event(
                                principal=principal,
                                run_id=run_id,
                                source="redis",
                            )
                        )
                    else:
                        yield _encode_sse(event)
            return
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._logger.warning(
                "sse_redis_degraded_to_postgresql",
                tenant_id=str(principal.tenant_id),
                run_id=str(run_id),
                error_type=type(error).__name__,
            )

        while True:
            await self._sleep(self._fallback_poll_seconds)
            snapshot = await self._run_service.get_run(
                principal=principal,
                run_id=run_id,
            )
            encoded_snapshot = snapshot.model_dump_json()
            if encoded_snapshot != latest_snapshot:
                latest_snapshot = encoded_snapshot
                yield _encode_sse(
                    _snapshot_event(
                        principal=principal,
                        snapshot=snapshot,
                    )
                )
            else:
                yield _encode_sse(
                    _heartbeat_event(
                        principal=principal,
                        run_id=run_id,
                        source="postgresql_fallback",
                    )
                )


def _snapshot_event(*, principal: Principal, snapshot: RunRead) -> ProgressEvent:
    return ProgressEvent(
        event_type=EventType.SNAPSHOT,
        run_id=snapshot.id,
        tenant_id=principal.tenant_id,
        timestamp=datetime.now(UTC),
        payload=snapshot.model_dump(mode="json"),
    )


def _heartbeat_event(
    *,
    principal: Principal,
    run_id: UUID,
    source: str,
) -> ProgressEvent:
    return ProgressEvent(
        event_type=EventType.HEARTBEAT,
        run_id=run_id,
        tenant_id=principal.tenant_id,
        timestamp=datetime.now(UTC),
        payload={"source": source},
    )


def _encode_sse(event: ProgressEvent) -> str:
    data = json.dumps(
        event.model_dump(mode="json"),
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return f"id: {event.event_id}\nevent: {event.event_type.value}\ndata: {data}\n\n"

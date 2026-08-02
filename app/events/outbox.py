import asyncio
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import Select, delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.dml import ReturningDelete

from app.core.clock import Clock, SystemClock
from app.core.logging import get_logger
from app.core.telemetry import Telemetry
from app.events.models import EventType, ProgressEvent
from app.events.publisher import EventPublisher
from app.observability.metrics import PlatformMetrics
from app.persistence.database import AsyncSessionFactory
from app.persistence.orm_models import ProgressEventOutbox


def enqueue_progress_event(
    session: AsyncSession,
    *,
    event_type: EventType,
    tenant_id: UUID,
    run_id: UUID,
    timestamp: datetime,
    payload: Mapping[str, JsonValue],
    event_id: UUID | None = None,
) -> ProgressEvent:
    """Add notification intent to the caller's existing state transaction."""
    event_values: dict[str, object] = {
        "event_type": event_type,
        "tenant_id": tenant_id,
        "run_id": run_id,
        "timestamp": timestamp,
        "payload": dict(payload),
    }
    if event_id is not None:
        event_values["event_id"] = event_id
    event = ProgressEvent.model_validate(event_values)
    session.add(
        ProgressEventOutbox(
            id=event.event_id,
            tenant_id=event.tenant_id,
            run_id=event.run_id,
            event_type=event.event_type.value,
            payload_json=event.payload,
            occurred_at=event.timestamp,
            available_at=event.timestamp,
            attempt_count=0,
        )
    )
    return event


def build_claim_outbox_statement(
    *,
    now: datetime,
    limit: int,
) -> Select[tuple[ProgressEventOutbox]]:
    if not 1 <= limit <= 1_000:
        raise ValueError("outbox claim limit must be between 1 and 1000")
    return (
        select(ProgressEventOutbox)
        .where(
            ProgressEventOutbox.published_at.is_(None),
            ProgressEventOutbox.available_at <= now,
            or_(
                ProgressEventOutbox.lease_expires_at.is_(None),
                ProgressEventOutbox.lease_expires_at <= now,
            ),
        )
        .order_by(
            ProgressEventOutbox.available_at.asc(),
            ProgressEventOutbox.created_at.asc(),
            ProgressEventOutbox.id.asc(),
        )
        .limit(limit)
        .with_for_update(of=ProgressEventOutbox, skip_locked=True)
    )


def build_cleanup_outbox_statement(
    *,
    published_before: datetime,
    limit: int,
) -> ReturningDelete[tuple[UUID]]:
    if not 1 <= limit <= 10_000:
        raise ValueError("outbox cleanup limit must be between 1 and 10000")
    candidates = (
        select(ProgressEventOutbox.id)
        .where(
            ProgressEventOutbox.published_at.is_not(None),
            ProgressEventOutbox.published_at < published_before,
        )
        .order_by(
            ProgressEventOutbox.published_at.asc(),
            ProgressEventOutbox.id.asc(),
        )
        .limit(limit)
        .with_for_update(of=ProgressEventOutbox, skip_locked=True)
        .cte("outbox_cleanup_candidates")
    )
    return (
        delete(ProgressEventOutbox)
        .where(ProgressEventOutbox.id.in_(select(candidates.c.id)))
        .returning(ProgressEventOutbox.id)
    )


class SQLAlchemyOutboxMaintenance:
    def __init__(
        self,
        session_factory: AsyncSessionFactory,
        *,
        retention_seconds: float,
        clock: Clock | None = None,
    ) -> None:
        if retention_seconds <= 0:
            raise ValueError("outbox retention_seconds must be positive")
        self._session_factory = session_factory
        self._retention_seconds = retention_seconds
        self._clock = clock or SystemClock()

    async def cleanup_once(self, *, limit: int) -> int:
        published_before = self._clock.now() - timedelta(seconds=self._retention_seconds)
        async with self._session_factory.begin() as session:
            deleted_ids = (
                (
                    await session.execute(
                        build_cleanup_outbox_statement(
                            published_before=published_before,
                            limit=limit,
                        )
                    )
                )
                .scalars()
                .all()
            )
        return len(deleted_ids)


@dataclass(frozen=True, slots=True)
class ClaimedOutboxEvent:
    event: ProgressEvent
    attempt_count: int


class OutboxStore(Protocol):
    async def claim_batch(self, *, limit: int) -> tuple[ClaimedOutboxEvent, ...]:
        """Lease a bounded batch of due unpublished events."""

    async def mark_published(self, *, event_id: UUID) -> bool:
        """Fenced acknowledgement after successful publication."""

    async def reschedule(
        self,
        *,
        event_id: UUID,
        error_code: str,
        delay_seconds: float,
    ) -> bool:
        """Release an owned event for bounded delayed retry."""


class SQLAlchemyOutboxStore:
    def __init__(
        self,
        session_factory: AsyncSessionFactory,
        *,
        dispatcher_id: str,
        lease_seconds: float,
        clock: Clock | None = None,
    ) -> None:
        if not dispatcher_id.strip() or len(dispatcher_id) > 128:
            raise ValueError("outbox dispatcher_id must be nonblank and at most 128 characters")
        if lease_seconds <= 0:
            raise ValueError("outbox lease_seconds must be positive")
        self._session_factory = session_factory
        self._dispatcher_id = dispatcher_id
        self._lease_seconds = lease_seconds
        self._clock = clock or SystemClock()

    async def claim_batch(self, *, limit: int) -> tuple[ClaimedOutboxEvent, ...]:
        now = self._clock.now()
        lease_expires_at = now + timedelta(seconds=self._lease_seconds)
        claimed: list[ClaimedOutboxEvent] = []
        async with self._session_factory.begin() as session:
            rows = (
                (await session.execute(build_claim_outbox_statement(now=now, limit=limit)))
                .scalars()
                .all()
            )
            for row in rows:
                row.lease_owner = self._dispatcher_id
                row.lease_expires_at = lease_expires_at
                row.attempt_count += 1
                claimed.append(
                    ClaimedOutboxEvent(
                        event=ProgressEvent(
                            event_id=row.id,
                            event_type=EventType(row.event_type),
                            run_id=row.run_id,
                            tenant_id=row.tenant_id,
                            timestamp=row.occurred_at,
                            payload=dict(row.payload_json),
                        ),
                        attempt_count=row.attempt_count,
                    )
                )
        return tuple(claimed)

    async def mark_published(self, *, event_id: UUID) -> bool:
        now = self._clock.now()
        async with self._session_factory.begin() as session:
            acknowledged = (
                await session.execute(
                    update(ProgressEventOutbox)
                    .where(
                        ProgressEventOutbox.id == event_id,
                        ProgressEventOutbox.published_at.is_(None),
                        ProgressEventOutbox.lease_owner == self._dispatcher_id,
                        ProgressEventOutbox.lease_expires_at.is_not(None),
                        ProgressEventOutbox.lease_expires_at > now,
                    )
                    .values(
                        published_at=now,
                        lease_owner=None,
                        lease_expires_at=None,
                        last_error_code=None,
                    )
                    .returning(ProgressEventOutbox.id)
                )
            ).scalar_one_or_none()
        return acknowledged is not None

    async def reschedule(
        self,
        *,
        event_id: UUID,
        error_code: str,
        delay_seconds: float,
    ) -> bool:
        if delay_seconds < 0:
            raise ValueError("outbox retry delay must be nonnegative")
        now = self._clock.now()
        async with self._session_factory.begin() as session:
            released = (
                await session.execute(
                    update(ProgressEventOutbox)
                    .where(
                        ProgressEventOutbox.id == event_id,
                        ProgressEventOutbox.published_at.is_(None),
                        ProgressEventOutbox.lease_owner == self._dispatcher_id,
                    )
                    .values(
                        available_at=now + timedelta(seconds=delay_seconds),
                        lease_owner=None,
                        lease_expires_at=None,
                        last_error_code=error_code[:100],
                    )
                    .returning(ProgressEventOutbox.id)
                )
            ).scalar_one_or_none()
        return released is not None


def outbox_retry_delay_seconds(
    *,
    attempt_count: int,
    base_seconds: float,
    max_seconds: float,
) -> float:
    if attempt_count < 1:
        raise ValueError("outbox attempt_count must be positive")
    if base_seconds <= 0 or max_seconds <= 0 or base_seconds > max_seconds:
        raise ValueError("outbox retry bounds are invalid")
    exponent = min(attempt_count - 1, 62)
    return min(base_seconds * (2.0**exponent), max_seconds)


@dataclass(frozen=True, slots=True)
class OutboxDispatchResult:
    claimed: int
    published: int
    retry_scheduled: int
    lease_lost: int


class OutboxDispatcher:
    def __init__(
        self,
        *,
        store: OutboxStore,
        publisher: EventPublisher,
        publish_timeout_seconds: float,
        retry_base_seconds: float,
        retry_max_seconds: float,
        telemetry: Telemetry | None = None,
        metrics: PlatformMetrics | None = None,
    ) -> None:
        if publish_timeout_seconds <= 0:
            raise ValueError("outbox publish timeout must be positive")
        outbox_retry_delay_seconds(
            attempt_count=1,
            base_seconds=retry_base_seconds,
            max_seconds=retry_max_seconds,
        )
        self._store = store
        self._publisher = publisher
        self._publish_timeout_seconds = publish_timeout_seconds
        self._retry_base_seconds = retry_base_seconds
        self._retry_max_seconds = retry_max_seconds
        self._telemetry = telemetry
        self._metrics = metrics

    async def dispatch_once(self, *, limit: int) -> OutboxDispatchResult:
        claimed = await self._store.claim_batch(limit=limit)
        if not claimed:
            return OutboxDispatchResult(0, 0, 0, 0)
        outcomes = await asyncio.gather(*(self._dispatch_one(message) for message in claimed))
        result = OutboxDispatchResult(
            claimed=len(claimed),
            published=sum(outcome == "published" for outcome in outcomes),
            retry_scheduled=sum(outcome == "retry_scheduled" for outcome in outcomes),
            lease_lost=sum(outcome == "lease_lost" for outcome in outcomes),
        )
        if self._metrics is not None:
            self._metrics.record_outbox_retry_scheduled(result.retry_scheduled)
        return result

    async def _dispatch_one(self, message: ClaimedOutboxEvent) -> str:
        error_code: str | None = None
        try:
            if self._telemetry is None:
                published = await asyncio.wait_for(
                    self._publisher.publish(message.event),
                    timeout=self._publish_timeout_seconds,
                )
            else:
                with self._telemetry.start_as_current_span(
                    "progress.publish",
                    attributes={
                        "tenant.id": str(message.event.tenant_id),
                        "run.id": str(message.event.run_id),
                        "event.type": message.event.event_type.value,
                    },
                ):
                    published = await asyncio.wait_for(
                        self._publisher.publish(message.event),
                        timeout=self._publish_timeout_seconds,
                    )
            if not published:
                error_code = "publish_returned_false"
        except Exception as error:
            error_code = type(error).__name__
        if error_code is not None:
            released = await self._store.reschedule(
                event_id=message.event.event_id,
                error_code=error_code,
                delay_seconds=outbox_retry_delay_seconds(
                    attempt_count=message.attempt_count,
                    base_seconds=self._retry_base_seconds,
                    max_seconds=self._retry_max_seconds,
                ),
            )
            return "retry_scheduled" if released else "lease_lost"
        acknowledged = await self._store.mark_published(event_id=message.event.event_id)
        return "published" if acknowledged else "lease_lost"


class OutboxDispatchIteration(Protocol):
    async def dispatch_once(self, *, limit: int) -> OutboxDispatchResult:
        """Dispatch at most one bounded batch."""


class OutboxLoopLogger(Protocol):
    def info(self, event: str, **values: object) -> object:
        """Record a successful nonempty batch."""

    def error(self, event: str, **values: object) -> object:
        """Record a sanitized iteration failure."""


async def run_outbox_dispatch_loop(
    dispatcher: OutboxDispatchIteration,
    *,
    stop_requested: asyncio.Event,
    poll_seconds: float,
    batch_size: int,
    logger: OutboxLoopLogger | None = None,
) -> None:
    if poll_seconds <= 0:
        raise ValueError("outbox poll_seconds must be positive")
    if not 1 <= batch_size <= 1_000:
        raise ValueError("outbox batch_size must be between 1 and 1000")
    active_logger = logger or get_logger(__name__, role="outbox_dispatcher")
    while not stop_requested.is_set():
        try:
            result = await dispatcher.dispatch_once(limit=batch_size)
        except Exception as error:
            active_logger.error(
                "outbox_dispatch_iteration_failed",
                error_type=type(error).__name__,
            )
        else:
            if result.claimed:
                active_logger.info(
                    "outbox_dispatch_batch_completed",
                    claimed=result.claimed,
                    published=result.published,
                    retry_scheduled=result.retry_scheduled,
                    lease_lost=result.lease_lost,
                )
        if stop_requested.is_set():
            break
        with suppress(TimeoutError):
            await asyncio.wait_for(stop_requested.wait(), timeout=poll_seconds)

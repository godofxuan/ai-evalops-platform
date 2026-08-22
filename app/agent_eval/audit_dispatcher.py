"""Credential-independent delivery of durable MCP audit outcomes."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol, cast
from uuid import UUID

from sqlalchemy import Select, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert

from app.core.clock import Clock, SystemClock
from app.core.logging import get_logger
from app.observability.metrics import PlatformMetrics
from app.persistence.database import AsyncSessionFactory
from app.persistence.orm_models import AuditEvent, McpAuditOutbox


@dataclass(frozen=True, slots=True)
class ClaimedAudit:
    outbox_id: UUID
    tenant_id: UUID
    actor_id: str
    api_key_id: UUID
    operation: str
    idempotency_key: str
    trace_id: str
    outcome_status: str
    attempt_count: int
    max_attempts: int
    lease_version: int


@dataclass(frozen=True, slots=True)
class AuditDispatchResult:
    claimed: int
    delivered: int
    retry_scheduled: int
    dead_lettered: int
    lease_lost: int


@dataclass(frozen=True, slots=True)
class AuditBacklog:
    pending: int
    oldest_pending_created_at: datetime | None
    dead_letter_count: int

    def oldest_pending_age_seconds(self, now: datetime) -> float:
        if self.oldest_pending_created_at is None:
            return 0.0
        return max((now - self.oldest_pending_created_at).total_seconds(), 0.0)


def build_claim_audit_statement(
    *,
    now: datetime,
    limit: int,
) -> Select[tuple[McpAuditOutbox]]:
    if not 1 <= limit <= 1_000:
        raise ValueError("audit dispatcher batch size must be between 1 and 1000")
    return (
        select(McpAuditOutbox)
        .where(
            McpAuditOutbox.delivery_status == "PENDING",
            McpAuditOutbox.outcome_status.is_not(None),
            McpAuditOutbox.available_at <= now,
            or_(
                McpAuditOutbox.lease_expires_at.is_(None),
                McpAuditOutbox.lease_expires_at <= now,
            ),
        )
        .order_by(
            McpAuditOutbox.available_at.asc(),
            McpAuditOutbox.created_at.asc(),
            McpAuditOutbox.id.asc(),
        )
        .limit(limit)
        .with_for_update(of=McpAuditOutbox, skip_locked=True)
    )


class AuditOutboxStore(Protocol):
    async def claim_batch(self, *, limit: int) -> tuple[ClaimedAudit, ...]:
        """Lease a bounded due batch using a system-owned dispatcher identity."""

    async def read_backlog(self) -> AuditBacklog:
        """Read global durable pending/age/dead-letter state."""

    async def acknowledge(self, message: ClaimedAudit) -> bool:
        """Fenced acknowledgement after idempotent sink delivery."""

    async def record_failure(
        self,
        message: ClaimedAudit,
        *,
        error_code: str,
        delay_seconds: float,
    ) -> Literal["retry_scheduled", "dead_lettered", "lease_lost"]:
        """Release for retry or terminally dead-letter an owned row."""


class AuditSink(Protocol):
    async def deliver(self, message: ClaimedAudit) -> None:
        """Idempotently materialize one audit event."""


class SQLAlchemyAuditOutboxStore:
    def __init__(
        self,
        session_factory: AsyncSessionFactory,
        *,
        dispatcher_id: str,
        lease_seconds: float,
        clock: Clock | None = None,
    ) -> None:
        if not dispatcher_id.strip() or len(dispatcher_id) > 128:
            raise ValueError("audit dispatcher_id must be nonblank and at most 128 characters")
        if lease_seconds <= 0:
            raise ValueError("audit lease_seconds must be positive")
        self._session_factory = session_factory
        self._dispatcher_id = dispatcher_id
        self._lease_seconds = lease_seconds
        self._clock = clock or SystemClock()

    async def claim_batch(self, *, limit: int) -> tuple[ClaimedAudit, ...]:
        now = self._clock.now()
        expires_at = now + timedelta(seconds=self._lease_seconds)
        claimed: list[ClaimedAudit] = []
        async with self._session_factory.begin() as session:
            rows = (
                (await session.execute(build_claim_audit_statement(now=now, limit=limit)))
                .scalars()
                .all()
            )
            for row in rows:
                row.lease_owner = self._dispatcher_id
                row.lease_expires_at = expires_at
                row.lease_version += 1
                row.attempt_count += 1
                claimed.append(
                    ClaimedAudit(
                        outbox_id=row.id,
                        tenant_id=row.tenant_id,
                        actor_id=row.actor_id,
                        api_key_id=row.api_key_id,
                        operation=row.tool_name,
                        idempotency_key=row.call_identity,
                        trace_id=row.trace_id,
                        outcome_status=cast(str, row.outcome_status),
                        attempt_count=row.attempt_count,
                        max_attempts=row.max_attempts,
                        lease_version=row.lease_version,
                    )
                )
        return tuple(claimed)

    async def read_backlog(self) -> AuditBacklog:
        async with self._session_factory() as session:
            pending, oldest, dead_letters = (
                await session.execute(
                    select(
                        func.count(McpAuditOutbox.id).filter(
                            McpAuditOutbox.delivery_status == "PENDING"
                        ),
                        func.min(McpAuditOutbox.created_at).filter(
                            McpAuditOutbox.delivery_status == "PENDING"
                        ),
                        func.count(McpAuditOutbox.id).filter(
                            McpAuditOutbox.delivery_status == "DEAD_LETTER"
                        ),
                    )
                )
            ).one()
        return AuditBacklog(
            pending=int(pending),
            oldest_pending_created_at=oldest,
            dead_letter_count=int(dead_letters),
        )

    async def acknowledge(self, message: ClaimedAudit) -> bool:
        now = self._clock.now()
        async with self._session_factory.begin() as session:
            row_id = (
                await session.execute(
                    update(McpAuditOutbox)
                    .where(
                        McpAuditOutbox.id == message.outbox_id,
                        McpAuditOutbox.delivery_status == "PENDING",
                        McpAuditOutbox.lease_owner == self._dispatcher_id,
                        McpAuditOutbox.lease_version == message.lease_version,
                        McpAuditOutbox.lease_expires_at > now,
                    )
                    .values(
                        delivery_status="DELIVERED",
                        delivered_at=now,
                        lease_owner=None,
                        lease_expires_at=None,
                        last_error_code=None,
                    )
                    .returning(McpAuditOutbox.id)
                )
            ).scalar_one_or_none()
        return row_id is not None

    async def record_failure(
        self,
        message: ClaimedAudit,
        *,
        error_code: str,
        delay_seconds: float,
    ) -> Literal["retry_scheduled", "dead_lettered", "lease_lost"]:
        if delay_seconds < 0:
            raise ValueError("audit retry delay must be nonnegative")
        now = self._clock.now()
        dead_letter = message.attempt_count >= message.max_attempts
        values: dict[str, object] = {
            "lease_owner": None,
            "lease_expires_at": None,
            "last_error_code": error_code[:100],
        }
        if dead_letter:
            values.update(delivery_status="DEAD_LETTER", dead_lettered_at=now)
        else:
            values["available_at"] = now + timedelta(seconds=delay_seconds)
        async with self._session_factory.begin() as session:
            row_id = (
                await session.execute(
                    update(McpAuditOutbox)
                    .where(
                        McpAuditOutbox.id == message.outbox_id,
                        McpAuditOutbox.delivery_status == "PENDING",
                        McpAuditOutbox.lease_owner == self._dispatcher_id,
                        McpAuditOutbox.lease_version == message.lease_version,
                    )
                    .values(**values)
                    .returning(McpAuditOutbox.id)
                )
            ).scalar_one_or_none()
        if row_id is None:
            return "lease_lost"
        return "dead_lettered" if dead_letter else "retry_scheduled"


class SQLAlchemyAuditEventSink:
    """Idempotent database sink keyed by the source Outbox UUID."""

    def __init__(self, session_factory: AsyncSessionFactory) -> None:
        self._session_factory = session_factory

    async def deliver(self, message: ClaimedAudit) -> None:
        metadata = {
            "api_key_id": str(message.api_key_id),
            "operation": message.operation,
            "idempotency_key": message.idempotency_key,
            "status": message.outcome_status,
            "trace_id": message.trace_id,
            "delivery_attempt": message.attempt_count,
            "source_outbox_id": str(message.outbox_id),
        }
        async with self._session_factory.begin() as session:
            await session.execute(
                postgresql_insert(AuditEvent)
                .values(
                    id=message.outbox_id,
                    tenant_id=message.tenant_id,
                    actor_id=message.actor_id,
                    action="mcp.tool_called",
                    resource_type="mcp_tool",
                    resource_id=UUID(hex=message.trace_id),
                    metadata_json=metadata,
                )
                .on_conflict_do_nothing(index_elements=[AuditEvent.id])
            )
            persisted = (
                await session.execute(select(AuditEvent).where(AuditEvent.id == message.outbox_id))
            ).scalar_one()
            if (
                persisted.tenant_id != message.tenant_id
                or persisted.actor_id != message.actor_id
                or persisted.action != "mcp.tool_called"
                or persisted.resource_id != UUID(hex=message.trace_id)
            ):
                raise RuntimeError("audit sink idempotency identity conflict")


def audit_retry_delay_seconds(
    *,
    attempt_count: int,
    base_seconds: float,
    max_seconds: float,
) -> float:
    if attempt_count < 1:
        raise ValueError("audit attempt_count must be positive")
    if base_seconds <= 0 or max_seconds <= 0 or base_seconds > max_seconds:
        raise ValueError("audit retry bounds are invalid")
    return min(base_seconds * (2.0 ** min(attempt_count - 1, 62)), max_seconds)


class AuditDispatcher:
    def __init__(
        self,
        *,
        store: AuditOutboxStore,
        sink: AuditSink,
        delivery_timeout_seconds: float,
        retry_base_seconds: float,
        retry_max_seconds: float,
        metrics: PlatformMetrics | None = None,
    ) -> None:
        if delivery_timeout_seconds <= 0:
            raise ValueError("audit delivery timeout must be positive")
        audit_retry_delay_seconds(
            attempt_count=1,
            base_seconds=retry_base_seconds,
            max_seconds=retry_max_seconds,
        )
        self._store = store
        self._sink = sink
        self._delivery_timeout_seconds = delivery_timeout_seconds
        self._retry_base_seconds = retry_base_seconds
        self._retry_max_seconds = retry_max_seconds
        self._metrics = metrics

    async def dispatch_once(self, *, limit: int) -> AuditDispatchResult:
        claimed = await self._store.claim_batch(limit=limit)
        outcomes = await asyncio.gather(*(self._dispatch_one(message) for message in claimed))
        result = AuditDispatchResult(
            claimed=len(claimed),
            delivered=outcomes.count("delivered"),
            retry_scheduled=outcomes.count("retry_scheduled"),
            dead_lettered=outcomes.count("dead_lettered"),
            lease_lost=outcomes.count("lease_lost"),
        )
        if self._metrics is not None:
            self._metrics.record_audit_delivery_failure(
                result.retry_scheduled + result.dead_lettered
            )
            self._metrics.record_audit_dead_letter(result.dead_lettered)
            backlog = await self._store.read_backlog()
            self._metrics.set_audit_pending(backlog.pending)
            self._metrics.set_audit_oldest_pending_age(
                backlog.oldest_pending_age_seconds(datetime.now(UTC))
            )
            self._metrics.set_audit_dead_letter_count(backlog.dead_letter_count)
        return result

    async def _dispatch_one(
        self,
        message: ClaimedAudit,
    ) -> Literal["delivered", "retry_scheduled", "dead_lettered", "lease_lost"]:
        try:
            await asyncio.wait_for(
                self._sink.deliver(message),
                timeout=self._delivery_timeout_seconds,
            )
        except Exception as error:
            return await self._store.record_failure(
                message,
                error_code=type(error).__name__,
                delay_seconds=audit_retry_delay_seconds(
                    attempt_count=message.attempt_count,
                    base_seconds=self._retry_base_seconds,
                    max_seconds=self._retry_max_seconds,
                ),
            )
        return "delivered" if await self._store.acknowledge(message) else "lease_lost"


class AuditDispatchIteration(Protocol):
    async def dispatch_once(self, *, limit: int) -> AuditDispatchResult:
        """Dispatch at most one bounded audit batch."""


async def run_audit_dispatch_loop(
    dispatcher: AuditDispatchIteration,
    *,
    stop_requested: asyncio.Event,
    poll_seconds: float,
    batch_size: int,
) -> None:
    if poll_seconds <= 0:
        raise ValueError("audit poll_seconds must be positive")
    if not 1 <= batch_size <= 1_000:
        raise ValueError("audit batch_size must be between 1 and 1000")
    logger = get_logger(__name__, role="audit_dispatcher")
    while not stop_requested.is_set():
        try:
            result = await dispatcher.dispatch_once(limit=batch_size)
        except Exception as error:
            logger.error("audit_dispatch_iteration_failed", error_type=type(error).__name__)
        else:
            if result.claimed:
                logger.info(
                    "audit_dispatch_batch_completed",
                    claimed=result.claimed,
                    delivered=result.delivered,
                    retry_scheduled=result.retry_scheduled,
                    dead_lettered=result.dead_lettered,
                    lease_lost=result.lease_lost,
                )
        if stop_requested.is_set():
            break
        with suppress(TimeoutError):
            await asyncio.wait_for(stop_requested.wait(), timeout=poll_seconds)

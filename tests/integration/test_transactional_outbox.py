import asyncio
import hashlib
import os
from collections.abc import AsyncIterator
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from redis.asyncio import Redis
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.domain.enums import ArtifactType, RunStatus
from app.events.models import EventType, ProgressEvent
from app.events.outbox import (
    ClaimedOutboxEvent,
    OutboxDispatcher,
    OutboxDispatchResult,
    SQLAlchemyOutboxMaintenance,
    SQLAlchemyOutboxStore,
    enqueue_progress_event,
)
from app.events.publisher import RedisEventPublisher
from app.events.subscriber import RedisEventSubscriber
from app.observability.durable import refresh_durable_outbox_gauges
from app.observability.metrics import PlatformMetrics
from app.persistence.database import create_database_engine, create_session_factory
from app.persistence.orm_models import (
    APIKey,
    ArtifactBlob,
    ArtifactReference,
    Dataset,
    DatasetVersion,
    EvaluationRun,
    ProgressEventOutbox,
    Tenant,
)

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self._value = value

    def now(self) -> datetime:
        return self._value

    def advance(self, seconds: float) -> None:
        self._value += timedelta(seconds=seconds)


class FlappingPublisher:
    def __init__(self, delegate: RedisEventPublisher) -> None:
        self._delegate = delegate
        self.events: list[ProgressEvent] = []

    async def publish(self, event: ProgressEvent) -> bool:
        self.events.append(event)
        if len(self.events) == 1:
            return False
        return await self._delegate.publish(event)


class AckCrashStore:
    """Simulate process loss after Redis accepted the event but before DB acknowledgement."""

    def __init__(self, delegate: SQLAlchemyOutboxStore) -> None:
        self._delegate = delegate

    async def claim_batch(self, *, limit: int) -> tuple[ClaimedOutboxEvent, ...]:
        return await self._delegate.claim_batch(limit=limit)

    async def mark_published(self, *, event_id: UUID) -> bool:
        del event_id
        return False

    async def reschedule(
        self,
        *,
        event_id: UUID,
        error_code: str,
        delay_seconds: float,
    ) -> bool:
        return await self._delegate.reschedule(
            event_id=event_id,
            error_code=error_code,
            delay_seconds=delay_seconds,
        )


async def _next_event(
    stream: AsyncIterator[ProgressEvent | None],
) -> ProgressEvent:
    while True:
        event = await asyncio.wait_for(anext(stream), timeout=2)
        if event is not None:
            return event


async def _subscribe_before_dispatch(
    stream: AsyncIterator[ProgressEvent | None],
) -> asyncio.Task[ProgressEvent]:
    pending = asyncio.create_task(_next_event(stream))
    await asyncio.sleep(0.05)
    return pending


def _run(
    *,
    run_id: UUID,
    tenant_id: UUID,
    dataset_version_id: UUID,
    api_key_id: UUID,
) -> EvaluationRun:
    return EvaluationRun(
        id=run_id,
        tenant_id=tenant_id,
        dataset_version_id=dataset_version_id,
        dataset_hash="a" * 64,
        idempotency_key=f"outbox-{run_id.hex}",
        request_hash="b" * 64,
        target_type="mock",
        target_config_json={},
        target_config_hash="c" * 64,
        evaluator_type="execution",
        evaluator_config_json={},
        evaluator_config_hash="d" * 64,
        target_version="v1",
        evaluator_version="v1",
        status=RunStatus.RUNNING,
        total_jobs=1,
        created_by=api_key_id,
        started_at=NOW,
    )


@pytest.mark.integration
async def test_real_transactional_outbox_claim_retry_and_at_least_once_delivery(
    tmp_path: Path,
) -> None:
    if os.getenv("EVALOPS_RUN_INTEGRATION") != "1":
        pytest.skip("set EVALOPS_RUN_INTEGRATION=1 with migrated PostgreSQL and Redis")
    database_url = os.getenv("EVALOPS_DATABASE_URL")
    redis_url = os.getenv("EVALOPS_REDIS_URL")
    if database_url is None or redis_url is None:
        pytest.fail("outbox integration requires EVALOPS_DATABASE_URL and EVALOPS_REDIS_URL")

    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=SecretStr(database_url),
        redis_url=SecretStr(redis_url),
        artifact_root=tmp_path,
    )
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)
    redis_client = Redis.from_url(redis_url, decode_responses=True)
    redis_publisher = RedisEventPublisher(redis_client)
    clock = MutableClock(NOW)
    tenant_id = uuid4()
    other_tenant_id = uuid4()
    api_key_id = uuid4()
    dataset_id = uuid4()
    artifact_id = uuid4()
    dataset_version_id = uuid4()
    run_id = uuid4()
    rollback_event_id = uuid4()
    concurrent_event_id = uuid4()
    retry_event_id = uuid4()
    replay_event_id = uuid4()
    old_published_ids = (uuid4(), uuid4())
    recent_published_id = uuid4()
    old_pending_id = uuid4()
    blob_sha256 = hashlib.sha256(tenant_id.bytes).hexdigest()
    subscriber = RedisEventSubscriber(redis_client, poll_timeout_seconds=0.05)
    stream = subscriber.listen(tenant_id=tenant_id, run_id=run_id)
    pending: asyncio.Task[ProgressEvent] | None = None

    try:
        async with session_factory.begin() as session:
            session.add_all(
                [
                    Tenant(
                        id=tenant_id,
                        slug=f"outbox-{tenant_id.hex}",
                        name="Outbox integration tenant",
                    ),
                    Tenant(
                        id=other_tenant_id,
                        slug=f"outbox-other-{other_tenant_id.hex}",
                        name="Outbox other tenant",
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    APIKey(
                        id=api_key_id,
                        tenant_id=tenant_id,
                        name="outbox-integration",
                        key_prefix=f"outbox_{tenant_id.hex[:8]}",
                        key_hash="not-a-real-key",
                    ),
                    Dataset(
                        id=dataset_id,
                        tenant_id=tenant_id,
                        name="outbox-dataset",
                    ),
                    ArtifactBlob(
                        sha256=blob_sha256,
                        byte_size=1,
                        storage_path=f"{blob_sha256[:2]}/{blob_sha256}",
                    ),
                    ArtifactReference(
                        id=artifact_id,
                        tenant_id=tenant_id,
                        artifact_type=ArtifactType.DATASET_SOURCE,
                        blob_sha256=blob_sha256,
                        media_type="application/x-ndjson",
                    ),
                ]
            )
            await session.flush()
            session.add(
                DatasetVersion(
                    id=dataset_version_id,
                    dataset_id=dataset_id,
                    tenant_id=tenant_id,
                    artifact_id=artifact_id,
                    version=1,
                    schema_version="1",
                    sha256=blob_sha256,
                    case_count=1,
                )
            )
            await session.flush()
            session.add(
                _run(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    dataset_version_id=dataset_version_id,
                    api_key_id=api_key_id,
                )
            )

        with pytest.raises(RuntimeError, match="rollback outbox insertion"):
            async with session_factory.begin() as session:
                enqueue_progress_event(
                    session,
                    event_id=rollback_event_id,
                    event_type=EventType.JOB_PROGRESS,
                    tenant_id=tenant_id,
                    run_id=run_id,
                    timestamp=NOW,
                    payload={"status": "must-rollback"},
                )
                await session.flush()
                raise RuntimeError("rollback outbox insertion")
        async with session_factory() as session:
            assert await session.get(ProgressEventOutbox, rollback_event_id) is None

        with pytest.raises(IntegrityError) as cross_tenant:
            async with session_factory.begin() as session:
                enqueue_progress_event(
                    session,
                    event_type=EventType.JOB_PROGRESS,
                    tenant_id=other_tenant_id,
                    run_id=run_id,
                    timestamp=NOW,
                    payload={"status": "wrong-tenant"},
                )
                await session.flush()
        diagnostic = getattr(cross_tenant.value.orig, "diag", None)
        assert getattr(diagnostic, "constraint_name", None) == (
            "fk_progress_event_outbox_run_id_tenant_id_evaluation_runs"
        )

        async with session_factory.begin() as session:
            enqueue_progress_event(
                session,
                event_id=concurrent_event_id,
                event_type=EventType.JOB_PROGRESS,
                tenant_id=tenant_id,
                run_id=run_id,
                timestamp=NOW,
                payload={"status": "concurrent-claim"},
            )
        dispatcher_a = OutboxDispatcher(
            store=SQLAlchemyOutboxStore(
                session_factory,
                dispatcher_id="integration-a",
                lease_seconds=10,
                clock=clock,
            ),
            publisher=redis_publisher,
            publish_timeout_seconds=1,
            retry_base_seconds=1,
            retry_max_seconds=10,
        )
        dispatcher_b = OutboxDispatcher(
            store=SQLAlchemyOutboxStore(
                session_factory,
                dispatcher_id="integration-b",
                lease_seconds=10,
                clock=clock,
            ),
            publisher=redis_publisher,
            publish_timeout_seconds=1,
            retry_base_seconds=1,
            retry_max_seconds=10,
        )
        pending = await _subscribe_before_dispatch(stream)
        concurrent_results = await asyncio.gather(
            dispatcher_a.dispatch_once(limit=10),
            dispatcher_b.dispatch_once(limit=10),
        )
        delivered = await pending
        assert sum(result.claimed for result in concurrent_results) == 1
        assert sum(result.published for result in concurrent_results) == 1
        assert delivered.event_id == concurrent_event_id
        async with session_factory() as session:
            concurrent_row = await session.get(ProgressEventOutbox, concurrent_event_id)
            assert concurrent_row is not None
            assert concurrent_row.published_at == NOW
            assert concurrent_row.attempt_count == 1
            assert concurrent_row.lease_owner is None

        async with session_factory.begin() as session:
            enqueue_progress_event(
                session,
                event_id=retry_event_id,
                event_type=EventType.JOB_FAILED,
                tenant_id=tenant_id,
                run_id=run_id,
                timestamp=NOW,
                payload={"status": "failed"},
            )
        retry_publisher = FlappingPublisher(redis_publisher)
        retry_dispatcher = OutboxDispatcher(
            store=SQLAlchemyOutboxStore(
                session_factory,
                dispatcher_id="integration-retry",
                lease_seconds=10,
                clock=clock,
            ),
            publisher=retry_publisher,
            publish_timeout_seconds=1,
            retry_base_seconds=2,
            retry_max_seconds=10,
        )
        first_retry = await retry_dispatcher.dispatch_once(limit=10)
        assert first_retry == OutboxDispatchResult(1, 0, 1, 0)
        async with session_factory() as session:
            retry_row = await session.get(ProgressEventOutbox, retry_event_id)
            assert retry_row is not None
            assert retry_row.published_at is None
            assert retry_row.available_at == NOW + timedelta(seconds=2)
            assert retry_row.attempt_count == 1
            assert retry_row.lease_owner is None
            assert retry_row.last_error_code == "publish_returned_false"

        clock.advance(2)
        pending = await _subscribe_before_dispatch(stream)
        second_retry = await retry_dispatcher.dispatch_once(limit=10)
        delivered = await pending
        assert second_retry == OutboxDispatchResult(1, 1, 0, 0)
        assert delivered.event_id == retry_event_id
        assert [event.event_id for event in retry_publisher.events] == [
            retry_event_id,
            retry_event_id,
        ]
        async with session_factory() as session:
            retry_row = await session.get(ProgressEventOutbox, retry_event_id)
            assert retry_row is not None
            assert retry_row.published_at == NOW + timedelta(seconds=2)
            assert retry_row.attempt_count == 2
            assert retry_row.last_error_code is None

        async with session_factory.begin() as session:
            enqueue_progress_event(
                session,
                event_id=replay_event_id,
                event_type=EventType.RUN_COMPLETED,
                tenant_id=tenant_id,
                run_id=run_id,
                timestamp=clock.now(),
                payload={"status": "succeeded"},
            )
        crash_store = SQLAlchemyOutboxStore(
            session_factory,
            dispatcher_id="integration-crash-before-ack",
            lease_seconds=5,
            clock=clock,
        )
        crash_dispatcher = OutboxDispatcher(
            store=AckCrashStore(crash_store),
            publisher=redis_publisher,
            publish_timeout_seconds=1,
            retry_base_seconds=1,
            retry_max_seconds=10,
        )
        pending = await _subscribe_before_dispatch(stream)
        crash_result = await crash_dispatcher.dispatch_once(limit=10)
        first_delivery = await pending
        assert crash_result == OutboxDispatchResult(1, 0, 0, 1)
        assert first_delivery.event_id == replay_event_id

        clock.advance(6)
        recovery_dispatcher = OutboxDispatcher(
            store=SQLAlchemyOutboxStore(
                session_factory,
                dispatcher_id="integration-recovery",
                lease_seconds=5,
                clock=clock,
            ),
            publisher=redis_publisher,
            publish_timeout_seconds=1,
            retry_base_seconds=1,
            retry_max_seconds=10,
        )
        pending = await _subscribe_before_dispatch(stream)
        recovery_result = await recovery_dispatcher.dispatch_once(limit=10)
        replay_delivery = await pending
        assert recovery_result == OutboxDispatchResult(1, 1, 0, 0)
        assert replay_delivery.event_id == first_delivery.event_id == replay_event_id
        async with session_factory() as session:
            replay_row = await session.get(ProgressEventOutbox, replay_event_id)
            assert replay_row is not None
            assert replay_row.published_at == clock.now()
            assert replay_row.attempt_count == 2
            assert replay_row.lease_owner is None

        retention_now = clock.now()
        old_timestamp = retention_now - timedelta(days=8)
        recent_timestamp = retention_now - timedelta(days=1)

        def retention_row(
            event_id: UUID,
            *,
            created_at: datetime,
            published_at: datetime | None,
        ) -> ProgressEventOutbox:
            return ProgressEventOutbox(
                id=event_id,
                tenant_id=tenant_id,
                run_id=run_id,
                event_type=EventType.JOB_PROGRESS.value,
                payload_json={"status": "retention-integration"},
                occurred_at=created_at,
                available_at=created_at,
                attempt_count=1 if published_at is not None else 0,
                published_at=published_at,
                created_at=created_at,
            )

        async with session_factory.begin() as session:
            session.add_all(
                [
                    *(
                        retention_row(
                            event_id,
                            created_at=old_timestamp,
                            published_at=old_timestamp,
                        )
                        for event_id in old_published_ids
                    ),
                    retention_row(
                        recent_published_id,
                        created_at=recent_timestamp,
                        published_at=recent_timestamp,
                    ),
                    retention_row(
                        old_pending_id,
                        created_at=old_timestamp,
                        published_at=None,
                    ),
                ]
            )

        cleanup_results = await asyncio.gather(
            SQLAlchemyOutboxMaintenance(
                session_factory,
                retention_seconds=7 * 24 * 60 * 60,
                clock=clock,
            ).cleanup_once(limit=1),
            SQLAlchemyOutboxMaintenance(
                session_factory,
                retention_seconds=7 * 24 * 60 * 60,
                clock=clock,
            ).cleanup_once(limit=1),
        )
        assert sorted(cleanup_results) == [1, 1]
        async with session_factory() as session:
            assert all(
                [
                    await session.get(ProgressEventOutbox, event_id) is None
                    for event_id in old_published_ids
                ]
            )
            assert await session.get(ProgressEventOutbox, recent_published_id) is not None
            assert await session.get(ProgressEventOutbox, old_pending_id) is not None

        metrics = PlatformMetrics()
        gauges = await refresh_durable_outbox_gauges(
            session_factory=session_factory,
            metrics=metrics,
            now=retention_now,
        )
        assert gauges.pending == 1
        assert gauges.oldest_pending_age_seconds(retention_now) == 8 * 24 * 60 * 60
        rendered = metrics.render().decode("utf-8")
        assert "outbox_pending 1.0" in rendered
        assert "outbox_oldest_pending_age_seconds 691200.0" in rendered
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
            with suppress(asyncio.CancelledError):
                await pending
        await stream.aclose()
        await redis_client.aclose()
        async with session_factory.begin() as session:
            await session.execute(delete(EvaluationRun).where(EvaluationRun.id == run_id))
            await session.execute(
                delete(DatasetVersion).where(DatasetVersion.id == dataset_version_id)
            )
            await session.execute(
                delete(ArtifactReference).where(ArtifactReference.id == artifact_id)
            )
            await session.execute(delete(ArtifactBlob).where(ArtifactBlob.sha256 == blob_sha256))
            await session.execute(delete(Dataset).where(Dataset.id == dataset_id))
            await session.execute(delete(APIKey).where(APIKey.id == api_key_id))
            await session.execute(delete(Tenant).where(Tenant.id.in_((tenant_id, other_tenant_id))))
        await engine.dispose()

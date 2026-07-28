import asyncio
import os
import socket
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.core.config import Settings
from app.core.logging import get_logger
from app.events.models import EventType, ProgressEvent
from app.events.publisher import RedisEventPublisher
from app.jobs.claiming import SQLAlchemyJobClaimer
from app.jobs.failures import SQLAlchemyFailureCommitter
from app.jobs.heartbeat import LeaseLostError, SQLAlchemyHeartbeatService
from app.jobs.lease import LeasePolicy
from app.jobs.reaper import SQLAlchemyJobReaper
from app.jobs.results import SQLAlchemyResultCommitter
from app.jobs.retry_policy import RetryPolicy
from app.persistence.database import create_database_engine, create_session_factory
from app.persistence.redis import create_redis_client
from app.workers.lease_runner import LeaseHeartbeatRunner
from app.workers.worker import EvaluationWorker


async def run_worker_process(
    settings: Settings,
    *,
    stop_requested: asyncio.Event,
    once: bool = False,
) -> None:
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)
    redis_client = create_redis_client(settings)
    event_publisher = RedisEventPublisher(redis_client)
    retry_policy = _retry_policy(settings)
    worker_id = _worker_id()
    worker = EvaluationWorker(
        claimer=SQLAlchemyJobClaimer(
            session_factory,
            lease_policy=LeasePolicy(timedelta(seconds=settings.worker_lease_seconds)),
        ),
        result_committer=SQLAlchemyResultCommitter(session_factory),
        failure_committer=SQLAlchemyFailureCommitter(
            session_factory,
            retry_policy=retry_policy,
        ),
        lease_runner=LeaseHeartbeatRunner(
            heartbeat_service=SQLAlchemyHeartbeatService(
                session_factory,
                lease_duration=timedelta(seconds=settings.worker_lease_seconds),
            ),
            heartbeat_interval_seconds=settings.worker_heartbeat_seconds,
        ),
        event_publisher=event_publisher,
    )
    logger = get_logger(__name__, role="worker", worker_id=worker_id)
    logger.info("worker_started")
    try:
        while not stop_requested.is_set():
            try:
                processed = await worker.process_one(worker_id=worker_id)
            except LeaseLostError:
                logger.warning("worker_lease_lost")
                processed = True
            except Exception as error:
                logger.error(
                    "worker_iteration_failed",
                    error_type=type(error).__name__,
                )
                processed = True
            if once:
                return
            if not processed:
                await _wait_or_stop(stop_requested, settings.worker_poll_seconds)
    finally:
        await redis_client.aclose()
        await engine.dispose()
        logger.info("worker_stopped")


async def run_reaper_process(
    settings: Settings,
    *,
    stop_requested: asyncio.Event,
    once: bool = False,
) -> None:
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)
    redis_client = create_redis_client(settings)
    event_publisher = RedisEventPublisher(redis_client)
    reaper_id = f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:8]}"
    reaper = SQLAlchemyJobReaper(
        session_factory,
        retry_policy=_retry_policy(settings),
        reaper_id=reaper_id,
    )
    logger = get_logger(__name__, role="reaper", reaper_id=reaper_id)
    logger.info("reaper_started")
    try:
        while not stop_requested.is_set():
            try:
                reaped = await reaper.reap(limit=settings.reaper_batch_size)
                for item in reaped:
                    event_type = (
                        EventType.JOB_RETRIED if item.action == "requeued" else EventType.JOB_FAILED
                    )
                    await event_publisher.publish(
                        ProgressEvent(
                            event_type=event_type,
                            run_id=item.run_id,
                            tenant_id=item.tenant_id,
                            timestamp=datetime.now(UTC),
                            payload={
                                "job_id": str(item.job_id),
                                "status": item.status.value,
                                "source": "reaper",
                            },
                        )
                    )
                    if item.run_status is not None and item.run_status.value in {
                        "succeeded",
                        "partially_succeeded",
                        "failed",
                        "cancelled",
                    }:
                        await event_publisher.publish(
                            ProgressEvent(
                                event_type=EventType.RUN_COMPLETED,
                                run_id=item.run_id,
                                tenant_id=item.tenant_id,
                                timestamp=datetime.now(UTC),
                                payload={"status": item.run_status.value},
                            )
                        )
                if reaped:
                    logger.info("reaper_batch_completed", count=len(reaped))
            except Exception as error:
                logger.error(
                    "reaper_iteration_failed",
                    error_type=type(error).__name__,
                )
            if once:
                return
            await _wait_or_stop(stop_requested, settings.reaper_interval_seconds)
    finally:
        await redis_client.aclose()
        await engine.dispose()
        logger.info("reaper_stopped")


def _retry_policy(settings: Settings) -> RetryPolicy:
    return RetryPolicy(
        base_delay_seconds=settings.retry_base_delay_seconds,
        max_delay_seconds=settings.retry_max_delay_seconds,
        jitter_ratio=settings.retry_jitter_ratio,
    )


def _worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:8]}"


async def _wait_or_stop(stop_requested: asyncio.Event, timeout_seconds: float) -> None:
    with suppress(TimeoutError):
        await asyncio.wait_for(stop_requested.wait(), timeout=timeout_seconds)

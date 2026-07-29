import asyncio
import os
import socket
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Protocol
from uuid import uuid4

import structlog

from app.core.config import Settings
from app.core.logging import get_logger
from app.core.telemetry import Telemetry, parse_otlp_headers
from app.events.models import EventType, ProgressEvent
from app.events.publisher import RedisEventPublisher
from app.jobs.claiming import SQLAlchemyJobClaimer
from app.jobs.failures import SQLAlchemyFailureCommitter
from app.jobs.heartbeat import LeaseLostError, SQLAlchemyHeartbeatService
from app.jobs.lease import LeasePolicy
from app.jobs.reaper import ReapedJob, SQLAlchemyJobReaper
from app.jobs.results import SQLAlchemyResultCommitter
from app.jobs.retry_policy import RetryPolicy
from app.observability.metrics import PlatformMetrics, start_metrics_server
from app.persistence.database import create_database_engine, create_session_factory
from app.persistence.redis import create_redis_client
from app.workers.lease_runner import LeaseHeartbeatRunner
from app.workers.worker import EvaluationWorker


class WorkerIteration(Protocol):
    async def process_one(self, *, worker_id: str) -> bool:
        """Process at most one durable Job."""


class ReaperIteration(Protocol):
    async def reap(self, *, limit: int = 100) -> tuple[ReapedJob, ...]:
        """Recover at most one bounded batch of expired leases."""


class IterationLogger(Protocol):
    def warning(self, event: str, **values: object) -> object:
        """Record a warning."""

    def error(self, event: str, **values: object) -> object:
        """Record an error."""


async def run_worker_process(
    settings: Settings,
    *,
    stop_requested: asyncio.Event,
    once: bool = False,
) -> None:
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)
    redis_client = create_redis_client(settings)
    retry_policy = _retry_policy(settings)
    worker_id = _worker_id()
    metrics = PlatformMetrics()
    telemetry = _telemetry(settings, role="worker", instance_id=worker_id)
    metrics_server = (
        start_metrics_server(
            metrics=metrics,
            host=settings.metrics_host,
            port=settings.worker_metrics_port,
        )
        if settings.metrics_enabled
        else None
    )
    event_publisher = RedisEventPublisher(redis_client, metrics=metrics)
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
        metrics=metrics,
        telemetry=telemetry,
    )
    logger = get_logger(__name__, role="worker", worker_id=worker_id)
    logger.info("worker_started")
    try:
        while not stop_requested.is_set():
            processed = await run_worker_iteration(
                worker,
                worker_id=worker_id,
                logger=logger,
            )
            if once:
                return
            if not processed:
                await _wait_or_stop(stop_requested, settings.worker_poll_seconds)
    finally:
        if metrics_server is not None:
            metrics_server.close()
        telemetry.shutdown()
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
    reaper_id = f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:8]}"
    metrics = PlatformMetrics()
    telemetry = _telemetry(settings, role="reaper", instance_id=reaper_id)
    metrics_server = (
        start_metrics_server(
            metrics=metrics,
            host=settings.metrics_host,
            port=settings.reaper_metrics_port,
        )
        if settings.metrics_enabled
        else None
    )
    event_publisher = RedisEventPublisher(redis_client, metrics=metrics)
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
                with telemetry.start_as_current_span("reaper.recover_expired_leases"):
                    trace_id = telemetry.current_trace_id()
                    with structlog.contextvars.bound_contextvars(trace_id=trace_id):
                        reaped = await run_reaper_iteration(
                            reaper,
                            metrics=metrics,
                            limit=settings.reaper_batch_size,
                        )
                metrics.record_job_lease_expired(len(reaped))
                for item in reaped:
                    if item.action == "requeued":
                        metrics.record_job_retry()
                    elif item.action == "failed":
                        metrics.record_job_failed()
                    event_type = (
                        EventType.JOB_RETRIED if item.action == "requeued" else EventType.JOB_FAILED
                    )
                    with telemetry.start_as_current_span(
                        "progress.publish",
                        attributes={
                            "tenant.id": str(item.tenant_id),
                            "run.id": str(item.run_id),
                            "job.id": str(item.job_id),
                        },
                    ):
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
        if metrics_server is not None:
            metrics_server.close()
        telemetry.shutdown()
        await redis_client.aclose()
        await engine.dispose()
        logger.info("reaper_stopped")


async def run_reaper_iteration(
    reaper: ReaperIteration,
    *,
    metrics: PlatformMetrics,
    limit: int,
) -> tuple[ReapedJob, ...]:
    started_at = perf_counter()
    try:
        return await reaper.reap(limit=limit)
    finally:
        metrics.observe_db_operation(
            operation="reaper",
            duration_seconds=perf_counter() - started_at,
        )


def _retry_policy(settings: Settings) -> RetryPolicy:
    return RetryPolicy(
        base_delay_seconds=settings.retry_base_delay_seconds,
        max_delay_seconds=settings.retry_max_delay_seconds,
        jitter_ratio=settings.retry_jitter_ratio,
    )


def _worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:8]}"


def _telemetry(
    settings: Settings,
    *,
    role: str,
    instance_id: str,
) -> Telemetry:
    secret_headers = settings.otel_exporter_otlp_headers
    return Telemetry(
        service_name=settings.otel_service_name,
        enabled=settings.otel_enabled,
        otlp_endpoint=settings.otel_exporter_otlp_endpoint,
        otlp_headers=parse_otlp_headers(
            None if secret_headers is None else secret_headers.get_secret_value()
        ),
        resource_attributes={
            "process.role": role,
            "service.instance.id": instance_id,
        },
    )


async def run_worker_iteration(
    worker: WorkerIteration,
    *,
    worker_id: str,
    logger: IterationLogger,
) -> bool:
    try:
        return await worker.process_one(worker_id=worker_id)
    except LeaseLostError:
        logger.warning("worker_lease_lost")
        return True
    except Exception as error:
        logger.error(
            "worker_iteration_failed",
            error_type=type(error).__name__,
        )
        return True


async def _wait_or_stop(stop_requested: asyncio.Event, timeout_seconds: float) -> None:
    with suppress(TimeoutError):
        await asyncio.wait_for(stop_requested.wait(), timeout=timeout_seconds)

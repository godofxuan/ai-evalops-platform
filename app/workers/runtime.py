import asyncio
import os
import socket
from contextlib import suppress
from datetime import timedelta
from time import perf_counter
from typing import Protocol
from uuid import uuid4

import structlog

from app.core.config import Settings
from app.core.logging import get_logger
from app.core.telemetry import Telemetry, parse_otlp_headers
from app.jobs.claiming import SQLAlchemyJobClaimer
from app.jobs.failures import SQLAlchemyFailureCommitter
from app.jobs.heartbeat import LeaseLostError, SQLAlchemyHeartbeatService
from app.jobs.lease import LeasePolicy
from app.jobs.reaper import ReapedJob, SQLAlchemyJobReaper
from app.jobs.results import SQLAlchemyResultCommitter
from app.jobs.retry_policy import RetryPolicy
from app.observability.metrics import PlatformMetrics, start_metrics_server
from app.persistence.database import create_database_engine, create_session_factory
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
                    await handle_reaped_job(
                        item,
                        metrics=metrics,
                        telemetry=telemetry,
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


async def handle_reaped_job(
    item: ReapedJob,
    *,
    metrics: PlatformMetrics,
    telemetry: Telemetry,
) -> None:
    attributes: dict[str, str | int] = {
        "tenant.id": str(item.tenant_id),
        "run.id": str(item.run_id),
        "job.id": str(item.job_id),
        "attempt.number": item.attempt_number,
        "reaper.action": item.action,
    }
    if item.attempt_id is not None:
        attributes["attempt.id"] = str(item.attempt_id)
    if item.previous_worker is not None:
        attributes["worker.previous.id"] = item.previous_worker

    with telemetry.start_as_current_span(
        "reaper.job.recovered",
        attributes=attributes,
        links=telemetry.links_from_traceparent(item.origin_traceparent),
    ):
        if item.action == "requeued":
            metrics.record_job_retry()
        elif item.action == "failed":
            metrics.record_job_failed()


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

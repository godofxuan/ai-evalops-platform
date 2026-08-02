from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, func, select

from app.domain.enums import JobStatus
from app.observability.metrics import PlatformMetrics
from app.persistence.database import AsyncSessionFactory
from app.persistence.orm_models import EvaluationJob, ProgressEventOutbox

_QUEUED_STATUSES = (JobStatus.QUEUED, JobStatus.RETRY_WAIT)
_RUNNING_STATUSES = (JobStatus.RUNNING, JobStatus.CANCELLING)


@dataclass(frozen=True, slots=True)
class DurableJobGauges:
    queue_depth: int
    running: int
    oldest_heartbeat_at: datetime | None

    def heartbeat_age_seconds(self, now: datetime) -> float:
        if self.oldest_heartbeat_at is None:
            return 0.0
        return max((now - self.oldest_heartbeat_at).total_seconds(), 0.0)


def build_durable_job_gauges_statement() -> Select[tuple[int, int, datetime | None]]:
    return select(
        func.count(EvaluationJob.id)
        .filter(EvaluationJob.status.in_(_QUEUED_STATUSES))
        .label("queue_depth"),
        func.count(EvaluationJob.id)
        .filter(EvaluationJob.status.in_(_RUNNING_STATUSES))
        .label("running"),
        func.min(EvaluationJob.heartbeat_at)
        .filter(EvaluationJob.status.in_(_RUNNING_STATUSES))
        .label("oldest_heartbeat_at"),
    )


def build_durable_outbox_gauges_statement() -> Select[tuple[int, datetime | None]]:
    return select(
        func.count(ProgressEventOutbox.id)
        .filter(ProgressEventOutbox.published_at.is_(None))
        .label("pending"),
        func.min(ProgressEventOutbox.created_at)
        .filter(ProgressEventOutbox.published_at.is_(None))
        .label("oldest_pending_at"),
    )


async def refresh_durable_job_gauges(
    *,
    session_factory: AsyncSessionFactory,
    metrics: PlatformMetrics,
    now: datetime,
) -> DurableJobGauges:
    async with session_factory() as session:
        row = (await session.execute(build_durable_job_gauges_statement())).one()
    gauges = DurableJobGauges(
        queue_depth=int(row.queue_depth),
        running=int(row.running),
        oldest_heartbeat_at=row.oldest_heartbeat_at,
    )
    metrics.set_job_queue_depth(gauges.queue_depth)
    metrics.set_job_running(gauges.running)
    metrics.set_worker_heartbeat_age(gauges.heartbeat_age_seconds(now))
    return gauges

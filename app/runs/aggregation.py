from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import JobStatus, RunStatus
from app.domain.run_state_machine import transition_run
from app.persistence.orm_models import AuditEvent, EvaluationJob, EvaluationRun

_TERMINAL_JOB_STATUSES = {
    JobStatus.SUCCEEDED,
    JobStatus.FAILED,
    JobStatus.CANCELLED,
}


def aggregate_run_status(
    statuses: Collection[JobStatus],
    *,
    cancellation_requested: bool,
) -> RunStatus:
    if not statuses:
        raise ValueError("Run aggregation requires at least one Job")
    status_set = set(statuses)
    all_terminal = status_set <= _TERMINAL_JOB_STATUSES

    if cancellation_requested and not all_terminal:
        return RunStatus.CANCELLING
    if all_terminal:
        if cancellation_requested and JobStatus.CANCELLED in status_set:
            return RunStatus.CANCELLED
        if status_set == {JobStatus.SUCCEEDED}:
            return RunStatus.SUCCEEDED
        if status_set == {JobStatus.FAILED}:
            return RunStatus.FAILED
        return RunStatus.PARTIALLY_SUCCEEDED
    if status_set == {JobStatus.QUEUED}:
        return RunStatus.QUEUED
    return RunStatus.RUNNING


@dataclass(frozen=True, slots=True)
class RunAggregation:
    run_id: UUID
    status: RunStatus
    total_jobs: int
    succeeded_jobs: int
    failed_jobs: int
    cancelled_jobs: int


async def aggregate_run_in_session(
    session: AsyncSession,
    *,
    run_id: UUID,
    now: datetime,
    actor: str,
) -> RunAggregation:
    run = (
        await session.execute(
            select(EvaluationRun)
            .where(EvaluationRun.id == run_id)
            .with_for_update(of=EvaluationRun)
        )
    ).scalar_one()
    rows = (
        await session.execute(
            select(EvaluationJob.status, func.count(EvaluationJob.id))
            .where(EvaluationJob.run_id == run_id)
            .group_by(EvaluationJob.status)
        )
    ).all()
    counts = {status: count for status, count in rows}
    statuses = tuple(status for status, count in counts.items() for _ in range(int(count)))
    desired_status = aggregate_run_status(
        statuses,
        cancellation_requested=run.cancel_requested_at is not None,
    )
    run.total_jobs = len(statuses)
    run.succeeded_jobs = int(counts.get(JobStatus.SUCCEEDED, 0))
    run.failed_jobs = int(counts.get(JobStatus.FAILED, 0))
    run.cancelled_jobs = int(counts.get(JobStatus.CANCELLED, 0))
    if desired_status is not run.status:
        transition = transition_run(
            run.status,
            desired_status,
            reason="job_aggregate_changed",
            actor=actor,
        )
        session.add(
            AuditEvent(
                tenant_id=run.tenant_id,
                actor_id=actor,
                action="run.status_changed",
                resource_type="evaluation_run",
                resource_id=run.id,
                metadata_json={
                    "previous": transition.previous.value,
                    "current": transition.current.value,
                    "reason": transition.reason,
                },
            )
        )
        run.status = desired_status
    if desired_status is RunStatus.RUNNING and run.started_at is None:
        run.started_at = now
    if desired_status in {
        RunStatus.SUCCEEDED,
        RunStatus.PARTIALLY_SUCCEEDED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
    }:
        run.finished_at = run.finished_at or now
    run.version += 1
    return RunAggregation(
        run_id=run.id,
        status=run.status,
        total_jobs=run.total_jobs,
        succeeded_jobs=run.succeeded_jobs,
        failed_jobs=run.failed_jobs,
        cancelled_jobs=run.cancelled_jobs,
    )

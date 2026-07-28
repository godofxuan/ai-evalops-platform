from typing import Protocol
from uuid import UUID

from sqlalchemy import select

from app.auth.principals import Principal
from app.core.clock import Clock, SystemClock
from app.domain.enums import JobStatus, RunStatus
from app.domain.job_state_machine import transition_job
from app.domain.run_state_machine import transition_run
from app.persistence.database import AsyncSessionFactory
from app.persistence.orm_models import AuditEvent, EvaluationJob, EvaluationRun
from app.runs.aggregation import aggregate_run_in_session
from app.runs.schemas import RunRead
from app.runs.service import RunNotFoundError


def planned_cancellation_target(current: JobStatus) -> JobStatus | None:
    if current in {JobStatus.QUEUED, JobStatus.RETRY_WAIT}:
        return JobStatus.CANCELLED
    if current is JobStatus.RUNNING:
        return JobStatus.CANCELLING
    return None


class CancellationService(Protocol):
    async def cancel_run(
        self,
        *,
        principal: Principal,
        run_id: UUID,
    ) -> RunRead:
        """Request tenant-scoped cooperative cancellation idempotently."""


_TERMINAL_RUN_STATUSES = {
    RunStatus.SUCCEEDED,
    RunStatus.PARTIALLY_SUCCEEDED,
    RunStatus.FAILED,
    RunStatus.CANCELLED,
}
_NONTERMINAL_JOB_STATUSES = {
    JobStatus.QUEUED,
    JobStatus.RETRY_WAIT,
    JobStatus.RUNNING,
    JobStatus.CANCELLING,
}


class SQLAlchemyCancellationService:
    def __init__(
        self,
        session_factory: AsyncSessionFactory,
        *,
        clock: Clock | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock or SystemClock()

    async def cancel_run(
        self,
        *,
        principal: Principal,
        run_id: UUID,
    ) -> RunRead:
        now = self._clock.now()
        async with self._session_factory.begin() as session:
            run = (
                await session.execute(
                    select(EvaluationRun).where(
                        EvaluationRun.id == run_id,
                        EvaluationRun.tenant_id == principal.tenant_id,
                    )
                )
            ).scalar_one_or_none()
            if run is None:
                raise RunNotFoundError
            if run.status in _TERMINAL_RUN_STATUSES:
                return _run_read(run)

            jobs = (
                (
                    await session.execute(
                        select(EvaluationJob)
                        .where(
                            EvaluationJob.run_id == run_id,
                            EvaluationJob.status.in_(_NONTERMINAL_JOB_STATUSES),
                        )
                        .order_by(EvaluationJob.id)
                        .with_for_update(of=EvaluationJob)
                    )
                )
                .scalars()
                .all()
            )
            run = (
                await session.execute(
                    select(EvaluationRun)
                    .where(
                        EvaluationRun.id == run_id,
                        EvaluationRun.tenant_id == principal.tenant_id,
                    )
                    .with_for_update(of=EvaluationRun)
                )
            ).scalar_one()
            if run.status in _TERMINAL_RUN_STATUSES:
                return _run_read(run)

            if run.status in {RunStatus.QUEUED, RunStatus.RUNNING}:
                run_transition = transition_run(
                    run.status,
                    RunStatus.CANCELLING,
                    reason="user_requested_cancel",
                    actor=str(principal.api_key_id),
                )
                session.add(
                    _audit(
                        tenant_id=principal.tenant_id,
                        actor=str(principal.api_key_id),
                        action="run.status_changed",
                        resource_type="evaluation_run",
                        resource_id=run.id,
                        metadata={
                            "previous": run_transition.previous.value,
                            "current": run_transition.current.value,
                            "reason": run_transition.reason,
                        },
                    )
                )
                run.status = run_transition.current
            run.cancel_requested_at = run.cancel_requested_at or now
            run.version += 1

            for job in jobs:
                target = planned_cancellation_target(job.status)
                if target is None:
                    continue
                transition = transition_job(
                    job.status,
                    target,
                    reason="run_cancel_requested",
                    actor=str(principal.api_key_id),
                )
                session.add(
                    _audit(
                        tenant_id=principal.tenant_id,
                        actor=str(principal.api_key_id),
                        action="job.status_changed",
                        resource_type="evaluation_job",
                        resource_id=job.id,
                        metadata={
                            "previous": transition.previous.value,
                            "current": transition.current.value,
                            "reason": transition.reason,
                        },
                    )
                )
                job.status = target
                job.cancel_requested_at = now
                job.next_attempt_at = None
                if target is JobStatus.CANCELLED:
                    job.finished_at = now
                    job.lease_owner = None
                    job.lease_expires_at = None
                    job.heartbeat_at = None
                    job.version += 1
            await session.flush()
            await aggregate_run_in_session(
                session,
                run_id=run.id,
                now=now,
                actor=str(principal.api_key_id),
            )
            return _run_read(run)


def _audit(
    *,
    tenant_id: UUID,
    actor: str,
    action: str,
    resource_type: str,
    resource_id: UUID,
    metadata: dict[str, object],
) -> AuditEvent:
    return AuditEvent(
        tenant_id=tenant_id,
        actor_id=actor,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        metadata_json=metadata,
    )


def _run_read(run: EvaluationRun) -> RunRead:
    return RunRead(
        id=run.id,
        dataset_version_id=run.dataset_version_id,
        status=run.status,
        total_jobs=run.total_jobs,
        succeeded_jobs=run.succeeded_jobs,
        failed_jobs=run.failed_jobs,
        cancelled_jobs=run.cancelled_jobs,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import Select, select

from app.core.clock import Clock, SystemClock
from app.domain.enums import AttemptOutcome, JobStatus, RunStatus
from app.domain.job_state_machine import JobTransition, transition_job
from app.jobs.retry_policy import FailureClassification, RetryPolicy
from app.persistence.database import AsyncSessionFactory
from app.persistence.orm_models import (
    AuditEvent,
    EvaluationJob,
    EvaluationRun,
    JobAttempt,
)
from app.runs.aggregation import aggregate_run_in_session


def build_expired_job_statement(
    *,
    now: datetime,
    limit: int,
) -> Select[tuple[EvaluationJob, EvaluationRun]]:
    if not 1 <= limit <= 1_000:
        raise ValueError("reaper limit must be between 1 and 1000")
    return (
        select(EvaluationJob, EvaluationRun)
        .join(EvaluationRun, EvaluationRun.id == EvaluationJob.run_id)
        .where(
            EvaluationJob.status.in_((JobStatus.RUNNING, JobStatus.CANCELLING)),
            EvaluationJob.lease_expires_at.is_not(None),
            EvaluationJob.lease_expires_at < now,
        )
        .order_by(EvaluationJob.lease_expires_at.asc(), EvaluationJob.id.asc())
        .limit(limit)
        .with_for_update(of=EvaluationJob, skip_locked=True)
    )


@dataclass(frozen=True, slots=True)
class ReapedJob:
    job_id: UUID
    run_id: UUID
    tenant_id: UUID
    previous_worker: str | None
    action: str
    status: JobStatus
    next_attempt_at: datetime | None
    attempt_id: UUID | None
    attempt_number: int
    origin_traceparent: str | None
    run_status: RunStatus | None = None


class SQLAlchemyJobReaper:
    def __init__(
        self,
        session_factory: AsyncSessionFactory,
        *,
        retry_policy: RetryPolicy,
        clock: Clock | None = None,
        reaper_id: str = "reaper",
    ) -> None:
        self._session_factory = session_factory
        self._retry_policy = retry_policy
        self._clock = clock or SystemClock()
        self._reaper_id = reaper_id

    async def reap(self, *, limit: int = 100) -> tuple[ReapedJob, ...]:
        now = self._clock.now()
        reaped: list[ReapedJob] = []
        touched_run_ids: set[UUID] = set()
        async with self._session_factory.begin() as session:
            rows = (await session.execute(build_expired_job_statement(now=now, limit=limit))).all()
            for job, run in rows:
                previous_worker = job.lease_owner
                cancellation_requested = (
                    job.status is JobStatus.CANCELLING
                    or job.cancel_requested_at is not None
                    or run.status is RunStatus.CANCELLING
                    or run.cancel_requested_at is not None
                )
                failure = FailureClassification(
                    error_code="lease_expired",
                    retryable=True,
                    upstream_status_code=None,
                    safe_message="worker lease expired before completion",
                )
                decision = self._retry_policy.decide(
                    failure,
                    attempt_number=job.attempt_count,
                    max_attempts=job.max_attempts,
                    cancellation_requested=cancellation_requested,
                )
                transitions = _reaper_transitions(
                    current=job.status,
                    cancellation_requested=cancellation_requested,
                    should_retry=decision.should_retry,
                    actor=self._reaper_id,
                )
                target_status = transitions[-1].current
                next_attempt_at = (
                    now + timedelta(seconds=decision.backoff_seconds)
                    if decision.backoff_seconds is not None
                    else None
                )
                action = (
                    "cancelled"
                    if target_status is JobStatus.CANCELLED
                    else "requeued"
                    if target_status is JobStatus.RETRY_WAIT
                    else "failed"
                )
                for transition in transitions:
                    session.add(
                        AuditEvent(
                            tenant_id=run.tenant_id,
                            actor_id=self._reaper_id,
                            action="job.lease_expired",
                            resource_type="evaluation_job",
                            resource_id=job.id,
                            metadata_json={
                                "previous": transition.previous.value,
                                "current": transition.current.value,
                                "reason": transition.reason,
                                "previous_worker": previous_worker,
                                "action": action,
                                "next_attempt_at": (
                                    None if next_attempt_at is None else next_attempt_at.isoformat()
                                ),
                            },
                        )
                    )
                attempt = (
                    await session.execute(
                        select(JobAttempt)
                        .where(
                            JobAttempt.job_id == job.id,
                            JobAttempt.finished_at.is_(None),
                        )
                        .order_by(JobAttempt.attempt_number.desc())
                        .limit(1)
                        .with_for_update()
                    )
                ).scalar_one_or_none()
                if attempt is not None:
                    attempt.finished_at = now
                    attempt.outcome = AttemptOutcome.LEASE_EXPIRED
                    attempt.retryable = decision.should_retry
                    attempt.error_code = "lease_expired"
                    attempt.error_message = failure.safe_message

                job.status = target_status
                job.next_attempt_at = next_attempt_at
                job.lease_owner = None
                job.lease_expires_at = None
                job.heartbeat_at = None
                job.last_error_code = "lease_expired"
                job.last_error_message = failure.safe_message
                job.finished_at = (
                    now if target_status in {JobStatus.FAILED, JobStatus.CANCELLED} else None
                )
                job.version += 1
                touched_run_ids.add(run.id)
                reaped.append(
                    ReapedJob(
                        job_id=job.id,
                        run_id=run.id,
                        tenant_id=run.tenant_id,
                        previous_worker=previous_worker,
                        action=action,
                        status=target_status,
                        next_attempt_at=next_attempt_at,
                        attempt_id=None if attempt is None else attempt.id,
                        attempt_number=job.attempt_count,
                        origin_traceparent=run.origin_traceparent,
                    )
                )
            await session.flush()
            run_statuses: dict[UUID, RunStatus] = {}
            for run_id in sorted(touched_run_ids, key=str):
                aggregation = await aggregate_run_in_session(
                    session,
                    run_id=run_id,
                    now=now,
                    actor=self._reaper_id,
                )
                run_statuses[run_id] = aggregation.status
        return tuple(replace(item, run_status=run_statuses[item.run_id]) for item in reaped)


def _reaper_transitions(
    *,
    current: JobStatus,
    cancellation_requested: bool,
    should_retry: bool,
    actor: str,
) -> tuple[JobTransition, ...]:
    if cancellation_requested:
        if current is JobStatus.RUNNING:
            first = transition_job(
                current,
                JobStatus.CANCELLING,
                reason="cancel_observed_after_lease_expiry",
                actor=actor,
            )
            second = transition_job(
                first.current,
                JobStatus.CANCELLED,
                reason="lease_expired_after_cancel",
                actor=actor,
            )
            return (first, second)
        return (
            transition_job(
                current,
                JobStatus.CANCELLED,
                reason="lease_expired_after_cancel",
                actor=actor,
            ),
        )
    return (
        transition_job(
            current,
            JobStatus.RETRY_WAIT if should_retry else JobStatus.FAILED,
            reason="lease_expired_retry" if should_retry else "lease_expired_exhausted",
            actor=actor,
        ),
    )

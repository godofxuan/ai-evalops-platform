from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import Select, select

from app.core.clock import Clock, SystemClock
from app.domain.enums import AttemptOutcome, JobStatus, RunStatus
from app.domain.job_state_machine import JobTransition, transition_job
from app.events.models import EventType
from app.events.outbox import enqueue_progress_event
from app.jobs.claiming import ClaimedJob
from app.jobs.heartbeat import LeaseLostError
from app.jobs.retry_policy import RetryDecision, RetryPolicy, classify_failure
from app.persistence.database import AsyncSessionFactory
from app.persistence.orm_models import (
    AuditEvent,
    EvaluationJob,
    EvaluationRun,
    JobAttempt,
)
from app.runs.aggregation import aggregate_run_in_session
from app.targets.base import TargetCancelledError


@dataclass(frozen=True, slots=True)
class FailureCommitReceipt:
    job_id: UUID
    status: JobStatus
    version: int
    retryable: bool
    error_code: str
    next_attempt_at: datetime | None
    run_status: RunStatus


def build_owned_job_for_failure_statement(
    *,
    job_id: UUID,
    run_id: UUID,
    worker_id: str,
    expected_version: int,
    now: datetime,
) -> Select[tuple[EvaluationJob, EvaluationRun]]:
    return (
        select(EvaluationJob, EvaluationRun)
        .join(EvaluationRun, EvaluationRun.id == EvaluationJob.run_id)
        .where(
            EvaluationJob.id == job_id,
            EvaluationJob.run_id == run_id,
            EvaluationJob.status.in_((JobStatus.RUNNING, JobStatus.CANCELLING)),
            EvaluationJob.lease_owner == worker_id,
            EvaluationJob.version == expected_version,
            EvaluationJob.lease_expires_at.is_not(None),
            EvaluationJob.lease_expires_at > now,
        )
        .with_for_update(of=EvaluationJob)
    )


class SQLAlchemyFailureCommitter:
    def __init__(
        self,
        session_factory: AsyncSessionFactory,
        *,
        retry_policy: RetryPolicy,
        clock: Clock | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._retry_policy = retry_policy
        self._clock = clock or SystemClock()

    async def commit_failure(
        self,
        *,
        claim: ClaimedJob,
        lease_version: int,
        error: BaseException,
    ) -> FailureCommitReceipt:
        now = self._clock.now()
        async with self._session_factory.begin() as session:
            row = (
                await session.execute(
                    build_owned_job_for_failure_statement(
                        job_id=claim.job_id,
                        run_id=claim.run_id,
                        worker_id=claim.worker_id,
                        expected_version=lease_version,
                        now=now,
                    )
                )
            ).one_or_none()
            if row is None:
                raise LeaseLostError(
                    "failure rejected because the worker no longer owns a live lease"
                )
            job, run = row
            attempt = (
                await session.execute(
                    select(JobAttempt)
                    .where(
                        JobAttempt.id == claim.attempt_id,
                        JobAttempt.job_id == claim.job_id,
                        JobAttempt.worker_id == claim.worker_id,
                        JobAttempt.finished_at.is_(None),
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if attempt is None:
                raise LeaseLostError("failure rejected because the attempt is no longer active")

            failure = classify_failure(error)
            cancellation_requested = (
                isinstance(error, TargetCancelledError)
                or job.status is JobStatus.CANCELLING
                or job.cancel_requested_at is not None
                or run.cancel_requested_at is not None
            )
            decision = self._retry_policy.decide(
                failure,
                attempt_number=job.attempt_count,
                max_attempts=job.max_attempts,
                cancellation_requested=cancellation_requested,
            )
            transitions = _failure_transitions(
                current=job.status,
                decision=decision,
                cancellation_requested=cancellation_requested,
                actor=claim.worker_id,
            )
            for transition in transitions:
                session.add(
                    _transition_audit(
                        tenant_id=claim.tenant_id,
                        job_id=job.id,
                        transition=transition,
                        attempt_id=claim.attempt_id,
                    )
                )
            target_status = transitions[-1].current
            next_attempt_at = (
                now + timedelta(seconds=decision.backoff_seconds)
                if decision.backoff_seconds is not None
                else None
            )
            job.status = target_status
            job.next_attempt_at = next_attempt_at
            job.lease_owner = None
            job.lease_expires_at = None
            job.heartbeat_at = None
            job.last_error_code = failure.error_code[:100]
            job.last_error_message = failure.safe_message[:1_000]
            job.finished_at = (
                now if target_status in {JobStatus.FAILED, JobStatus.CANCELLED} else None
            )
            job.version += 1
            attempt.finished_at = now
            attempt.outcome = (
                AttemptOutcome.CANCELLED
                if target_status is JobStatus.CANCELLED
                else AttemptOutcome.FAILED
            )
            attempt.retryable = decision.should_retry
            attempt.error_code = failure.error_code[:100]
            attempt.error_message = failure.safe_message[:1_000]
            attempt.upstream_status_code = failure.upstream_status_code
            await session.flush()
            aggregation = await aggregate_run_in_session(
                session,
                run_id=run.id,
                now=now,
                actor=claim.worker_id,
            )
            enqueue_progress_event(
                session,
                event_type=(
                    EventType.JOB_RETRIED if decision.should_retry else EventType.JOB_FAILED
                ),
                tenant_id=claim.tenant_id,
                run_id=claim.run_id,
                timestamp=now,
                payload={
                    "job_id": str(claim.job_id),
                    "case_id": claim.case_id,
                    "attempt_number": claim.attempt_number,
                    "status": target_status.value,
                },
            )
            if aggregation.status_changed and aggregation.status in {
                RunStatus.SUCCEEDED,
                RunStatus.PARTIALLY_SUCCEEDED,
                RunStatus.FAILED,
                RunStatus.CANCELLED,
            }:
                enqueue_progress_event(
                    session,
                    event_type=EventType.RUN_COMPLETED,
                    tenant_id=claim.tenant_id,
                    run_id=claim.run_id,
                    timestamp=now,
                    payload={"status": aggregation.status.value},
                )
        return FailureCommitReceipt(
            job_id=claim.job_id,
            status=target_status,
            version=job.version,
            retryable=decision.should_retry,
            error_code=failure.error_code,
            next_attempt_at=next_attempt_at,
            run_status=aggregation.status,
        )


def _failure_transitions(
    *,
    current: JobStatus,
    decision: RetryDecision,
    cancellation_requested: bool,
    actor: str,
) -> tuple[JobTransition, ...]:
    if cancellation_requested:
        if current is JobStatus.RUNNING:
            first = transition_job(
                current,
                JobStatus.CANCELLING,
                reason="cancel_observed",
                actor=actor,
            )
            second = transition_job(
                first.current,
                JobStatus.CANCELLED,
                reason="worker_stopped_after_cancel",
                actor=actor,
            )
            return (first, second)
        return (
            transition_job(
                current,
                JobStatus.CANCELLED,
                reason="worker_stopped_after_cancel",
                actor=actor,
            ),
        )
    target = JobStatus.RETRY_WAIT if decision.should_retry else JobStatus.FAILED
    return (
        transition_job(
            current,
            target,
            reason=(
                "retryable_failure"
                if target is JobStatus.RETRY_WAIT
                else "permanent_or_exhausted_failure"
            ),
            actor=actor,
        ),
    )


def _transition_audit(
    *,
    tenant_id: UUID,
    job_id: UUID,
    transition: JobTransition,
    attempt_id: UUID,
) -> AuditEvent:
    return AuditEvent(
        tenant_id=tenant_id,
        actor_id=transition.actor,
        action="job.status_changed",
        resource_type="evaluation_job",
        resource_id=job_id,
        metadata_json={
            "previous": transition.previous.value,
            "current": transition.current.value,
            "reason": transition.reason,
            "attempt_id": str(attempt_id),
        },
    )

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError

from app.core.clock import Clock, SystemClock
from app.domain.enums import AttemptOutcome, JobStatus, RunStatus
from app.domain.evaluation import EvaluationResult, TargetResult
from app.domain.job_state_machine import transition_job
from app.events.models import EventType
from app.events.outbox import enqueue_progress_event
from app.jobs.claiming import ClaimedJob
from app.jobs.heartbeat import LeaseLostError
from app.persistence.database import AsyncSessionFactory
from app.persistence.orm_models import (
    AuditEvent,
    CaseResult,
    EvaluationJob,
    EvaluationRun,
    JobAttempt,
)
from app.runs.aggregation import aggregate_run_in_session


class AttemptNotActiveError(RuntimeError):
    """The attempt referenced by a claim is absent, completed, or belongs elsewhere."""


class ResultAlreadyCommittedError(RuntimeError):
    """A final result already exists for this Job or Run/case."""


@dataclass(frozen=True, slots=True)
class ResultCommitReceipt:
    result_id: UUID
    job_id: UUID
    job_version: int
    run_status: RunStatus


def build_owned_job_for_completion_statement(
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


class SQLAlchemyResultCommitter:
    def __init__(
        self,
        session_factory: AsyncSessionFactory,
        *,
        clock: Clock | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock or SystemClock()

    async def commit_success(
        self,
        *,
        claim: ClaimedJob,
        lease_version: int,
        target_result: TargetResult,
        evaluation_result: EvaluationResult,
    ) -> ResultCommitReceipt:
        now = self._clock.now()
        result_id = uuid4()
        next_version = lease_version + 1
        try:
            async with self._session_factory.begin() as session:
                row = (
                    await session.execute(
                        build_owned_job_for_completion_statement(
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
                        "result rejected because the worker no longer owns a live lease"
                    )
                job, run = row
                transition = transition_job(
                    job.status,
                    JobStatus.SUCCEEDED,
                    reason="result_committed",
                    actor=claim.worker_id,
                )
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
                    raise AttemptNotActiveError("claim does not reference an active attempt")

                job.status = transition.current
                job.finished_at = now
                job.lease_owner = None
                job.lease_expires_at = None
                job.heartbeat_at = None
                job.version = next_version
                attempt.finished_at = now
                attempt.outcome = AttemptOutcome.SUCCEEDED
                attempt.retryable = False
                attempt.latency_ms = target_result.latency_ms
                attempt.trace_id = _trace_id(target_result)

                usage = target_result.token_usage
                session.add(
                    CaseResult(
                        id=result_id,
                        job_id=claim.job_id,
                        run_id=claim.run_id,
                        case_id=claim.case_id,
                        answer_json={"answer": target_result.answer},
                        evidence_json={
                            "citations": list(target_result.citations),
                            "sources": list(target_result.sources),
                            "trace": target_result.trace,
                        },
                        metrics_json=evaluation_result.metrics,
                        input_tokens=None if usage is None else usage.input_tokens,
                        output_tokens=None if usage is None else usage.output_tokens,
                        latency_ms=target_result.latency_ms,
                        created_at=now,
                    )
                )
                session.add(
                    AuditEvent(
                        tenant_id=claim.tenant_id,
                        actor_id=claim.worker_id,
                        action="job.status_changed",
                        resource_type="evaluation_job",
                        resource_id=claim.job_id,
                        metadata_json={
                            "previous": transition.previous.value,
                            "current": transition.current.value,
                            "reason": transition.reason,
                            "attempt_id": str(claim.attempt_id),
                            "result_id": str(result_id),
                        },
                    )
                )
                await session.flush()
                aggregation = await aggregate_run_in_session(
                    session,
                    run_id=run.id,
                    now=now,
                    actor=claim.worker_id,
                )
                enqueue_progress_event(
                    session,
                    event_type=EventType.JOB_PROGRESS,
                    tenant_id=claim.tenant_id,
                    run_id=claim.run_id,
                    timestamp=now,
                    payload={
                        "job_id": str(claim.job_id),
                        "case_id": claim.case_id,
                        "attempt_number": claim.attempt_number,
                        "status": JobStatus.SUCCEEDED.value,
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
        except IntegrityError as error:
            if _constraint_name(error) in {
                "uq_case_results_job_id",
                "uq_case_results_run_id_case_id",
            }:
                raise ResultAlreadyCommittedError from error
            raise
        return ResultCommitReceipt(
            result_id=result_id,
            job_id=claim.job_id,
            job_version=next_version,
            run_status=aggregation.status,
        )


def _trace_id(target_result: TargetResult) -> str | None:
    value = target_result.trace.get("trace_id")
    return value[:64] if isinstance(value, str) else None


def _constraint_name(error: IntegrityError) -> str | None:
    diagnostic = getattr(error.orig, "diag", None)
    value = getattr(diagnostic, "constraint_name", None)
    return value if isinstance(value, str) else None

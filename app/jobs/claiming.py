import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Select, and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import Clock, SystemClock
from app.domain.enums import JobStatus, RunStatus
from app.domain.job_state_machine import JobTransition, transition_job
from app.domain.run_state_machine import transition_run
from app.events.models import EventType
from app.events.outbox import enqueue_progress_event
from app.jobs.lease import LeasePolicy
from app.observability.metrics import PlatformMetrics
from app.persistence.database import AsyncSessionFactory
from app.persistence.orm_models import (
    AuditEvent,
    EvaluationJob,
    EvaluationRun,
    JobAttempt,
    Tenant,
)


class InvalidClaimRequest(ValueError):
    """A worker claim request has unsafe identity or batch parameters."""


_MAX_CONTENTION_RETRIES = 20
_CONTENTION_RETRY_SECONDS = 0.01


@dataclass(frozen=True, slots=True)
class ClaimedJob:
    job_id: UUID
    run_id: UUID
    tenant_id: UUID
    case_id: str
    case_payload: dict[str, Any]
    attempt_id: UUID
    attempt_number: int
    worker_id: str
    lease_expires_at: datetime
    version: int
    target_type: str
    target_config: dict[str, Any]
    target_version: str
    evaluator_type: str
    evaluator_config: dict[str, Any]
    evaluator_version: str
    run_started: bool = False
    origin_traceparent: str | None = None


def validate_claim_request(*, worker_id: str, limit: int) -> None:
    if not worker_id.strip():
        raise InvalidClaimRequest("worker_id must not be blank")
    if not 1 <= limit <= 100:
        raise InvalidClaimRequest("claim limit must be between 1 and 100")


def build_claim_candidates_statement(
    *,
    now: datetime,
    limit: int,
) -> Select[tuple[EvaluationJob, EvaluationRun, Tenant]]:
    ranked_candidates = (
        select(
            EvaluationJob.id.label("job_id"),
            func.row_number()
            .over(
                partition_by=EvaluationRun.tenant_id,
                order_by=(
                    EvaluationJob.priority.desc(),
                    EvaluationJob.created_at.asc(),
                    EvaluationJob.id.asc(),
                ),
            )
            .label("tenant_candidate_rank"),
        )
        .join(EvaluationRun, EvaluationRun.id == EvaluationJob.run_id)
        .where(_eligible_job(now), _eligible_run())
        .cte("ranked_claim_candidates")
        .prefix_with("MATERIALIZED")
    )
    return (
        select(EvaluationJob, EvaluationRun, Tenant)
        .join(ranked_candidates, ranked_candidates.c.job_id == EvaluationJob.id)
        .join(EvaluationRun, EvaluationRun.id == EvaluationJob.run_id)
        .join(Tenant, Tenant.id == EvaluationRun.tenant_id)
        .where(
            _eligible_job(now),
            _eligible_run(),
            ranked_candidates.c.tenant_candidate_rank <= limit,
        )
        .order_by(
            EvaluationJob.priority.desc(),
            ranked_candidates.c.tenant_candidate_rank.asc(),
            Tenant.last_scheduler_turn_at.asc().nulls_first(),
            EvaluationJob.created_at.asc(),
            EvaluationJob.id.asc(),
        )
        .limit(limit)
        .with_for_update(of=Tenant, skip_locked=True, key_share=True)
    )


def build_tenant_job_claim_statement(
    *,
    now: datetime,
    tenant_id: UUID,
) -> Select[tuple[EvaluationJob, EvaluationRun]]:
    return (
        select(EvaluationJob, EvaluationRun)
        .join(EvaluationRun, EvaluationRun.id == EvaluationJob.run_id)
        .where(
            EvaluationRun.tenant_id == tenant_id,
            _eligible_job(now),
            _eligible_run(),
        )
        .order_by(
            EvaluationJob.priority.desc(),
            EvaluationJob.created_at.asc(),
            EvaluationJob.id.asc(),
        )
        .limit(1)
        .with_for_update(of=EvaluationJob, skip_locked=True)
    )


def _eligible_job(now: datetime) -> Any:
    return or_(
        EvaluationJob.status == JobStatus.QUEUED,
        and_(
            EvaluationJob.status == JobStatus.RETRY_WAIT,
            EvaluationJob.next_attempt_at.is_not(None),
            EvaluationJob.next_attempt_at <= now,
        ),
    )


def _eligible_run() -> Any:
    return EvaluationRun.status.in_((RunStatus.QUEUED, RunStatus.RUNNING))


class SQLAlchemyJobClaimer:
    """Reserve a fair tenant turn, then commit each durable Job claim atomically."""

    def __init__(
        self,
        session_factory: AsyncSessionFactory,
        *,
        lease_policy: LeasePolicy,
        clock: Clock | None = None,
        metrics: PlatformMetrics | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._lease_policy = lease_policy
        self._clock = clock or SystemClock()
        self._metrics = metrics

    async def claim(self, *, worker_id: str, limit: int = 1) -> tuple[ClaimedJob, ...]:
        validate_claim_request(worker_id=worker_id, limit=limit)
        claimed_batch: list[ClaimedJob] = []
        for _batch_slot in range(limit):
            for retry_number in range(_MAX_CONTENTION_RETRIES + 1):
                eligible_at = self._clock.now()
                claims = await self._claim_once(
                    worker_id=worker_id,
                    limit=1,
                    eligible_at=eligible_at,
                )
                if claims:
                    claimed_batch.extend(claims)
                    break
                if retry_number == _MAX_CONTENTION_RETRIES or not await self._has_eligible_jobs(
                    self._clock.now()
                ):
                    return tuple(claimed_batch)
                await asyncio.sleep(_CONTENTION_RETRY_SECONDS)
            else:
                return tuple(claimed_batch)
        return tuple(claimed_batch)

    async def _has_eligible_jobs(self, now: datetime) -> bool:
        async with self._session_factory() as session:
            job_id = await session.scalar(
                select(EvaluationJob.id)
                .join(EvaluationRun, EvaluationRun.id == EvaluationJob.run_id)
                .where(_eligible_job(now), _eligible_run())
                .limit(1)
            )
        return job_id is not None

    async def _claim_once(
        self,
        *,
        worker_id: str,
        limit: int,
        eligible_at: datetime,
    ) -> tuple[ClaimedJob, ...]:
        tenant_id = await self._reserve_tenant_turn(eligible_at=eligible_at)
        if tenant_id is None:
            return ()
        if self._metrics is not None:
            self._metrics.record_tenant_turn_reserved()
        claims = await self._claim_reserved_tenant(
            worker_id=worker_id,
            tenant_id=tenant_id,
            eligible_at=eligible_at,
        )
        if not claims and self._metrics is not None:
            self._metrics.record_tenant_turn_without_job()
        return claims

    async def _reserve_tenant_turn(self, *, eligible_at: datetime) -> UUID | None:
        async with self._session_factory.begin() as session:
            row = (
                await session.execute(build_claim_candidates_statement(now=eligible_at, limit=1))
            ).first()
            if row is None:
                return None
            tenant: Tenant = row[2]
            tenant.last_scheduler_turn_at = self._clock.now()
            return tenant.id

    async def _claim_reserved_tenant(
        self,
        *,
        worker_id: str,
        tenant_id: UUID,
        eligible_at: datetime,
    ) -> tuple[ClaimedJob, ...]:
        claims: list[ClaimedJob] = []
        async with self._session_factory.begin() as session:
            rows = (
                await session.execute(
                    build_tenant_job_claim_statement(
                        now=eligible_at,
                        tenant_id=tenant_id,
                    )
                )
            ).all()
            if not rows:
                return ()
            claimed_at = self._clock.now()
            lease_expires_at = claimed_at + self._lease_policy.duration
            for job, run in rows:
                run_started_now = False
                if job.status is JobStatus.RETRY_WAIT:
                    retry_due = transition_job(
                        JobStatus.RETRY_WAIT,
                        JobStatus.QUEUED,
                        reason="retry_delay_elapsed",
                        actor=worker_id,
                    )
                    _add_job_transition_audit(
                        session=session,
                        tenant_id=run.tenant_id,
                        job_id=job.id,
                        transition=retry_due,
                    )
                    job.status = JobStatus.QUEUED

                claimed = transition_job(
                    job.status,
                    JobStatus.RUNNING,
                    reason="worker_claimed",
                    actor=worker_id,
                )
                _add_job_transition_audit(
                    session=session,
                    tenant_id=run.tenant_id,
                    job_id=job.id,
                    transition=claimed,
                )
                attempt_id = uuid4()
                next_attempt_number = job.attempt_count + 1
                next_version = job.version + 1
                job.status = claimed.current
                job.attempt_count = next_attempt_number
                job.lease_owner = worker_id
                job.lease_expires_at = lease_expires_at
                job.heartbeat_at = claimed_at
                job.next_attempt_at = None
                job.started_at = job.started_at or claimed_at
                job.version = next_version
                session.add(
                    JobAttempt(
                        id=attempt_id,
                        job_id=job.id,
                        attempt_number=next_attempt_number,
                        worker_id=worker_id,
                        started_at=claimed_at,
                    )
                )

                if run.status is RunStatus.QUEUED:
                    run_started = transition_run(
                        RunStatus.QUEUED,
                        RunStatus.RUNNING,
                        reason="first_job_claimed",
                        actor=worker_id,
                    )
                    updated_run_id = (
                        await session.execute(
                            update(EvaluationRun)
                            .where(
                                EvaluationRun.id == run.id,
                                EvaluationRun.status == RunStatus.QUEUED,
                            )
                            .values(
                                status=run_started.current,
                                started_at=claimed_at,
                                version=EvaluationRun.version + 1,
                            )
                            .returning(EvaluationRun.id)
                            .execution_options(synchronize_session=False)
                        )
                    ).scalar_one_or_none()
                    if updated_run_id is not None:
                        run_started_now = True
                        session.add(
                            AuditEvent(
                                tenant_id=run.tenant_id,
                                actor_id=worker_id,
                                action="run.status_changed",
                                resource_type="evaluation_run",
                                resource_id=run.id,
                                metadata_json={
                                    "previous": run_started.previous.value,
                                    "current": run_started.current.value,
                                    "reason": run_started.reason,
                                },
                            )
                        )

                if run_started_now:
                    enqueue_progress_event(
                        session,
                        event_type=EventType.RUN_STARTED,
                        tenant_id=run.tenant_id,
                        run_id=run.id,
                        timestamp=claimed_at,
                        payload={"status": "running"},
                    )
                enqueue_progress_event(
                    session,
                    event_type=EventType.JOB_PROGRESS,
                    tenant_id=run.tenant_id,
                    run_id=run.id,
                    timestamp=claimed_at,
                    payload={
                        "job_id": str(job.id),
                        "case_id": job.case_id,
                        "attempt_number": next_attempt_number,
                        "status": "running",
                    },
                )

                claims.append(
                    ClaimedJob(
                        job_id=job.id,
                        run_id=run.id,
                        tenant_id=run.tenant_id,
                        case_id=job.case_id,
                        case_payload=dict(job.case_payload_json),
                        attempt_id=attempt_id,
                        attempt_number=next_attempt_number,
                        worker_id=worker_id,
                        lease_expires_at=lease_expires_at,
                        version=next_version,
                        target_type=run.target_type,
                        target_config=dict(run.target_config_json),
                        target_version=run.target_version,
                        evaluator_type=run.evaluator_type,
                        evaluator_config=dict(run.evaluator_config_json),
                        evaluator_version=run.evaluator_version,
                        run_started=run_started_now,
                        origin_traceparent=run.origin_traceparent,
                    )
                )
        return tuple(claims)


def _add_job_transition_audit(
    *,
    session: AsyncSession,
    tenant_id: UUID,
    job_id: UUID,
    transition: JobTransition,
) -> None:
    session.add(
        AuditEvent(
            tenant_id=tenant_id,
            actor_id=transition.actor,
            action="job.status_changed",
            resource_type="evaluation_job",
            resource_id=job_id,
            metadata_json={
                "previous": transition.previous.value,
                "current": transition.current.value,
                "reason": transition.reason,
            },
        )
    )

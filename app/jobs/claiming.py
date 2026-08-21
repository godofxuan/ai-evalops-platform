from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Select, and_, exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
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
    SchedulerCoordination,
    Tenant,
    TenantSchedulerState,
)

SCHEDULER_COORDINATION_ID = 1
SCHEDULER_PERMIT_PENDING = "pending"
SCHEDULER_PERMIT_CONSUMED = "consumed"
SCHEDULER_PERMIT_EMPTY = "empty"


class InvalidClaimRequest(ValueError):
    """A worker claim request has unsafe identity or batch parameters."""


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
    scheduler_claim_sequence: int | None = None


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
    return _build_claim_candidates_statement(now=now, limit=limit, skip_locked=True)


def build_waiting_claim_candidate_statement(
    *,
    now: datetime,
    limit: int,
) -> Select[tuple[EvaluationJob, EvaluationRun, Tenant]]:
    """Wait for one short fair-turn row only after the nonblocking path found none."""

    return _build_claim_candidates_statement(now=now, limit=limit, skip_locked=False)


def _build_claim_candidates_statement(
    *,
    now: datetime,
    limit: int,
    skip_locked: bool,
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
        .with_for_update(of=Tenant, skip_locked=skip_locked, key_share=True)
    )


def build_tenant_job_claim_statement(
    *,
    now: datetime,
    tenant_id: UUID,
    priority: int | None = None,
    skip_locked: bool = True,
) -> Select[tuple[EvaluationJob, EvaluationRun]]:
    statement = (
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
        .with_for_update(of=EvaluationJob, skip_locked=skip_locked)
    )
    if priority is not None:
        statement = statement.where(EvaluationJob.priority == priority)
    return statement


def build_tenant_eligible_job_exists_statement(
    *,
    now: datetime,
    tenant_id: UUID,
    priority: int,
) -> Select[tuple[bool]]:
    """Distinguish a locked eligible Job from a genuinely stale round permit."""

    return select(
        exists().where(
            EvaluationJob.run_id == EvaluationRun.id,
            EvaluationRun.tenant_id == tenant_id,
            _eligible_job(now),
            _eligible_run(),
            EvaluationJob.priority == priority,
        )
    )


def build_scheduler_round_members_statement(*, now: datetime) -> Select[Any]:
    """Select one ordered fair-round membership record per highest-priority Tenant."""

    highest_priority = (
        select(func.max(EvaluationJob.priority))
        .join(EvaluationRun, EvaluationRun.id == EvaluationJob.run_id)
        .where(_eligible_job(now), _eligible_run())
        .scalar_subquery()
    )
    return (
        select(
            EvaluationRun.tenant_id.label("tenant_id"),
            highest_priority.label("round_priority"),
            func.row_number()
            .over(
                order_by=(
                    func.min(EvaluationJob.created_at).asc(),
                    EvaluationRun.tenant_id.asc(),
                )
            )
            .label("permit_order"),
        )
        .select_from(EvaluationJob)
        .join(EvaluationRun, EvaluationRun.id == EvaluationJob.run_id)
        .where(
            _eligible_job(now),
            _eligible_run(),
            EvaluationJob.priority == highest_priority,
        )
        .group_by(EvaluationRun.tenant_id)
    )


def build_pending_scheduler_permit_statement(
    *,
    skip_locked: bool,
) -> Select[tuple[TenantSchedulerState]]:
    """Lock one current-round Tenant permit, optionally using the nonblocking fast path."""

    return (
        select(TenantSchedulerState)
        .join(
            SchedulerCoordination,
            SchedulerCoordination.id == SCHEDULER_COORDINATION_ID,
        )
        .where(
            TenantSchedulerState.generation == SchedulerCoordination.active_generation,
            TenantSchedulerState.status == SCHEDULER_PERMIT_PENDING,
        )
        .order_by(TenantSchedulerState.permit_order.asc())
        .limit(1)
        .with_for_update(of=TenantSchedulerState, skip_locked=skip_locked)
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
    """Claim Jobs through bounded durable fair rounds."""

    def __init__(
        self,
        session_factory: AsyncSessionFactory,
        *,
        lease_policy: LeasePolicy,
        clock: Clock | None = None,
        metrics: PlatformMetrics | None = None,
        phase_observer: Callable[[str], None] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._lease_policy = lease_policy
        self._clock = clock or SystemClock()
        self._metrics = metrics
        self._phase_observer = phase_observer

    def _observe_claim_phase(self, phase: str) -> None:
        if self._phase_observer is not None:
            self._phase_observer(phase)

    async def claim(self, *, worker_id: str, limit: int = 1) -> tuple[ClaimedJob, ...]:
        validate_claim_request(worker_id=worker_id, limit=limit)
        self._observe_claim_phase("claim_entry")
        try:
            claimed_batch: list[ClaimedJob] = []
            for _batch_slot in range(limit):
                while True:
                    eligible_at = self._clock.now()
                    claims = await self._claim_once(
                        worker_id=worker_id,
                        limit=1,
                        eligible_at=eligible_at,
                    )
                    if claims:
                        claimed_batch.extend(claims)
                        break
                    if not await self._has_eligible_jobs(self._clock.now()):
                        return tuple(claimed_batch)
                    claims = await self._claim_once_waiting_for_turn(
                        worker_id=worker_id,
                        limit=1,
                        eligible_at=self._clock.now(),
                    )
                    if claims:
                        claimed_batch.extend(claims)
                        break
                    if not await self._has_eligible_jobs(self._clock.now()):
                        return tuple(claimed_batch)
            return tuple(claimed_batch)
        finally:
            self._observe_claim_phase("claim_return")

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
        if not await self._ensure_active_scheduler_round(eligible_at=eligible_at):
            return ()
        return await self._claim_active_scheduler_permit(
            worker_id=worker_id,
            eligible_at=eligible_at,
            skip_locked=True,
        )

    async def _claim_once_waiting_for_turn(
        self,
        *,
        worker_id: str,
        limit: int,
        eligible_at: datetime,
    ) -> tuple[ClaimedJob, ...]:
        if not await self._ensure_active_scheduler_round(eligible_at=eligible_at):
            return ()
        return await self._claim_active_scheduler_permit(
            worker_id=worker_id,
            eligible_at=eligible_at,
            skip_locked=False,
        )

    async def _ensure_active_scheduler_round(self, *, eligible_at: datetime) -> bool:
        """Create one fair round iff no current-generation permit remains pending."""

        async with self._session_factory() as session:
            has_pending = bool(
                await session.scalar(
                    select(
                        exists().where(
                            TenantSchedulerState.generation
                            == SchedulerCoordination.active_generation,
                            TenantSchedulerState.status == SCHEDULER_PERMIT_PENDING,
                            SchedulerCoordination.id == SCHEDULER_COORDINATION_ID,
                        )
                    )
                )
            )
        if has_pending:
            return True

        self._observe_claim_phase("scheduler_coordination_start")
        async with self._session_factory.begin() as session:
            coordination = (
                await session.execute(
                    select(SchedulerCoordination)
                    .where(SchedulerCoordination.id == SCHEDULER_COORDINATION_ID)
                    .with_for_update(of=SchedulerCoordination)
                )
            ).scalar_one()
            self._observe_claim_phase("scheduler_coordination_acquired")
            has_pending = bool(
                await session.scalar(
                    select(
                        exists().where(
                            TenantSchedulerState.generation == coordination.active_generation,
                            TenantSchedulerState.status == SCHEDULER_PERMIT_PENDING,
                        )
                    )
                )
            )
            if has_pending:
                return True

            members = (
                await session.execute(build_scheduler_round_members_statement(now=eligible_at))
            ).all()
            if not members:
                return False

            generation = coordination.active_generation + 1
            round_priority = int(members[0].round_priority)
            values = [
                {
                    "tenant_id": member.tenant_id,
                    "generation": generation,
                    "round_priority": round_priority,
                    "permit_order": int(member.permit_order),
                    "status": SCHEDULER_PERMIT_PENDING,
                    "version": 1,
                }
                for member in members
            ]
            insert_statement = postgresql_insert(TenantSchedulerState).values(values)
            await session.execute(
                insert_statement.on_conflict_do_update(
                    index_elements=[TenantSchedulerState.tenant_id],
                    set_={
                        "generation": generation,
                        "round_priority": round_priority,
                        "permit_order": insert_statement.excluded.permit_order,
                        "status": SCHEDULER_PERMIT_PENDING,
                        "version": TenantSchedulerState.version + 1,
                        "updated_at": func.now(),
                    },
                )
            )
            coordination.active_generation = generation
            coordination.active_priority = round_priority
            coordination.version += 1
            self._observe_claim_phase("round_created")
            self._observe_claim_phase("generation_advanced")
            return True

    async def _before_scheduler_permit_select(self, *, worker_id: str) -> None:
        """Deterministic concurrency-test seam; production intentionally does nothing."""

    async def _after_scheduler_permit_locked(
        self,
        *,
        worker_id: str,
        state: TenantSchedulerState,
    ) -> None:
        """Deterministic concurrency-test seam while the per-Tenant state is locked."""

    async def _claim_active_scheduler_permit(
        self,
        *,
        worker_id: str,
        eligible_at: datetime,
        skip_locked: bool,
    ) -> tuple[ClaimedJob, ...]:
        await self._before_scheduler_permit_select(worker_id=worker_id)
        self._observe_claim_phase("transaction_start")
        try:
            async with self._session_factory.begin() as session:
                self._observe_claim_phase("tenant_permit_select_start")
                state = await session.scalar(
                    build_pending_scheduler_permit_statement(skip_locked=skip_locked)
                )
                if state is None:
                    self._observe_claim_phase("tenant_permit_missing")
                    self._observe_claim_phase("transaction_work_complete")
                    return ()
                self._observe_claim_phase("tenant_permit_acquired")
                await self._after_scheduler_permit_locked(worker_id=worker_id, state=state)
                self._observe_claim_phase("job_row_select_start")
                rows = (
                    await session.execute(
                        build_tenant_job_claim_statement(
                            now=eligible_at,
                            tenant_id=state.tenant_id,
                            priority=state.round_priority,
                            skip_locked=skip_locked,
                        )
                    )
                ).all()
                if not rows:
                    self._observe_claim_phase("job_row_skipped")
                    has_locked_or_visible_job = bool(
                        await session.scalar(
                            build_tenant_eligible_job_exists_statement(
                                now=eligible_at,
                                tenant_id=state.tenant_id,
                                priority=state.round_priority,
                            )
                        )
                    )
                    if has_locked_or_visible_job:
                        self._observe_claim_phase("permit_retained")
                        if skip_locked:
                            self._observe_claim_phase("job_skip_locked_miss")
                    else:
                        state.status = SCHEDULER_PERMIT_EMPTY
                        state.version += 1
                        self._observe_claim_phase("tenant_permit_empty")
                    if self._metrics is not None:
                        self._metrics.record_tenant_turn_without_job()
                    self._observe_claim_phase("transaction_work_complete")
                    return ()

                self._observe_claim_phase("job_row_acquired")
                if self._metrics is not None:
                    self._metrics.record_tenant_turn_reserved()
                claims, attempts = await self._persist_claim_rows(
                    session=session,
                    rows=rows,
                    worker_id=worker_id,
                )
                self._observe_claim_phase("job_attempt_mutation_complete")
                state.status = SCHEDULER_PERMIT_CONSUMED
                state.version += 1
                self._observe_claim_phase("tenant_permit_consumed")

                # Diagnostic ordering must not serialize independent claims.
                self._observe_claim_phase("durable_sequence_start")
                sequence_value = await session.scalar(
                    select(func.nextval("scheduler_claim_receipt_seq"))
                )
                if sequence_value is None:
                    raise RuntimeError("scheduler claim sequence did not return a value")
                sequence = int(sequence_value)
                for attempt in attempts:
                    attempt.scheduler_claim_sequence = sequence
                self._observe_claim_phase("durable_sequence_allocated")
                self._observe_claim_phase("transaction_work_complete")
                return tuple(replace(claim, scheduler_claim_sequence=sequence) for claim in claims)
        finally:
            self._observe_claim_phase("transaction_complete")

    async def _claim_after_reserved_turn(
        self,
        *,
        worker_id: str,
        tenant_id: UUID,
        eligible_at: datetime,
    ) -> tuple[ClaimedJob, ...]:
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

    async def _wait_for_tenant_turn(self, *, eligible_at: datetime) -> UUID | None:
        async with self._session_factory.begin() as session:
            row = (
                await session.execute(
                    build_waiting_claim_candidate_statement(now=eligible_at, limit=1)
                )
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
            claims, _attempts = await self._persist_claim_rows(
                session=session,
                rows=rows,
                worker_id=worker_id,
            )
            return claims

    async def _persist_claim_rows(
        self,
        *,
        session: AsyncSession,
        rows: Sequence[Any],
        worker_id: str,
    ) -> tuple[tuple[ClaimedJob, ...], tuple[JobAttempt, ...]]:
        claims: list[ClaimedJob] = []
        attempts: list[JobAttempt] = []
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
            attempt = JobAttempt(
                id=attempt_id,
                job_id=job.id,
                attempt_number=next_attempt_number,
                worker_id=worker_id,
                started_at=claimed_at,
            )
            attempts.append(attempt)
            session.add(attempt)

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
        return tuple(claims), tuple(attempts)


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

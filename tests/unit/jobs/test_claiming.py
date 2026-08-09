from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy.dialects import postgresql

from app.domain.enums import JobStatus, RunStatus
from app.jobs.claiming import (
    InvalidClaimRequest,
    SQLAlchemyJobClaimer,
    build_claim_candidates_statement,
    build_pending_scheduler_permit_statement,
    build_tenant_job_claim_statement,
    build_waiting_claim_candidate_statement,
    validate_claim_request,
)
from app.jobs.lease import LeasePolicy
from app.observability.metrics import PlatformMetrics
from app.persistence.orm_models import EvaluationJob, EvaluationRun, ProgressEventOutbox, Tenant

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
TENANT_ID = UUID("00000000-0000-0000-0000-000000000201")
RUN_ID = UUID("00000000-0000-0000-0000-000000000601")
JOB_ID = UUID("00000000-0000-0000-0000-000000000701")
ORIGIN_TRACEPARENT = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"


class FixedClock:
    def now(self) -> datetime:
        return NOW


class AdvancingClock:
    def __init__(self, *values: datetime) -> None:
        self._values = iter(values)

    def now(self) -> datetime:
        return next(self._values)


class OneRowResult:
    def __init__(self, job: EvaluationJob, run: EvaluationRun, tenant: Tenant) -> None:
        self._row = (job, run, tenant)

    def first(self) -> tuple[EvaluationJob, EvaluationRun, Tenant]:
        return self._row

    def all(self) -> list[tuple[EvaluationJob, EvaluationRun]]:
        job, run, _tenant = self._row
        return [(job, run)]


class EmptyRowResult:
    def first(self) -> None:
        return None

    def all(self) -> list[tuple[EvaluationJob, EvaluationRun]]:
        return []


class OneRowSession:
    def __init__(self, job: EvaluationJob, run: EvaluationRun, tenant: Tenant) -> None:
        self._result = OneRowResult(job, run, tenant)
        self.added: list[object] = []

    async def execute(self, _statement: object) -> OneRowResult:
        return self._result

    def add(self, value: object) -> None:
        self.added.append(value)


class EmptyRowSession:
    async def execute(self, _statement: object) -> EmptyRowResult:
        return EmptyRowResult()


class EligibleProbeSession:
    async def scalar(self, _statement: object) -> UUID:
        return JOB_ID


class OneRowSessionFactory:
    def __init__(self, session: OneRowSession) -> None:
        self._session = session

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[OneRowSession]:
        yield self._session


class ContendedThenAvailableSessionFactory:
    def __init__(self, available_session: OneRowSession) -> None:
        self._available_session = available_session
        self.begin_count = 0
        self.probe_count = 0

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[EmptyRowSession | OneRowSession]:
        self.begin_count += 1
        if self.begin_count == 1:
            yield EmptyRowSession()
        else:
            yield self._available_session

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[EligibleProbeSession]:
        self.probe_count += 1
        yield EligibleProbeSession()


class ReservedThenMissingSessionFactory:
    def __init__(self, reserved_session: OneRowSession) -> None:
        self._reserved_session = reserved_session
        self.begin_count = 0

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[OneRowSession | EmptyRowSession]:
        self.begin_count += 1
        if self.begin_count == 1:
            yield self._reserved_session
        else:
            yield EmptyRowSession()


def compile_postgresql(statement: object) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_claim_candidates_use_non_key_updating_tenant_turn_and_deterministic_order() -> None:
    sql = compile_postgresql(build_claim_candidates_statement(now=NOW, limit=10))

    assert "row_number() OVER (PARTITION BY evaluation_runs.tenant_id" in sql
    assert "JOIN tenants" in sql
    assert "tenants.last_scheduler_turn_at ASC NULLS FIRST" in sql
    assert "FOR NO KEY UPDATE OF tenants SKIP LOCKED" in sql
    assert "FOR UPDATE OF tenants" not in sql
    assert "evaluation_jobs.status" in sql
    assert sql.count("evaluation_jobs.status") >= 4
    assert "evaluation_jobs.next_attempt_at" in sql
    assert "evaluation_runs.status" in sql
    assert "tenant_candidate_rank ASC" in sql
    assert "LIMIT 10" in sql


def test_waiting_fallback_preserves_lock_strength_without_skip_locked() -> None:
    sql = compile_postgresql(build_waiting_claim_candidate_statement(now=NOW, limit=1))

    assert "FOR NO KEY UPDATE OF tenants" in sql
    assert "SKIP LOCKED" not in sql
    assert "FOR UPDATE OF tenants" not in sql
    assert "LIMIT 1" in sql


def test_tenant_job_claim_skips_locked_jobs_without_locking_tenant() -> None:
    sql = compile_postgresql(build_tenant_job_claim_statement(now=NOW, tenant_id=TENANT_ID))

    assert "evaluation_runs.tenant_id" in sql
    assert "evaluation_jobs.priority DESC" in sql
    assert "FOR UPDATE OF evaluation_jobs SKIP LOCKED" in sql
    assert "FOR UPDATE OF tenants" not in sql
    assert "LIMIT 1" in sql


def test_claim_candidates_prune_tenant_ranks_that_cannot_enter_the_batch() -> None:
    sql = compile_postgresql(build_claim_candidates_statement(now=NOW, limit=10))

    assert "ranked_claim_candidates.tenant_candidate_rank <= 10" in sql


def test_claim_candidates_materialize_ranking_once_before_outer_filtering() -> None:
    sql = compile_postgresql(build_claim_candidates_statement(now=NOW, limit=10))

    assert "ranked_claim_candidates AS MATERIALIZED" in sql


async def test_claimer_copies_run_origin_traceparent_to_claim() -> None:
    tenant = Tenant(
        id=TENANT_ID,
        slug="claim-tenant",
        name="Claim tenant",
    )
    run = EvaluationRun(
        id=RUN_ID,
        tenant_id=TENANT_ID,
        status=RunStatus.RUNNING,
        target_type="mock",
        target_config_json={},
        target_version="v1",
        evaluator_type="execution",
        evaluator_config_json={},
        evaluator_version="v1",
        origin_traceparent=ORIGIN_TRACEPARENT,
    )
    job = EvaluationJob(
        id=JOB_ID,
        run_id=RUN_ID,
        case_id="case-1",
        case_payload_json={"case_id": "case-1", "question": "q"},
        status=JobStatus.QUEUED,
        attempt_count=0,
        version=1,
    )
    session = OneRowSession(job, run, tenant)
    claimer = SQLAlchemyJobClaimer(
        OneRowSessionFactory(session),  # type: ignore[arg-type]
        lease_policy=LeasePolicy(timedelta(seconds=30)),
        clock=FixedClock(),
    )

    claims = await claimer._claim_reserved_tenant(
        worker_id="worker-1",
        tenant_id=TENANT_ID,
        eligible_at=NOW,
    )

    assert len(claims) == 1
    assert claims[0].origin_traceparent == ORIGIN_TRACEPARENT
    events = [item for item in session.added if isinstance(item, ProgressEventOutbox)]
    assert len(events) == 1
    assert events[0].event_type == "job_progress"
    assert events[0].payload_json == {
        "job_id": str(JOB_ID),
        "case_id": "case-1",
        "attempt_number": 1,
        "status": "running",
    }


async def test_claim_lease_starts_after_candidate_query_completes() -> None:
    claimed_at = NOW + timedelta(seconds=20)
    tenant = Tenant(id=TENANT_ID, slug="slow-query-tenant", name="Slow query tenant")
    run = EvaluationRun(
        id=RUN_ID,
        tenant_id=TENANT_ID,
        status=RunStatus.RUNNING,
        target_type="mock",
        target_config_json={},
        target_version="v1",
        evaluator_type="execution",
        evaluator_config_json={},
        evaluator_version="v1",
    )
    job = EvaluationJob(
        id=JOB_ID,
        run_id=RUN_ID,
        case_id="case-slow-query",
        case_payload_json={"case_id": "case-slow-query"},
        status=JobStatus.QUEUED,
        attempt_count=0,
        version=1,
    )
    claimer = SQLAlchemyJobClaimer(
        OneRowSessionFactory(OneRowSession(job, run, tenant)),  # type: ignore[arg-type]
        lease_policy=LeasePolicy(timedelta(seconds=30)),
        clock=AdvancingClock(claimed_at),
    )

    claim = (
        await claimer._claim_reserved_tenant(
            worker_id="worker-slow-query",
            tenant_id=TENANT_ID,
            eligible_at=NOW,
        )
    )[0]

    assert claim.lease_expires_at == claimed_at + timedelta(seconds=30)
    assert job.heartbeat_at == claimed_at
    assert job.started_at == claimed_at


async def test_claimer_retries_when_eligible_jobs_are_temporarily_locked() -> None:
    sql = compile_postgresql(build_pending_scheduler_permit_statement(skip_locked=True))

    assert "FOR UPDATE OF tenant_scheduler_states SKIP LOCKED" in sql
    assert "tenant_scheduler_states.status = 'pending'" in sql


async def test_claimer_waits_for_one_short_turn_after_nonblocking_contention() -> None:
    sql = compile_postgresql(build_pending_scheduler_permit_statement(skip_locked=False))

    assert "FOR UPDATE OF tenant_scheduler_states" in sql
    assert "SKIP LOCKED" not in sql


async def test_claimer_records_reserved_turn_without_job_metrics() -> None:
    metrics = PlatformMetrics()
    metrics.record_tenant_turn_reserved()
    metrics.record_tenant_turn_without_job()

    rendered = metrics.render().decode("utf-8")
    assert "tenant_turn_reserved_total 1.0" in rendered
    assert "tenant_turn_without_job_total 1.0" in rendered
    assert "reservation_miss_rate 1.0" in rendered


@pytest.mark.parametrize(("worker_id", "limit"), [("", 1), ("worker-1", 0), ("worker-1", 101)])
def test_claim_request_rejects_unsafe_worker_or_batch_values(
    worker_id: str,
    limit: int,
) -> None:
    with pytest.raises(InvalidClaimRequest):
        validate_claim_request(worker_id=worker_id, limit=limit)

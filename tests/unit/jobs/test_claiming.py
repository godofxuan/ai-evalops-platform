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
    validate_claim_request,
)
from app.jobs.lease import LeasePolicy
from app.persistence.orm_models import EvaluationJob, EvaluationRun, ProgressEventOutbox, Tenant

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
TENANT_ID = UUID("00000000-0000-0000-0000-000000000201")
RUN_ID = UUID("00000000-0000-0000-0000-000000000601")
JOB_ID = UUID("00000000-0000-0000-0000-000000000701")
ORIGIN_TRACEPARENT = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"


class FixedClock:
    def now(self) -> datetime:
        return NOW


class OneRowResult:
    def __init__(self, job: EvaluationJob, run: EvaluationRun, tenant: Tenant) -> None:
        self._row = (job, run, tenant)

    def all(self) -> list[tuple[EvaluationJob, EvaluationRun, Tenant]]:
        return [self._row]


class EmptyRowResult:
    def all(self) -> list[tuple[EvaluationJob, EvaluationRun, Tenant]]:
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


def compile_postgresql(statement: object) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_claim_candidates_use_postgresql_skip_locked_and_deterministic_order() -> None:
    sql = compile_postgresql(build_claim_candidates_statement(now=NOW, limit=10))

    assert "row_number() OVER (PARTITION BY evaluation_runs.tenant_id" in sql
    assert "JOIN tenants" in sql
    assert "tenants.last_job_claimed_at ASC NULLS FIRST" in sql
    assert "FOR UPDATE OF evaluation_jobs, tenants SKIP LOCKED" in sql
    assert "evaluation_jobs.status" in sql
    assert "evaluation_jobs.next_attempt_at" in sql
    assert "evaluation_runs.status" in sql
    assert "tenant_candidate_rank ASC" in sql
    assert "LIMIT 10" in sql


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

    claims = await claimer.claim(worker_id="worker-1")

    assert len(claims) == 1
    assert claims[0].origin_traceparent == ORIGIN_TRACEPARENT
    assert tenant.last_job_claimed_at == NOW
    events = [item for item in session.added if isinstance(item, ProgressEventOutbox)]
    assert len(events) == 1
    assert events[0].event_type == "job_progress"
    assert events[0].payload_json == {
        "job_id": str(JOB_ID),
        "case_id": "case-1",
        "attempt_number": 1,
        "status": "running",
    }


async def test_claimer_retries_when_eligible_jobs_are_temporarily_locked() -> None:
    tenant = Tenant(id=TENANT_ID, slug="retry-tenant", name="Retry tenant")
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
        case_id="case-retry",
        case_payload_json={"case_id": "case-retry"},
        status=JobStatus.QUEUED,
        attempt_count=0,
        version=1,
    )
    factory = ContendedThenAvailableSessionFactory(OneRowSession(job, run, tenant))
    claimer = SQLAlchemyJobClaimer(
        factory,  # type: ignore[arg-type]
        lease_policy=LeasePolicy(timedelta(seconds=30)),
        clock=FixedClock(),
    )

    claims = await claimer.claim(worker_id="worker-retry")

    assert [claim.job_id for claim in claims] == [JOB_ID]
    assert factory.begin_count == 2
    assert factory.probe_count == 1


@pytest.mark.parametrize(("worker_id", "limit"), [("", 1), ("worker-1", 0), ("worker-1", 101)])
def test_claim_request_rejects_unsafe_worker_or_batch_values(
    worker_id: str,
    limit: int,
) -> None:
    with pytest.raises(InvalidClaimRequest):
        validate_claim_request(worker_id=worker_id, limit=limit)

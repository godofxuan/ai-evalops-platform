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
from app.persistence.orm_models import EvaluationJob, EvaluationRun, ProgressEventOutbox

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
TENANT_ID = UUID("00000000-0000-0000-0000-000000000201")
RUN_ID = UUID("00000000-0000-0000-0000-000000000601")
JOB_ID = UUID("00000000-0000-0000-0000-000000000701")
ORIGIN_TRACEPARENT = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"


class FixedClock:
    def now(self) -> datetime:
        return NOW


class OneRowResult:
    def __init__(self, job: EvaluationJob, run: EvaluationRun) -> None:
        self._row = (job, run)

    def all(self) -> list[tuple[EvaluationJob, EvaluationRun]]:
        return [self._row]


class OneRowSession:
    def __init__(self, job: EvaluationJob, run: EvaluationRun) -> None:
        self._result = OneRowResult(job, run)
        self.added: list[object] = []

    async def execute(self, _statement: object) -> OneRowResult:
        return self._result

    def add(self, value: object) -> None:
        self.added.append(value)


class OneRowSessionFactory:
    def __init__(self, session: OneRowSession) -> None:
        self._session = session

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[OneRowSession]:
        yield self._session


def compile_postgresql(statement: object) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_claim_candidates_use_postgresql_skip_locked_and_deterministic_order() -> None:
    sql = compile_postgresql(build_claim_candidates_statement(now=NOW, limit=10))

    assert "FOR UPDATE OF evaluation_jobs SKIP LOCKED" in sql
    assert "evaluation_jobs.status" in sql
    assert "evaluation_jobs.next_attempt_at" in sql
    assert "evaluation_runs.status" in sql
    assert (
        "ORDER BY evaluation_jobs.priority DESC, evaluation_jobs.created_at ASC, "
        "evaluation_jobs.id ASC" in sql
    )
    assert "LIMIT 10" in sql


async def test_claimer_copies_run_origin_traceparent_to_claim() -> None:
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
    session = OneRowSession(job, run)
    claimer = SQLAlchemyJobClaimer(
        OneRowSessionFactory(session),  # type: ignore[arg-type]
        lease_policy=LeasePolicy(timedelta(seconds=30)),
        clock=FixedClock(),
    )

    claims = await claimer.claim(worker_id="worker-1")

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


@pytest.mark.parametrize(("worker_id", "limit"), [("", 1), ("worker-1", 0), ("worker-1", 101)])
def test_claim_request_rejects_unsafe_worker_or_batch_values(
    worker_id: str,
    limit: int,
) -> None:
    with pytest.raises(InvalidClaimRequest):
        validate_claim_request(worker_id=worker_id, limit=limit)

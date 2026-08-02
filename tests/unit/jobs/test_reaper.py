from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy.dialects import postgresql

from app.domain.enums import JobStatus, RunStatus
from app.jobs.reaper import SQLAlchemyJobReaper, build_expired_job_statement
from app.jobs.retry_policy import RetryPolicy
from app.persistence.orm_models import (
    EvaluationJob,
    EvaluationRun,
    JobAttempt,
    ProgressEventOutbox,
)
from app.runs.aggregation import RunAggregation

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
TENANT_ID = UUID("00000000-0000-0000-0000-000000000201")
RUN_ID = UUID("00000000-0000-0000-0000-000000000601")
JOB_ID = UUID("00000000-0000-0000-0000-000000000701")
ATTEMPT_ID = UUID("00000000-0000-0000-0000-000000000801")
ORIGIN_TRACEPARENT = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"


class FixedClock:
    def now(self) -> datetime:
        return NOW


class RowsResult:
    def __init__(self, job: EvaluationJob, run: EvaluationRun) -> None:
        self._row = (job, run)

    def all(self) -> list[tuple[EvaluationJob, EvaluationRun]]:
        return [self._row]


class AttemptResult:
    def __init__(self, attempt: JobAttempt) -> None:
        self._attempt = attempt

    def scalar_one_or_none(self) -> JobAttempt:
        return self._attempt


class ReaperSession:
    def __init__(
        self,
        job: EvaluationJob,
        run: EvaluationRun,
        attempt: JobAttempt,
    ) -> None:
        self._results: list[object] = [RowsResult(job, run), AttemptResult(attempt)]
        self.added: list[object] = []

    async def execute(self, _statement: object) -> object:
        return self._results.pop(0)

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        return None


class ReaperSessionFactory:
    def __init__(self, session: ReaperSession) -> None:
        self._session = session

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[ReaperSession]:
        yield self._session


def test_reaper_locks_expired_running_jobs_with_skip_locked() -> None:
    sql = str(
        build_expired_job_statement(now=NOW, limit=50).compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "evaluation_jobs.lease_expires_at <" in sql
    assert "evaluation_jobs.status IN ('running', 'cancelling')" in sql
    assert "FOR UPDATE OF evaluation_jobs SKIP LOCKED" in sql
    assert "ORDER BY evaluation_jobs.lease_expires_at ASC" in sql
    assert "LIMIT 50" in sql


async def test_reaper_returns_origin_traceparent_and_expired_attempt_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = EvaluationRun(
        id=RUN_ID,
        tenant_id=TENANT_ID,
        status=RunStatus.RUNNING,
        origin_traceparent=ORIGIN_TRACEPARENT,
    )
    job = EvaluationJob(
        id=JOB_ID,
        run_id=RUN_ID,
        status=JobStatus.RUNNING,
        lease_owner="worker-1",
        lease_expires_at=NOW - timedelta(seconds=1),
        attempt_count=1,
        max_attempts=3,
        version=2,
    )
    attempt = JobAttempt(
        id=ATTEMPT_ID,
        job_id=JOB_ID,
        attempt_number=1,
        worker_id="worker-1",
        started_at=NOW - timedelta(seconds=30),
    )
    session = ReaperSession(job, run, attempt)

    async def aggregate(
        _session: object,
        *,
        run_id: UUID,
        now: datetime,
        actor: str,
    ) -> RunAggregation:
        assert run_id == RUN_ID
        assert now == NOW
        assert actor == "reaper-1"
        assert not [item for item in session.added if isinstance(item, ProgressEventOutbox)]
        return RunAggregation(
            run_id=RUN_ID,
            status=RunStatus.RUNNING,
            total_jobs=1,
            succeeded_jobs=0,
            failed_jobs=0,
            cancelled_jobs=0,
        )

    monkeypatch.setattr("app.jobs.reaper.aggregate_run_in_session", aggregate)
    reaper = SQLAlchemyJobReaper(
        ReaperSessionFactory(session),  # type: ignore[arg-type]
        retry_policy=RetryPolicy(
            base_delay_seconds=1,
            max_delay_seconds=60,
            jitter_ratio=0,
        ),
        clock=FixedClock(),
        reaper_id="reaper-1",
    )

    reaped = await reaper.reap(limit=1)

    assert len(reaped) == 1
    assert reaped[0].origin_traceparent == ORIGIN_TRACEPARENT
    assert reaped[0].attempt_id == ATTEMPT_ID
    assert reaped[0].attempt_number == 1
    events = [item for item in session.added if isinstance(item, ProgressEventOutbox)]
    assert len(events) == 1
    assert events[0].event_type == "job_retried"
    assert events[0].payload_json == {
        "job_id": str(JOB_ID),
        "status": "retry_wait",
        "source": "reaper",
    }

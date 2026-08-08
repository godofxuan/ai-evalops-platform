from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from app.auth.principals import Principal
from app.domain.enums import JobStatus, RunStatus
from app.domain.evaluation import EvaluationResult, TargetResult
from app.jobs.cancellation import SQLAlchemyCancellationService
from app.jobs.claiming import ClaimedJob
from app.jobs.failures import SQLAlchemyFailureCommitter
from app.jobs.results import SQLAlchemyResultCommitter
from app.jobs.retry_policy import RetryPolicy
from app.persistence.orm_models import (
    EvaluationJob,
    EvaluationRun,
    JobAttempt,
    ProgressEventOutbox,
)
from app.runs.aggregation import RunAggregation
from app.targets.base import TargetHTTPError

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)
TENANT_ID = UUID("00000000-0000-0000-0000-000000000201")
API_KEY_ID = UUID("00000000-0000-0000-0000-000000000101")
DATASET_VERSION_ID = UUID("00000000-0000-0000-0000-000000000401")
RUN_ID = UUID("00000000-0000-0000-0000-000000000601")
JOB_ID = UUID("00000000-0000-0000-0000-000000000701")
ATTEMPT_ID = UUID("00000000-0000-0000-0000-000000000801")


class FixedClock:
    def now(self) -> datetime:
        return NOW


class RowResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def one_or_none(self) -> object:
        return self._value


class ScalarResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value

    def scalar_one(self) -> object:
        return self._value


class ScalarCollectionResult:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def scalars(self) -> "ScalarCollectionResult":
        return self

    def all(self) -> list[object]:
        return self._values


class RecordingSession:
    def __init__(self, results: list[object]) -> None:
        self._results = results
        self.added: list[object] = []

    async def execute(self, _statement: object) -> object:
        return self._results.pop(0)

    async def scalar(self, _statement: object) -> object:
        result = self._results.pop(0)
        if not isinstance(result, ScalarResult):
            raise AssertionError("test expected a scalar result")
        return result.scalar_one_or_none()

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        return None


class RecordingSessionFactory:
    def __init__(self, session: RecordingSession) -> None:
        self._session = session

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[RecordingSession]:
        yield self._session


def _run(*, status: RunStatus = RunStatus.RUNNING) -> EvaluationRun:
    return EvaluationRun(
        id=RUN_ID,
        tenant_id=TENANT_ID,
        dataset_version_id=DATASET_VERSION_ID,
        status=status,
        total_jobs=1,
        succeeded_jobs=0,
        failed_jobs=0,
        cancelled_jobs=0,
        version=1,
        created_at=NOW - timedelta(minutes=1),
        started_at=NOW - timedelta(seconds=30),
    )


def _job(
    *,
    status: JobStatus = JobStatus.RUNNING,
    attempt_count: int = 1,
    max_attempts: int = 3,
) -> EvaluationJob:
    return EvaluationJob(
        id=JOB_ID,
        run_id=RUN_ID,
        case_id="case-1",
        case_payload_json={"case_id": "case-1", "question": "q", "metadata": {}},
        status=status,
        attempt_count=attempt_count,
        max_attempts=max_attempts,
        lease_owner="worker-1" if status is JobStatus.RUNNING else None,
        lease_expires_at=(NOW + timedelta(seconds=30)) if status is JobStatus.RUNNING else None,
        heartbeat_at=NOW if status is JobStatus.RUNNING else None,
        version=2,
    )


def _attempt(*, attempt_number: int = 1) -> JobAttempt:
    return JobAttempt(
        id=ATTEMPT_ID,
        job_id=JOB_ID,
        attempt_number=attempt_number,
        worker_id="worker-1",
        started_at=NOW - timedelta(seconds=10),
    )


def _claim(*, attempt_number: int = 1) -> ClaimedJob:
    return ClaimedJob(
        job_id=JOB_ID,
        run_id=RUN_ID,
        tenant_id=TENANT_ID,
        case_id="case-1",
        case_payload={"case_id": "case-1", "question": "q", "metadata": {}},
        attempt_id=ATTEMPT_ID,
        attempt_number=attempt_number,
        worker_id="worker-1",
        lease_expires_at=NOW + timedelta(seconds=30),
        version=2,
        target_type="mock",
        target_config={},
        target_version="v1",
        evaluator_type="execution",
        evaluator_config={},
        evaluator_version="v1",
    )


def _outbox_events(session: RecordingSession) -> list[ProgressEventOutbox]:
    return [item for item in session.added if isinstance(item, ProgressEventOutbox)]


async def test_success_commits_progress_and_terminal_events_in_state_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run()
    session = RecordingSession(
        [
            ScalarResult(TENANT_ID),
            ScalarResult(RUN_ID),
            RowResult((_job(), run)),
            ScalarResult(_attempt()),
        ]
    )

    async def aggregate(*_args: object, **_kwargs: object) -> RunAggregation:
        return RunAggregation(
            run_id=RUN_ID,
            status=RunStatus.SUCCEEDED,
            total_jobs=1,
            succeeded_jobs=1,
            failed_jobs=0,
            cancelled_jobs=0,
            status_changed=True,
        )

    monkeypatch.setattr("app.jobs.results.aggregate_run_in_session", aggregate)
    committer = SQLAlchemyResultCommitter(
        RecordingSessionFactory(session),  # type: ignore[arg-type]
        clock=FixedClock(),
    )

    await committer.commit_success(
        claim=_claim(),
        lease_version=2,
        target_result=TargetResult(
            answer="answer",
            citations=(),
            sources=(),
            trace={},
            token_usage=None,
            latency_ms=10,
        ),
        evaluation_result=EvaluationResult(metrics={"score": 1.0}),
    )

    events = _outbox_events(session)
    assert [event.event_type for event in events] == ["job_progress", "run_completed"]
    assert events[0].payload_json == {
        "job_id": str(JOB_ID),
        "case_id": "case-1",
        "attempt_number": 1,
        "status": "succeeded",
    }
    assert events[1].payload_json == {"status": "succeeded"}


@pytest.mark.parametrize(
    ("attempt_count", "max_attempts", "run_status", "status_changed", "expected_types"),
    [
        (1, 3, RunStatus.RUNNING, False, ["job_retried"]),
        (3, 3, RunStatus.FAILED, True, ["job_failed", "run_completed"]),
    ],
)
async def test_failure_commits_retry_or_failure_event_in_state_transaction(
    monkeypatch: pytest.MonkeyPatch,
    attempt_count: int,
    max_attempts: int,
    run_status: RunStatus,
    status_changed: bool,
    expected_types: list[str],
) -> None:
    run = _run()
    session = RecordingSession(
        [
            RowResult(
                (
                    _job(attempt_count=attempt_count, max_attempts=max_attempts),
                    run,
                )
            ),
            ScalarResult(_attempt(attempt_number=attempt_count)),
        ]
    )

    async def aggregate(*_args: object, **_kwargs: object) -> RunAggregation:
        return RunAggregation(
            run_id=RUN_ID,
            status=run_status,
            total_jobs=1,
            succeeded_jobs=0,
            failed_jobs=int(run_status is RunStatus.FAILED),
            cancelled_jobs=0,
            status_changed=status_changed,
        )

    monkeypatch.setattr("app.jobs.failures.aggregate_run_in_session", aggregate)
    committer = SQLAlchemyFailureCommitter(
        RecordingSessionFactory(session),  # type: ignore[arg-type]
        retry_policy=RetryPolicy(
            base_delay_seconds=1,
            max_delay_seconds=60,
            jitter_ratio=0,
        ),
        clock=FixedClock(),
    )

    receipt = await committer.commit_failure(
        claim=_claim(attempt_number=attempt_count),
        lease_version=2,
        error=TargetHTTPError(500),
    )

    events = _outbox_events(session)
    assert [event.event_type for event in events] == expected_types
    assert events[0].payload_json == {
        "job_id": str(JOB_ID),
        "case_id": "case-1",
        "attempt_number": attempt_count,
        "status": receipt.status.value,
    }
    if status_changed:
        assert events[1].payload_json == {"status": run_status.value}


async def test_cancellation_commits_terminal_event_in_state_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run()
    job = _job(status=JobStatus.QUEUED)
    session = RecordingSession(
        [
            ScalarResult(run),
            ScalarCollectionResult([job]),
            ScalarResult(run),
        ]
    )

    async def aggregate(*_args: object, **_kwargs: object) -> RunAggregation:
        run.status = RunStatus.CANCELLED
        run.cancelled_jobs = 1
        run.finished_at = NOW
        return RunAggregation(
            run_id=RUN_ID,
            status=RunStatus.CANCELLED,
            total_jobs=1,
            succeeded_jobs=0,
            failed_jobs=0,
            cancelled_jobs=1,
            status_changed=True,
        )

    monkeypatch.setattr("app.jobs.cancellation.aggregate_run_in_session", aggregate)
    service = SQLAlchemyCancellationService(
        RecordingSessionFactory(session),  # type: ignore[arg-type]
        clock=FixedClock(),
    )

    await service.cancel_run(
        principal=Principal(
            tenant_id=TENANT_ID,
            api_key_id=API_KEY_ID,
            key_prefix="evk_test",
        ),
        run_id=RUN_ID,
    )

    events = _outbox_events(session)
    assert [event.event_type for event in events] == ["run_completed"]
    assert events[0].payload_json == {"status": "cancelled"}


async def test_nonterminal_cancellation_commits_progress_event_in_state_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run()
    job = _job(status=JobStatus.RUNNING)
    session = RecordingSession(
        [
            ScalarResult(run),
            ScalarCollectionResult([job]),
            ScalarResult(run),
        ]
    )

    async def aggregate(*_args: object, **_kwargs: object) -> RunAggregation:
        return RunAggregation(
            run_id=RUN_ID,
            status=RunStatus.CANCELLING,
            total_jobs=1,
            succeeded_jobs=0,
            failed_jobs=0,
            cancelled_jobs=0,
            status_changed=False,
        )

    monkeypatch.setattr("app.jobs.cancellation.aggregate_run_in_session", aggregate)
    service = SQLAlchemyCancellationService(
        RecordingSessionFactory(session),  # type: ignore[arg-type]
        clock=FixedClock(),
    )

    await service.cancel_run(
        principal=Principal(
            tenant_id=TENANT_ID,
            api_key_id=API_KEY_ID,
            key_prefix="evk_test",
        ),
        run_id=RUN_ID,
    )

    events = _outbox_events(session)
    assert [event.event_type for event in events] == ["job_progress"]
    assert events[0].payload_json == {
        "status": "cancelling",
        "source": "cancel_request",
    }

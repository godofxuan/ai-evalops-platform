from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.domain.enums import AttemptOutcome, JobStatus
from app.persistence.orm_models import CaseResult, EvaluationJob, JobAttempt


@pytest.fixture
def accepted_rows() -> tuple[EvaluationJob, CaseResult, JobAttempt]:
    job_id, run_id, attempt_id = uuid4(), uuid4(), uuid4()
    now = datetime(2026, 9, 7, tzinfo=UTC)
    job = EvaluationJob(
        id=job_id,
        run_id=run_id,
        case_id="q1",
        status=JobStatus.SUCCEEDED,
        attempt_count=2,
        version=7,
    )
    result = CaseResult(
        id=uuid4(),
        job_id=job_id,
        run_id=run_id,
        case_id="q1",
        accepted_attempt_id=attempt_id,
        metrics_json={"product_observation": {"answer": "accepted answer"}},
    )
    attempt = JobAttempt(
        id=attempt_id,
        job_id=job_id,
        attempt_number=2,
        outcome=AttemptOutcome.SUCCEEDED,
        started_at=now,
        finished_at=now,
    )
    return job, result, attempt


def test_exported_success_uses_accepted_attempt_identity_and_detaches_metrics(
    accepted_rows,
) -> None:
    from app.product_experiments.result_snapshot import freeze_durable_job

    job, result, attempt = accepted_rows
    frozen = freeze_durable_job(job, result, attempt)
    assert frozen["job_id"] == str(job.id)
    assert frozen["accepted_attempt_id"] == str(attempt.id)
    assert frozen["accepted_attempt_number"] == 2
    result.metrics_json["product_observation"]["answer"] = "changed after read"
    assert frozen["metrics"]["product_observation"]["answer"] == "accepted answer"


@pytest.mark.parametrize(
    "corruption",
    [
        "legacy",
        "other_job",
        "other_run",
        "other_case",
        "old_attempt",
        "failed_attempt",
        "unfinished",
        "wrong_id",
    ],
)
def test_invalid_accepted_identity_cannot_be_exported(accepted_rows, corruption) -> None:
    from app.product_experiments.result_snapshot import (
        ResultSnapshotIntegrityError,
        freeze_durable_job,
    )

    job, result, attempt = accepted_rows
    if corruption == "legacy":
        result.accepted_attempt_id = None
    elif corruption == "other_job":
        attempt.job_id = uuid4()
    elif corruption == "other_run":
        result.run_id = uuid4()
    elif corruption == "other_case":
        result.case_id = "other"
    elif corruption == "old_attempt":
        attempt.attempt_number = 1
    elif corruption == "failed_attempt":
        attempt.outcome = AttemptOutcome.FAILED
    elif corruption == "unfinished":
        attempt.finished_at = None
    else:
        attempt.id = uuid4()
    with pytest.raises(ResultSnapshotIntegrityError):
        freeze_durable_job(job, result, attempt)


@pytest.mark.parametrize("status", list(JobStatus))
def test_non_success_rows_are_preserved_or_rejected_not_silently_dropped(
    accepted_rows, status
) -> None:
    from app.product_experiments.result_snapshot import (
        ExperimentNotTerminalError,
        ResultSnapshotIntegrityError,
        freeze_durable_job,
    )

    job, _, _ = accepted_rows
    job.status = status
    if status in {JobStatus.FAILED, JobStatus.CANCELLED}:
        frozen = freeze_durable_job(job, None, None)
        assert frozen["job_status"] == status.value and frozen["metrics"] is None
    else:
        error = (
            ResultSnapshotIntegrityError
            if status == JobStatus.SUCCEEDED
            else ExperimentNotTerminalError
        )
        with pytest.raises(error):
            freeze_durable_job(job, None, None)


def test_failed_job_keeps_safe_reason_without_private_error_message(accepted_rows) -> None:
    from app.product_experiments.result_snapshot import freeze_durable_job

    job, _, _ = accepted_rows
    job.status = JobStatus.FAILED
    job.last_error_code = "target_timeout"
    job.last_error_message = "PRIVATE_UPSTREAM_PAYLOAD"
    frozen = freeze_durable_job(job, None, None)
    assert frozen["error_code"] == "target_timeout"
    assert "PRIVATE_UPSTREAM_PAYLOAD" not in str(frozen)

import pytest

from app.domain.enums import JobStatus, RunStatus
from app.runs.aggregation import aggregate_run_status


@pytest.mark.parametrize(
    ("statuses", "cancel_requested", "expected"),
    [
        ((JobStatus.QUEUED, JobStatus.QUEUED), False, RunStatus.QUEUED),
        ((JobStatus.RUNNING, JobStatus.QUEUED), False, RunStatus.RUNNING),
        ((JobStatus.SUCCEEDED, JobStatus.SUCCEEDED), False, RunStatus.SUCCEEDED),
        ((JobStatus.FAILED, JobStatus.FAILED), False, RunStatus.FAILED),
        (
            (JobStatus.SUCCEEDED, JobStatus.FAILED),
            False,
            RunStatus.PARTIALLY_SUCCEEDED,
        ),
        (
            (JobStatus.RUNNING, JobStatus.CANCELLED),
            True,
            RunStatus.CANCELLING,
        ),
        (
            (JobStatus.SUCCEEDED, JobStatus.CANCELLED),
            True,
            RunStatus.CANCELLED,
        ),
    ],
)
def test_run_aggregation_is_a_pure_explicit_rule(
    statuses: tuple[JobStatus, ...],
    cancel_requested: bool,
    expected: RunStatus,
) -> None:
    assert aggregate_run_status(statuses, cancellation_requested=cancel_requested) is expected


def test_run_aggregation_rejects_empty_runs() -> None:
    with pytest.raises(ValueError, match="at least one Job"):
        aggregate_run_status((), cancellation_requested=False)

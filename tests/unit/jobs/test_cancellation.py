import pytest

from app.domain.enums import JobStatus
from app.jobs.cancellation import planned_cancellation_target


@pytest.mark.parametrize(
    ("current", "expected"),
    [
        (JobStatus.QUEUED, JobStatus.CANCELLED),
        (JobStatus.RETRY_WAIT, JobStatus.CANCELLED),
        (JobStatus.RUNNING, JobStatus.CANCELLING),
        (JobStatus.CANCELLING, None),
        (JobStatus.SUCCEEDED, None),
        (JobStatus.FAILED, None),
        (JobStatus.CANCELLED, None),
    ],
)
def test_job_cancellation_plan_preserves_terminal_results(
    current: JobStatus,
    expected: JobStatus | None,
) -> None:
    assert planned_cancellation_target(current) is expected

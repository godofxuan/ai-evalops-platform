import pytest

from app.domain.enums import JobStatus
from app.domain.job_state_machine import InvalidJobStateTransition, transition_job


def test_queued_job_can_transition_to_running_with_audit_context() -> None:
    transition = transition_job(
        JobStatus.QUEUED,
        JobStatus.RUNNING,
        reason="worker_claimed",
        actor="worker-1",
    )

    assert transition.previous is JobStatus.QUEUED
    assert transition.current is JobStatus.RUNNING
    assert transition.reason == "worker_claimed"
    assert transition.actor == "worker-1"


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (JobStatus.QUEUED, JobStatus.CANCELLED),
        (JobStatus.RUNNING, JobStatus.SUCCEEDED),
        (JobStatus.RUNNING, JobStatus.RETRY_WAIT),
        (JobStatus.RUNNING, JobStatus.FAILED),
        (JobStatus.RUNNING, JobStatus.CANCELLING),
        (JobStatus.RETRY_WAIT, JobStatus.QUEUED),
        (JobStatus.RETRY_WAIT, JobStatus.CANCELLED),
        (JobStatus.CANCELLING, JobStatus.CANCELLED),
        (JobStatus.CANCELLING, JobStatus.SUCCEEDED),
        (JobStatus.CANCELLING, JobStatus.FAILED),
    ],
)
def test_explicit_job_state_graph_allows_documented_transitions(
    current: JobStatus,
    target: JobStatus,
) -> None:
    transition = transition_job(
        current,
        target,
        reason="documented_transition",
        actor="system",
    )

    assert transition.previous is current
    assert transition.current is target


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (JobStatus.SUCCEEDED, JobStatus.RUNNING),
        (JobStatus.CANCELLED, JobStatus.RUNNING),
        (JobStatus.FAILED, JobStatus.SUCCEEDED),
        (JobStatus.QUEUED, JobStatus.SUCCEEDED),
        (JobStatus.RETRY_WAIT, JobStatus.SUCCEEDED),
    ],
)
def test_explicit_job_state_graph_rejects_documented_illegal_transitions(
    current: JobStatus,
    target: JobStatus,
) -> None:
    with pytest.raises(InvalidJobStateTransition, match="illegal Job transition"):
        transition_job(
            current,
            target,
            reason="invalid_transition_probe",
            actor="test",
        )


@pytest.mark.parametrize(("reason", "actor"), [("", "worker-1"), ("claimed", " ")])
def test_job_transition_requires_audit_context(reason: str, actor: str) -> None:
    with pytest.raises(ValueError, match="reason and actor"):
        transition_job(
            JobStatus.QUEUED,
            JobStatus.RUNNING,
            reason=reason,
            actor=actor,
        )

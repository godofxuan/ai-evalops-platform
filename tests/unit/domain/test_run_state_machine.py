import pytest

from app.domain.enums import RunStatus
from app.domain.run_state_machine import InvalidRunStateTransition, transition_run


def test_queued_run_can_transition_to_running_with_audit_context() -> None:
    transition = transition_run(
        RunStatus.QUEUED,
        RunStatus.RUNNING,
        reason="first_job_claimed",
        actor="worker-1",
    )

    assert transition.previous is RunStatus.QUEUED
    assert transition.current is RunStatus.RUNNING
    assert transition.reason == "first_job_claimed"
    assert transition.actor == "worker-1"


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (RunStatus.QUEUED, RunStatus.CANCELLING),
        (RunStatus.RUNNING, RunStatus.SUCCEEDED),
        (RunStatus.RUNNING, RunStatus.PARTIALLY_SUCCEEDED),
        (RunStatus.RUNNING, RunStatus.FAILED),
        (RunStatus.RUNNING, RunStatus.CANCELLING),
        (RunStatus.CANCELLING, RunStatus.CANCELLED),
        (RunStatus.CANCELLING, RunStatus.SUCCEEDED),
        (RunStatus.CANCELLING, RunStatus.PARTIALLY_SUCCEEDED),
        (RunStatus.CANCELLING, RunStatus.FAILED),
    ],
)
def test_explicit_run_state_graph_allows_documented_aggregation_transitions(
    current: RunStatus,
    target: RunStatus,
) -> None:
    transition = transition_run(
        current,
        target,
        reason="aggregate_changed",
        actor="run_aggregator",
    )

    assert transition.previous is current
    assert transition.current is target


def test_terminal_run_cannot_be_reopened() -> None:
    with pytest.raises(InvalidRunStateTransition, match="illegal Run transition"):
        transition_run(
            RunStatus.SUCCEEDED,
            RunStatus.RUNNING,
            reason="invalid_reopen",
            actor="test",
        )


def test_run_transition_requires_audit_context() -> None:
    with pytest.raises(ValueError, match="reason and actor"):
        transition_run(
            RunStatus.QUEUED,
            RunStatus.RUNNING,
            reason=" ",
            actor="worker-1",
        )

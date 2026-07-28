from dataclasses import dataclass

from app.domain.enums import RunStatus


class InvalidRunStateTransition(ValueError):
    """The requested Run transition is outside the explicit state graph."""


@dataclass(frozen=True, slots=True)
class RunTransition:
    previous: RunStatus
    current: RunStatus
    reason: str
    actor: str


_ALLOWED_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.QUEUED: frozenset({RunStatus.RUNNING, RunStatus.CANCELLING}),
    RunStatus.RUNNING: frozenset(
        {
            RunStatus.SUCCEEDED,
            RunStatus.PARTIALLY_SUCCEEDED,
            RunStatus.FAILED,
            RunStatus.CANCELLING,
        }
    ),
    RunStatus.CANCELLING: frozenset(
        {
            RunStatus.CANCELLED,
            RunStatus.SUCCEEDED,
            RunStatus.PARTIALLY_SUCCEEDED,
            RunStatus.FAILED,
        }
    ),
    RunStatus.SUCCEEDED: frozenset(),
    RunStatus.PARTIALLY_SUCCEEDED: frozenset(),
    RunStatus.FAILED: frozenset(),
    RunStatus.CANCELLED: frozenset(),
}


def transition_run(
    current: RunStatus,
    target: RunStatus,
    *,
    reason: str,
    actor: str,
) -> RunTransition:
    if not reason.strip() or not actor.strip():
        raise ValueError("state transition reason and actor must not be blank")
    if target not in _ALLOWED_TRANSITIONS.get(current, frozenset()):
        raise InvalidRunStateTransition(f"illegal Run transition: {current} -> {target}")
    return RunTransition(
        previous=current,
        current=target,
        reason=reason,
        actor=actor,
    )

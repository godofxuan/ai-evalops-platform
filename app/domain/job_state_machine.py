from dataclasses import dataclass

from app.domain.enums import JobStatus


class InvalidJobStateTransition(ValueError):
    """The requested Job transition is outside the explicit state graph."""


@dataclass(frozen=True, slots=True)
class JobTransition:
    previous: JobStatus
    current: JobStatus
    reason: str
    actor: str


_ALLOWED_TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.QUEUED: frozenset({JobStatus.RUNNING, JobStatus.CANCELLED}),
    JobStatus.RUNNING: frozenset(
        {
            JobStatus.SUCCEEDED,
            JobStatus.RETRY_WAIT,
            JobStatus.FAILED,
            JobStatus.CANCELLING,
        }
    ),
    JobStatus.RETRY_WAIT: frozenset({JobStatus.QUEUED, JobStatus.CANCELLED}),
    JobStatus.CANCELLING: frozenset(
        {
            JobStatus.CANCELLED,
            JobStatus.SUCCEEDED,
            JobStatus.FAILED,
        }
    ),
    JobStatus.SUCCEEDED: frozenset(),
    JobStatus.FAILED: frozenset(),
    JobStatus.CANCELLED: frozenset(),
}


def transition_job(
    current: JobStatus,
    target: JobStatus,
    *,
    reason: str,
    actor: str,
) -> JobTransition:
    if not reason.strip() or not actor.strip():
        raise ValueError("state transition reason and actor must not be blank")
    if target not in _ALLOWED_TRANSITIONS.get(current, frozenset()):
        raise InvalidJobStateTransition(f"illegal Job transition: {current} -> {target}")
    return JobTransition(
        previous=current,
        current=target,
        reason=reason,
        actor=actor,
    )

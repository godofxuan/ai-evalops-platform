"""Time at the locked lease authorization point, not transaction/request start."""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import Clock
from app.domain.enums import JobStatus
from app.persistence.orm_models import EvaluationJob


async def lease_authorization_time(session: AsyncSession, clock: Clock | None) -> datetime:
    """Call after acquiring every row lock needed by the lease decision.

    Production uses PostgreSQL's wall clock. An explicitly injected clock is a
    deterministic test seam; the production runtime does not inject one.
    CURRENT_TIMESTAMP/now() are transaction-start times and are not suitable.
    """
    if clock is not None:
        return clock.now()
    value = await session.scalar(select(func.clock_timestamp()))
    if not isinstance(value, datetime):
        raise RuntimeError("database lease clock did not return a timestamp")
    return value


def owns_live_lease(
    job: EvaluationJob, *, worker_id: str, expected_version: int, now: datetime
) -> bool:
    """Check an already locked Job; equality at expiry is not an active lease."""
    return (
        job.status in (JobStatus.RUNNING, JobStatus.CANCELLING)
        and job.lease_owner == worker_id
        and job.version == expected_version
        and job.lease_expires_at is not None
        and job.lease_expires_at > now
    )


def lease_rejection_reason(
    job: EvaluationJob | None, *, worker_id: str, expected_version: int, now: datetime
) -> str | None:
    """Classify the locked observation using bounded, non-sensitive reasons."""
    if job is None:
        return "not_found"
    if job.status not in (JobStatus.RUNNING, JobStatus.CANCELLING):
        return "state"
    if job.lease_owner != worker_id:
        return "owner"
    if job.version != expected_version:
        return "version"
    if job.lease_expires_at is None:
        return "missing_expiry"
    if job.lease_expires_at <= now:
        return "expired"
    return None

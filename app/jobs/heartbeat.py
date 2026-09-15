from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import Update, select, update

from app.core.clock import Clock
from app.domain.enums import JobStatus
from app.jobs.authorization import lease_authorization_time
from app.persistence.database import AsyncSessionFactory
from app.persistence.orm_models import EvaluationJob


class InvalidHeartbeatRequest(ValueError):
    """Heartbeat identity, version, or duration is invalid."""


class LeaseLostError(RuntimeError):
    """The worker no longer owns a live lease at the expected version."""


@dataclass(frozen=True, slots=True)
class HeartbeatReceipt:
    job_id: UUID
    worker_id: str
    version: int
    lease_expires_at: datetime
    cancellation_requested: bool


def validate_heartbeat_request(
    *,
    worker_id: str,
    expected_version: int,
    lease_duration: timedelta,
) -> None:
    if not worker_id.strip():
        raise InvalidHeartbeatRequest("worker_id must not be blank")
    if expected_version <= 0:
        raise InvalidHeartbeatRequest("expected_version must be positive")
    if lease_duration <= timedelta(0):
        raise InvalidHeartbeatRequest("lease_duration must be positive")


def build_heartbeat_statement(
    *,
    job_id: UUID,
    worker_id: str,
    expected_version: int,
    now: datetime,
    lease_duration: timedelta,
) -> Update:
    return (
        update(EvaluationJob)
        .where(
            EvaluationJob.id == job_id,
            EvaluationJob.status.in_((JobStatus.RUNNING, JobStatus.CANCELLING)),
            EvaluationJob.lease_owner == worker_id,
            EvaluationJob.version == expected_version,
            EvaluationJob.lease_expires_at.is_not(None),
            EvaluationJob.lease_expires_at > now,
        )
        .values(
            heartbeat_at=now,
            lease_expires_at=now + lease_duration,
            version=EvaluationJob.version + 1,
        )
        .returning(
            EvaluationJob.version,
            EvaluationJob.lease_expires_at,
            EvaluationJob.cancel_requested_at,
        )
    )


class SQLAlchemyHeartbeatService:
    def __init__(
        self,
        session_factory: AsyncSessionFactory,
        *,
        lease_duration: timedelta,
        clock: Clock | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._lease_duration = lease_duration
        self._clock = clock

    async def heartbeat(
        self,
        *,
        job_id: UUID,
        worker_id: str,
        expected_version: int,
    ) -> HeartbeatReceipt:
        validate_heartbeat_request(
            worker_id=worker_id,
            expected_version=expected_version,
            lease_duration=self._lease_duration,
        )
        async with self._session_factory.begin() as session:
            # Lock before reading time; UPDATE predicates alone may precede a wait.
            await session.execute(
                select(EvaluationJob.id)
                .where(EvaluationJob.id == job_id)
                .with_for_update(of=EvaluationJob, key_share=True)
            )
            now = await lease_authorization_time(session, self._clock)
            row = (
                await session.execute(
                    build_heartbeat_statement(
                        job_id=job_id,
                        worker_id=worker_id,
                        expected_version=expected_version,
                        now=now,
                        lease_duration=self._lease_duration,
                    )
                )
            ).one_or_none()
        if row is None:
            raise LeaseLostError(
                "heartbeat rejected because lease owner, version, state, or expiry changed"
            )
        return HeartbeatReceipt(
            job_id=job_id,
            worker_id=worker_id,
            version=row[0],
            lease_expires_at=row[1],
            cancellation_requested=row[2] is not None,
        )

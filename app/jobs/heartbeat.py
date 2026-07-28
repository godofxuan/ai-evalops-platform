from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import Update, update

from app.core.clock import Clock, SystemClock
from app.domain.enums import JobStatus
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
            EvaluationJob.status == JobStatus.RUNNING,
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
        .returning(EvaluationJob.version, EvaluationJob.lease_expires_at)
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
        self._clock = clock or SystemClock()

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
        now = self._clock.now()
        async with self._session_factory.begin() as session:
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
        )

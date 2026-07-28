from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy.dialects import postgresql

from app.jobs.heartbeat import (
    InvalidHeartbeatRequest,
    build_heartbeat_statement,
    validate_heartbeat_request,
)

JOB_ID = UUID("00000000-0000-0000-0000-000000000701")
NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


def compile_postgresql(statement: object) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_heartbeat_is_a_versioned_owner_guarded_conditional_update() -> None:
    sql = compile_postgresql(
        build_heartbeat_statement(
            job_id=JOB_ID,
            worker_id="worker-1",
            expected_version=7,
            now=NOW,
            lease_duration=timedelta(seconds=30),
        )
    )

    assert "UPDATE evaluation_jobs SET" in sql
    assert "evaluation_jobs.status = 'running'" in sql
    assert "evaluation_jobs.lease_owner = 'worker-1'" in sql
    assert "evaluation_jobs.version = 7" in sql
    assert "evaluation_jobs.lease_expires_at >" in sql
    assert "RETURNING evaluation_jobs.version, evaluation_jobs.lease_expires_at" in sql


@pytest.mark.parametrize(
    ("worker_id", "expected_version", "lease_seconds"),
    [("", 1, 30), ("worker-1", 0, 30), ("worker-1", 1, 0)],
)
def test_heartbeat_rejects_invalid_lease_identity_or_duration(
    worker_id: str,
    expected_version: int,
    lease_seconds: int,
) -> None:
    with pytest.raises(InvalidHeartbeatRequest):
        validate_heartbeat_request(
            worker_id=worker_id,
            expected_version=expected_version,
            lease_duration=timedelta(seconds=lease_seconds),
        )

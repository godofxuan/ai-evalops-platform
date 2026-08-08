from uuid import UUID

import pytest
from sqlalchemy.dialects import postgresql

from app.domain.enums import JobStatus
from app.jobs.cancellation import (
    build_tenant_key_share_for_cancellation_statement,
    planned_cancellation_target,
)

TENANT_ID = UUID("00000000-0000-0000-0000-000000000201")


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


def test_cancellation_has_explicit_tenant_key_share_statement() -> None:
    sql = str(
        build_tenant_key_share_for_cancellation_statement(tenant_id=TENANT_ID).compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "WHERE tenants.id" in sql
    assert "FOR KEY SHARE OF tenants" in sql

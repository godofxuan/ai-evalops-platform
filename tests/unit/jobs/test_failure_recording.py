from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.dialects import postgresql

from app.jobs.failures import build_owned_job_for_failure_statement

JOB_ID = UUID("00000000-0000-0000-0000-000000000701")
RUN_ID = UUID("00000000-0000-0000-0000-000000000601")
NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


def test_failure_commit_uses_same_live_lease_fencing_as_success() -> None:
    sql = str(
        build_owned_job_for_failure_statement(
            job_id=JOB_ID,
            run_id=RUN_ID,
            worker_id="worker-1",
            expected_version=5,
            now=NOW,
        ).compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "evaluation_jobs.lease_owner = 'worker-1'" in sql
    assert "evaluation_jobs.version = 5" in sql
    assert "evaluation_jobs.lease_expires_at >" in sql
    assert "evaluation_jobs.status IN ('running', 'cancelling')" in sql
    assert "FOR UPDATE OF evaluation_jobs" in sql

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.dialects import postgresql

from app.jobs.results import (
    build_owned_job_for_completion_statement,
    build_run_lock_for_completion_statement,
    build_tenant_key_share_for_completion_statement,
)

JOB_ID = UUID("00000000-0000-0000-0000-000000000701")
RUN_ID = UUID("00000000-0000-0000-0000-000000000601")
NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


def test_result_commit_locks_only_a_live_owned_job_at_expected_version() -> None:
    sql = str(
        build_owned_job_for_completion_statement(
            job_id=JOB_ID,
            run_id=RUN_ID,
            worker_id="worker-1",
            expected_version=4,
            now=NOW,
        ).compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "evaluation_jobs.id" in sql
    assert "evaluation_jobs.run_id" in sql
    assert "evaluation_jobs.lease_owner = 'worker-1'" in sql
    assert "evaluation_jobs.version = 4" in sql
    assert "evaluation_jobs.lease_expires_at >" in sql
    assert "FOR UPDATE OF evaluation_jobs" in sql


def test_result_commit_has_key_preserving_run_first_lock_statement() -> None:
    sql = str(
        build_run_lock_for_completion_statement(run_id=RUN_ID).compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "WHERE evaluation_runs.id" in sql
    assert "FOR NO KEY UPDATE OF evaluation_runs" in sql


def test_result_commit_has_explicit_tenant_key_share_statement() -> None:
    sql = str(
        build_tenant_key_share_for_completion_statement(tenant_id=RUN_ID).compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "WHERE tenants.id" in sql
    assert "FOR KEY SHARE OF tenants" in sql

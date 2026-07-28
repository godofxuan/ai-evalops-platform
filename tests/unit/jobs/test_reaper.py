from datetime import UTC, datetime

from sqlalchemy.dialects import postgresql

from app.jobs.reaper import build_expired_job_statement

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


def test_reaper_locks_expired_running_jobs_with_skip_locked() -> None:
    sql = str(
        build_expired_job_statement(now=NOW, limit=50).compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "evaluation_jobs.lease_expires_at <" in sql
    assert "evaluation_jobs.status IN ('running', 'cancelling')" in sql
    assert "FOR UPDATE OF evaluation_jobs SKIP LOCKED" in sql
    assert "ORDER BY evaluation_jobs.lease_expires_at ASC" in sql
    assert "LIMIT 50" in sql

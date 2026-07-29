from datetime import UTC, datetime

from sqlalchemy.dialects import postgresql

from app.observability.durable import (
    DurableJobGauges,
    build_durable_job_gauges_statement,
)


def test_durable_job_gauge_query_counts_queue_running_and_oldest_heartbeat() -> None:
    statement = build_durable_job_gauges_statement()
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "count(evaluation_jobs.id) FILTER" in sql
    assert "evaluation_jobs.status IN ('queued', 'retry_wait')" in sql
    assert "evaluation_jobs.status IN ('running', 'cancelling')" in sql
    assert "min(evaluation_jobs.heartbeat_at) FILTER" in sql
    assert "tenant_id" not in sql


def test_durable_job_gauges_calculate_stalest_heartbeat_age() -> None:
    gauges = DurableJobGauges(
        queue_depth=4,
        running=2,
        oldest_heartbeat_at=datetime(2026, 7, 29, 11, 59, 50, tzinfo=UTC),
    )

    assert gauges.heartbeat_age_seconds(datetime(2026, 7, 29, 12, 0, tzinfo=UTC)) == 10.0

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.rows import dict_row

RUN_SQL = """
SELECT
    id::text AS id,
    dataset_version_id::text AS dataset_version_id,
    dataset_hash,
    target_config_hash,
    evaluator_config_hash,
    source_commit,
    status::text AS status,
    total_jobs,
    succeeded_jobs,
    failed_jobs,
    cancelled_jobs,
    created_at,
    started_at,
    finished_at
FROM evaluation_runs
WHERE id = %s
"""

JOBS_SQL = """
SELECT
    id::text AS id,
    run_id::text AS run_id,
    case_id,
    status::text AS status,
    attempt_count,
    max_attempts,
    created_at,
    started_at,
    finished_at
FROM evaluation_jobs
WHERE run_id = %s
ORDER BY case_id, id
"""

ATTEMPTS_SQL = """
SELECT
    attempt.job_id::text AS job_id,
    attempt.attempt_number,
    attempt.worker_id,
    attempt.started_at,
    attempt.finished_at,
    attempt.outcome::text AS outcome,
    attempt.retryable,
    attempt.error_code,
    attempt.upstream_status_code,
    attempt.latency_ms
FROM job_attempts AS attempt
JOIN evaluation_jobs AS job ON job.id = attempt.job_id
WHERE job.run_id = %s
ORDER BY attempt.job_id, attempt.attempt_number
"""

CASE_RESULTS_SQL = """
SELECT
    job_id::text AS job_id,
    run_id::text AS run_id,
    case_id,
    latency_ms,
    created_at
FROM case_results
WHERE run_id = %s
ORDER BY case_id, job_id
"""

SAMPLING_SQL = """
SELECT
    clock_timestamp() AS sampled_at,
    count(*) FILTER (WHERE state = 'active') AS active_connections,
    count(*) FILTER (WHERE state = 'idle') AS idle_connections,
    count(*) FILTER (WHERE state = 'idle in transaction') AS idle_in_transaction_connections,
    count(*) FILTER (WHERE wait_event_type = 'Lock') AS lock_waiting_connections
FROM pg_stat_activity
WHERE datname = current_database()
"""

QUEUE_SQL = """
SELECT status::text AS status, count(*) AS count
FROM evaluation_jobs
WHERE status::text IN ('queued', 'running', 'retry_wait', 'cancelling')
GROUP BY status
ORDER BY status
"""


def psycopg_dsn(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (UUID, Decimal)):
        return str(value)
    return value


def _json_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: _json_value(value) for key, value in row.items()}


async def collect_reconciliation_bundle(
    *,
    database_url: str,
    run_id: str,
) -> dict[str, Any]:
    connection = await AsyncConnection.connect(
        psycopg_dsn(database_url),
        row_factory=dict_row,
    )
    async with connection, connection.transaction(), connection.cursor() as cursor:
        await cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        await cursor.execute(RUN_SQL, (run_id,))
        run = await cursor.fetchone()
        if run is None:
            raise LookupError(f"Run not found during reconciliation: {run_id}")
        await cursor.execute(JOBS_SQL, (run_id,))
        jobs = await cursor.fetchall()
        await cursor.execute(ATTEMPTS_SQL, (run_id,))
        attempts = await cursor.fetchall()
        await cursor.execute(CASE_RESULTS_SQL, (run_id,))
        case_results = await cursor.fetchall()
    return {
        "run_snapshot": _json_row(run),
        "jobs": [_json_row(row) for row in jobs],
        "attempts": [_json_row(row) for row in attempts],
        "case_results": [_json_row(row) for row in case_results],
    }


async def collect_postgres_sample(*, database_url: str) -> dict[str, Any]:
    connection = await AsyncConnection.connect(
        psycopg_dsn(database_url),
        row_factory=dict_row,
    )
    async with connection, connection.cursor() as cursor:
        await cursor.execute(SAMPLING_SQL)
        row = await cursor.fetchone()
    if row is None:
        raise RuntimeError("PostgreSQL sampler returned no row")
    return _json_row(row)


async def collect_nonterminal_queue_counts(
    *,
    database_url: str,
) -> dict[str, int]:
    connection = await AsyncConnection.connect(
        psycopg_dsn(database_url),
        row_factory=dict_row,
    )
    async with connection, connection.cursor() as cursor:
        await cursor.execute(QUEUE_SQL)
        rows = await cursor.fetchall()
    return {str(row["status"]): int(row["count"]) for row in rows}

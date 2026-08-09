import asyncio
import json
import os
import tempfile
from collections.abc import Awaitable
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from sqlalchemy import event
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from scripts.gate1_database import psycopg_dsn

POSTGRES_LOCK_TIMEOUT = "1500ms"
POSTGRES_STATEMENT_TIMEOUT = "8000ms"
PYTHON_WAIT_TIMEOUT_SECONDS = 15.0
LOCK_SNAPSHOT_TIMEOUT_SECONDS = 1.25
LOCK_SNAPSHOT_POLL_SECONDS = 0.02

TARGET_ACTIVITY_SQL = """
SELECT
    pid,
    application_name,
    state,
    wait_event_type,
    wait_event,
    pg_blocking_pids(pid) AS blocking_pids,
    query_start,
    xact_start,
    query
FROM pg_stat_activity
WHERE datname = current_database()
  AND application_name = %s
ORDER BY pid
"""

RELEVANT_ACTIVITY_SQL = """
SELECT
    pid,
    application_name,
    state,
    wait_event_type,
    wait_event,
    pg_blocking_pids(pid) AS blocking_pids,
    query_start,
    xact_start,
    query
FROM pg_stat_activity
WHERE pid = ANY(%s)
ORDER BY pid
"""

RELEVANT_LOCKS_SQL = """
SELECT
    locks.pid,
    activity.application_name,
    activity.state,
    activity.wait_event_type,
    activity.wait_event,
    locks.locktype,
    locks.mode,
    locks.granted,
    locks.relation::regclass::text AS relation,
    locks.page,
    locks.tuple,
    locks.virtualxid,
    locks.transactionid::text AS transactionid,
    locks.virtualtransaction,
    locks.classid,
    locks.objid,
    locks.objsubid,
    locks.fastpath
FROM pg_locks AS locks
LEFT JOIN pg_stat_activity AS activity ON activity.pid = locks.pid
WHERE locks.pid = ANY(%s)
ORDER BY locks.pid, locks.granted, locks.locktype, locks.mode
"""


def postgres_timeout_statements() -> tuple[str, str]:
    """Return transaction-local safety limits used only by PostgreSQL tests."""

    return (
        f"SET LOCAL lock_timeout = '{POSTGRES_LOCK_TIMEOUT}'",
        f"SET LOCAL statement_timeout = '{POSTGRES_STATEMENT_TIMEOUT}'",
    )


def install_postgres_test_timeouts(engine: AsyncEngine) -> None:
    """Apply fail-fast timeouts to every transaction opened by this test engine."""

    def set_local_timeouts(connection: Connection) -> None:
        for statement in postgres_timeout_statements():
            connection.exec_driver_sql(statement)

    event.listen(engine.sync_engine, "begin", set_local_timeouts)


def create_postgres_test_engine(
    database_url: str,
    *,
    application_name: str,
) -> AsyncEngine:
    """Create a named PostgreSQL engine so a blocked test session is observable."""

    if not application_name.strip():
        raise ValueError("application_name must not be blank")
    engine = create_async_engine(
        database_url,
        pool_pre_ping=True,
        connect_args={"application_name": application_name},
    )
    install_postgres_test_timeouts(engine)
    return engine


def _json_compatible(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_compatible(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_compatible(item) for item in value]
    return value


async def wait_for_postgres_lock_snapshot(
    database_url: str,
    *,
    target_application_name: str,
    timeout_seconds: float = LOCK_SNAPSHOT_TIMEOUT_SECONDS,
    poll_seconds: float = LOCK_SNAPSHOT_POLL_SECONDS,
) -> dict[str, Any]:
    """Capture target/blocker activity and locks once a named session blocks."""

    deadline = perf_counter() + timeout_seconds
    last_target_activity: list[dict[str, Any]] = []
    connection = await AsyncConnection.connect(
        psycopg_dsn(database_url),
        row_factory=dict_row,
        application_name="final-scheduler-lock-observer",
    )
    async with connection, connection.cursor() as cursor:
        while True:
            await cursor.execute(TARGET_ACTIVITY_SQL, (target_application_name,))
            last_target_activity = list(await cursor.fetchall())
            blocked_rows = [
                row
                for row in last_target_activity
                if row["wait_event_type"] == "Lock" and row["blocking_pids"]
            ]
            if blocked_rows:
                target_pids = sorted({int(row["pid"]) for row in blocked_rows})
                blocking_pids = sorted(
                    {
                        int(blocking_pid)
                        for row in blocked_rows
                        for blocking_pid in row["blocking_pids"]
                    }
                )
                relevant_pids = sorted({*target_pids, *blocking_pids})

                await cursor.execute(RELEVANT_ACTIVITY_SQL, (relevant_pids,))
                activities = list(await cursor.fetchall())
                await cursor.execute(RELEVANT_LOCKS_SQL, (relevant_pids,))
                locks = list(await cursor.fetchall())
                return {
                    "captured_at": datetime.now(UTC).isoformat(),
                    "target_application_name": target_application_name,
                    "target_pids": target_pids,
                    "blocking_pids": blocking_pids,
                    "activities": [_json_compatible(row) for row in activities],
                    "locks": [_json_compatible(row) for row in locks],
                }

            if perf_counter() >= deadline:
                break
            await asyncio.sleep(poll_seconds)

    raise AssertionError(
        "No PostgreSQL lock wait observed for "
        f"{target_application_name!r} within {timeout_seconds:g}s; "
        f"last activity={_json_compatible(last_target_activity)!r}"
    )


async def wait_for_lock_sensitive[ResultT](
    awaitable: Awaitable[ResultT],
    *,
    operation: str,
    timeout_seconds: float = PYTHON_WAIT_TIMEOUT_SECONDS,
) -> ResultT:
    """Turn an unbounded Python-side lock wait into an actionable test failure."""

    try:
        return await asyncio.wait_for(awaitable, timeout=timeout_seconds)
    except TimeoutError as error:
        raise AssertionError(
            f"{operation} exceeded the {timeout_seconds:g}s Python timeout"
        ) from error


def write_lock_diagnostic(
    record: dict[str, Any],
    *,
    directory: Path | None = None,
) -> Path:
    """Append one diagnostic record for CI artifact preservation."""

    resolved_directory = directory or Path(
        os.getenv(
            "EVALOPS_SCHEDULER_DIAGNOSTIC_DIR",
            str(Path(tempfile.gettempdir()) / "evalops-final-scheduler"),
        )
    )
    resolved_directory.mkdir(parents=True, exist_ok=True)
    path = resolved_directory / "lock-diagnostics.jsonl"
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        json.dump(record, stream, ensure_ascii=False, sort_keys=True, default=str)
        stream.write("\n")
    return path

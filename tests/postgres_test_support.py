from collections.abc import Awaitable

from sqlalchemy import event
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

POSTGRES_LOCK_TIMEOUT = "1500ms"
POSTGRES_STATEMENT_TIMEOUT = "8000ms"
PYTHON_WAIT_TIMEOUT_SECONDS = 15.0


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


async def wait_for_lock_sensitive[ResultT](
    awaitable: Awaitable[ResultT],
    *,
    operation: str,
    timeout_seconds: float = PYTHON_WAIT_TIMEOUT_SECONDS,
) -> ResultT:
    """Turn an unbounded Python-side lock wait into an actionable test failure."""

    import asyncio

    try:
        return await asyncio.wait_for(awaitable, timeout=timeout_seconds)
    except TimeoutError as error:
        raise AssertionError(
            f"{operation} exceeded the {timeout_seconds:g}s Python timeout"
        ) from error

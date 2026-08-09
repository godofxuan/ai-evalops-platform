import asyncio

import pytest

from tests.postgres_test_support import (
    postgres_timeout_statements,
    wait_for_lock_sensitive,
)


def test_lock_sensitive_postgres_transactions_use_local_fail_fast_timeouts() -> None:
    assert postgres_timeout_statements() == (
        "SET LOCAL lock_timeout = '1500ms'",
        "SET LOCAL statement_timeout = '8000ms'",
    )


async def test_lock_sensitive_python_wait_reports_the_operation_in_seconds() -> None:
    with pytest.raises(
        AssertionError,
        match="diagnostic claim exceeded the 0.01s Python timeout",
    ):
        await wait_for_lock_sensitive(
            asyncio.Event().wait(),
            operation="diagnostic claim",
            timeout_seconds=0.01,
        )

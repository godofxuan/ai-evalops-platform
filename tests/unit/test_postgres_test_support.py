import asyncio
import json
from pathlib import Path

import pytest

from tests.postgres_test_support import (
    postgres_timeout_statements,
    wait_for_lock_sensitive,
    write_lock_diagnostic,
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


def test_lock_diagnostic_is_appended_as_machine_readable_json(tmp_path: Path) -> None:
    path = write_lock_diagnostic(
        {
            "hypothesis": "H2_FK_LOCK_INTERACTION",
            "blocking_pids": [101],
        },
        directory=tmp_path,
    )

    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    assert path == tmp_path / "lock-diagnostics.jsonl"
    assert records == [
        {
            "blocking_pids": [101],
            "hypothesis": "H2_FK_LOCK_INTERACTION",
        }
    ]

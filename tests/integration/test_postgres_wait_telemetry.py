import asyncio
import os
from pathlib import Path
from uuid import uuid4

import pytest
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from scripts.gate1_database import psycopg_dsn
from scripts.postgres_wait_telemetry import (
    POSTGRES_TELEMETRY_QUERY,
    begin_passive_telemetry_process,
    start_passive_telemetry_process,
    stop_passive_telemetry_process,
)

pytestmark = pytest.mark.integration


def _database_url() -> str:
    if os.getenv("EVALOPS_RUN_INTEGRATION") != "1":
        pytest.skip("set EVALOPS_RUN_INTEGRATION=1 with real PostgreSQL")
    database_url = os.getenv("EVALOPS_DATABASE_URL")
    if database_url is None:
        pytest.fail("integration test requires EVALOPS_DATABASE_URL")
    return database_url


async def _fetch_public_snapshot(
    connection: AsyncConnection[dict[str, object]],
) -> list[dict[str, object]]:
    async with connection.cursor() as cursor:
        await cursor.execute(POSTGRES_TELEMETRY_QUERY, (257,))
        return list(await cursor.fetchall())


@pytest.mark.asyncio
async def test_telemetry_reads_pg_stat_activity_from_separate_connection() -> None:
    dsn = psycopg_dsn(_database_url())
    workload = await AsyncConnection.connect(dsn)
    telemetry = await AsyncConnection.connect(dsn, autocommit=True, row_factory=dict_row)
    async with workload, telemetry:
        await telemetry.execute("SET default_transaction_read_only = on")
        await telemetry.execute("SET application_name = 'evalops_passive_telemetry'")
        async with workload.transaction():
            await workload.execute("SELECT 1")
            snapshot = await _fetch_public_snapshot(telemetry)

        assert workload.info.backend_pid != telemetry.info.backend_pid
        assert any(row["pid"] == workload.info.backend_pid for row in snapshot)


@pytest.mark.asyncio
async def test_telemetry_reads_wait_state_without_modifying_transaction() -> None:
    dsn = psycopg_dsn(_database_url())
    holder = await AsyncConnection.connect(dsn)
    waiter = await AsyncConnection.connect(dsn)
    telemetry = await AsyncConnection.connect(dsn, autocommit=True, row_factory=dict_row)
    lock_key = uuid4().int % (2**31)
    async with holder, waiter, telemetry:
        await telemetry.execute("SET default_transaction_read_only = on")
        await telemetry.execute("SET application_name = 'evalops_passive_telemetry'")
        async with holder.transaction():
            transaction_cursor = await holder.execute("SELECT pg_current_xact_id()::text")
            transaction_row_before = await transaction_cursor.fetchone()
            assert transaction_row_before is not None
            transaction_id_before = transaction_row_before[0]
            await holder.execute("SELECT pg_advisory_xact_lock(%s)", (lock_key,))
            waiter_task = asyncio.create_task(
                waiter.execute("SELECT pg_advisory_xact_lock(%s)", (lock_key,))
            )
            waiting_row: dict[str, object] | None = None
            for _attempt in range(100):
                snapshot = await _fetch_public_snapshot(telemetry)
                waiting_row = next(
                    (
                        row
                        for row in snapshot
                        if row["pid"] == waiter.info.backend_pid
                        and row["wait_event_type"] == "Lock"
                    ),
                    None,
                )
                if waiting_row is not None:
                    break
                await asyncio.sleep(0.01)
            transaction_cursor = await holder.execute("SELECT pg_current_xact_id()::text")
            transaction_row_after = await transaction_cursor.fetchone()
            assert transaction_row_after is not None
            transaction_id_after = transaction_row_after[0]
            assert waiting_row is not None
            assert waiting_row["locktype"] == "advisory"
            assert transaction_id_after == transaction_id_before
        await asyncio.wait_for(waiter_task, timeout=5)
        await waiter.rollback()


@pytest.mark.asyncio
async def test_telemetry_failure_does_not_abort_workload_transaction(
    tmp_path: Path,
) -> None:
    dsn = psycopg_dsn(_database_url())
    workload = await AsyncConnection.connect(dsn)
    handle = await start_passive_telemetry_process(
        directory=tmp_path / "failed-telemetry",
        database_url_env="EVALOPS_INTENTIONALLY_MISSING_DATABASE_URL",
        sampling_hz=5,
    )
    await begin_passive_telemetry_process(handle)
    async with workload, workload.transaction():
        cursor = await workload.execute("SELECT 42")
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == 42
    summary = await stop_passive_telemetry_process(handle)

    assert summary["telemetry_error_count"] == 1


@pytest.mark.asyncio
async def test_telemetry_stops_cleanly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVALOPS_TELEMETRY_TEST_DATABASE_URL", _database_url())
    handle = await start_passive_telemetry_process(
        directory=tmp_path / "telemetry",
        database_url_env="EVALOPS_TELEMETRY_TEST_DATABASE_URL",
        sampling_hz=20,
    )
    await begin_passive_telemetry_process(handle)
    await asyncio.sleep(0.15)
    summary = await stop_passive_telemetry_process(handle)

    assert handle.process.returncode == 0
    successful_sample_count = summary["successful_sample_count"]
    assert isinstance(successful_sample_count, int)
    assert successful_sample_count >= 1
    assert summary["telemetry_error_count"] == 0
    assert (handle.directory / "samples.jsonl").is_file()

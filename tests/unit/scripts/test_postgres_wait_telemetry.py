import asyncio
import json
from pathlib import Path

import pytest

from scripts.postgres_wait_telemetry import (
    POSTGRES_TELEMETRY_QUERY,
    collect_telemetry,
    project_public_row,
)


def _database_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "observed_at": "2026-08-11T00:00:00+00:00",
        "pid": 123,
        "state": "active",
        "wait_event_type": "Lock",
        "wait_event": "transactionid",
        "backend_type": "client backend",
        "query_fingerprint": "a" * 32,
        "query_category": "job_selection",
        "locktype": "transactionid",
        "mode": "ShareLock",
        "granted": False,
        "relation_identity": None,
    }
    row.update(overrides)
    return row


def test_telemetry_query_is_static_read_only_core_postgres_sql() -> None:
    normalized = " ".join(POSTGRES_TELEMETRY_QUERY.lower().split())

    assert "pg_stat_activity" in normalized
    assert "pg_locks" in normalized
    assert " limit %s" in normalized
    assert not any(
        token in normalized
        for token in (" insert ", " update ", " delete ", " vacuum ", " analyze ")
    )


def test_telemetry_rejects_sensitive_raw_query_in_public_projection() -> None:
    projected = project_public_row(
        _database_row(
            query="SELECT * FROM evaluation_jobs WHERE tenant_id='secret-tenant'",
            tenant_id="secret-tenant",
            job_id="secret-job",
        )
    )

    assert "query" not in projected
    assert "tenant_id" not in projected
    assert "job_id" not in projected
    assert "secret" not in json.dumps(projected)


@pytest.mark.asyncio
async def test_telemetry_uses_bounded_buffer_or_streaming_output(tmp_path: Path) -> None:
    stop = asyncio.Event()

    async def fetch_sample(limit: int) -> list[dict[str, object]]:
        stop.set()
        return [_database_row(pid=index) for index in range(limit + 1)]

    summary = await collect_telemetry(
        fetch_sample=fetch_sample,
        output_path=tmp_path / "samples.jsonl",
        stop_requested=stop.is_set,
        sampling_hz=20,
        max_rows_per_sample=2,
        max_samples=4,
    )

    records = (tmp_path / "samples.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(records) == 1
    assert len(json.loads(records[0])["rows"]) == 2
    assert summary["buffer_overflow_count"] == 1
    assert summary["dropped_sample_count"] == 1


@pytest.mark.asyncio
async def test_telemetry_failure_is_recorded_and_stops_cleanly(tmp_path: Path) -> None:
    stop = asyncio.Event()

    async def fetch_sample(_limit: int) -> list[dict[str, object]]:
        stop.set()
        raise RuntimeError("dsn=must-not-leak")

    summary = await collect_telemetry(
        fetch_sample=fetch_sample,
        output_path=tmp_path / "samples.jsonl",
        stop_requested=stop.is_set,
        sampling_hz=5,
        max_rows_per_sample=8,
        max_samples=4,
    )

    public_output = (tmp_path / "samples.jsonl").read_text(encoding="utf-8")
    assert summary["telemetry_error_count"] == 1
    assert summary["successful_sample_count"] == 0
    assert "must-not-leak" not in public_output
    assert "RuntimeError" in public_output


@pytest.mark.asyncio
async def test_telemetry_records_sampling_metadata(tmp_path: Path) -> None:
    stop = asyncio.Event()

    async def fetch_sample(_limit: int) -> list[dict[str, object]]:
        stop.set()
        return [_database_row()]

    summary = await collect_telemetry(
        fetch_sample=fetch_sample,
        output_path=tmp_path / "samples.jsonl",
        stop_requested=stop.is_set,
        sampling_hz=5,
        max_rows_per_sample=8,
        max_samples=4,
    )

    assert summary["sampling_hz"] == 5
    assert summary["sample_interval_seconds"] == pytest.approx(0.2)
    assert summary["successful_sample_count"] == 1
    assert summary["observed_wait_sample_count"] == 1
    assert summary["observed_waiting_backends"] == 1
    assert summary["rows_written"] == 1
    assert summary["telemetry_error_count"] == 0


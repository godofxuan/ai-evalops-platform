"""Stream bounded, passive PostgreSQL wait snapshots from a separate process."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from scripts.gate1_database import psycopg_dsn

POSTGRES_TELEMETRY_QUERY = """
SELECT
    clock_timestamp() AS observed_at,
    activity.pid,
    activity.state,
    activity.wait_event_type,
    activity.wait_event,
    activity.backend_type,
    md5(COALESCE(activity.query, '')) AS query_fingerprint,
    CASE
        WHEN activity.query ILIKE '%%scheduler_claim_sequence%%'
            THEN 'durable_sequence_update'
        WHEN activity.query ILIKE '%%scheduler_coordination%%'
            THEN 'scheduler_coordination_lock'
        WHEN activity.query ILIKE '%%tenant_scheduler_states%%'
            THEN 'tenant_permit_selection'
        WHEN activity.query ILIKE '%%evaluation_jobs%%'
            THEN 'job_selection'
        ELSE 'other'
    END AS query_category,
    locks.locktype,
    locks.mode,
    locks.granted,
    relation.relname AS relation_identity
FROM pg_catalog.pg_stat_activity AS activity
LEFT JOIN pg_catalog.pg_locks AS locks ON locks.pid = activity.pid
LEFT JOIN pg_catalog.pg_class AS relation ON relation.oid = locks.relation
WHERE activity.datname = current_database()
  AND activity.backend_type = 'client backend'
  AND activity.pid <> pg_backend_pid()
  AND activity.application_name <> 'evalops_passive_telemetry'
ORDER BY activity.pid, locks.locktype, locks.mode, locks.granted
LIMIT %s
""".strip()

PUBLIC_TELEMETRY_FIELDS = (
    "observed_at",
    "pid",
    "state",
    "wait_event_type",
    "wait_event",
    "backend_type",
    "query_fingerprint",
    "query_category",
    "locktype",
    "mode",
    "granted",
    "relation_identity",
)

FetchSample = Callable[[int], Awaitable[Sequence[Mapping[str, object]]]]
StopRequested = Callable[[], bool]


@dataclass(frozen=True, slots=True)
class PassiveTelemetryProcess:
    process: asyncio.subprocess.Process
    directory: Path
    start_path: Path
    stop_path: Path
    summary_path: Path


def _json_safe(value: object) -> object:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return value


def project_public_row(row: Mapping[str, object]) -> dict[str, object]:
    """Project a database row through an explicit public-artifact allowlist."""
    return {field: _json_safe(row.get(field)) for field in PUBLIC_TELEMETRY_FIELDS}


def _is_waiting(row: Mapping[str, object]) -> bool:
    return row.get("wait_event_type") is not None or row.get("granted") is False


async def collect_telemetry(
    *,
    fetch_sample: FetchSample,
    output_path: Path,
    stop_requested: StopRequested,
    sampling_hz: int,
    max_rows_per_sample: int,
    max_samples: int,
) -> dict[str, int | float | str]:
    """Collect bounded samples and stream each one immediately as public JSONL."""
    if sampling_hz <= 0 or max_rows_per_sample <= 0 or max_samples <= 0:
        raise ValueError("telemetry bounds and sampling frequency must be positive")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    interval = 1.0 / sampling_hz
    successful_samples = 0
    observed_wait_samples = 0
    waiting_backend_pids: set[int] = set()
    rows_written = 0
    telemetry_errors = 0
    dropped_samples = 0
    buffer_overflows = 0
    query_latency_sum_ms = 0.0
    query_latency_max_ms = 0.0
    started_at = perf_counter()
    next_deadline = started_at

    with output_path.open("x", encoding="utf-8", newline="\n") as stream:
        while not stop_requested():
            if successful_samples + telemetry_errors >= max_samples:
                buffer_overflows += 1
                dropped_samples += 1
                break
            sample_index = successful_samples + telemetry_errors + 1
            query_started = perf_counter()
            try:
                database_rows = await fetch_sample(max_rows_per_sample + 1)
                query_latency_ms = (perf_counter() - query_started) * 1_000
                query_latency_sum_ms += query_latency_ms
                query_latency_max_ms = max(query_latency_max_ms, query_latency_ms)
                overflow = max(len(database_rows) - max_rows_per_sample, 0)
                if overflow:
                    buffer_overflows += 1
                    dropped_samples += overflow
                public_rows = [
                    project_public_row(row) for row in database_rows[:max_rows_per_sample]
                ]
                waiting_rows = [row for row in public_rows if _is_waiting(row)]
                if waiting_rows:
                    observed_wait_samples += 1
                    for row in waiting_rows:
                        pid = row.get("pid")
                        if isinstance(pid, int) and not isinstance(pid, bool):
                            waiting_backend_pids.add(pid)
                successful_samples += 1
                rows_written += len(public_rows)
                record: dict[str, object] = {
                    "record_type": "sample",
                    "sample_index": sample_index,
                    "query_latency_ms": query_latency_ms,
                    "rows": public_rows,
                }
            except Exception as error:
                telemetry_errors += 1
                record = {
                    "record_type": "sample_error",
                    "sample_index": sample_index,
                    "error_type": type(error).__name__,
                }
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            stream.flush()

            next_deadline += interval
            remaining = next_deadline - perf_counter()
            if remaining > 0:
                await asyncio.sleep(remaining)
            else:
                missed = int(abs(remaining) // interval)
                if missed:
                    dropped_samples += missed
                    next_deadline += missed * interval

    elapsed_seconds = perf_counter() - started_at
    return {
        "schema_version": 1,
        "collector": "external_passive_postgres_core_views",
        "sampling_hz": sampling_hz,
        "sample_interval_seconds": interval,
        "max_rows_per_sample": max_rows_per_sample,
        "max_samples": max_samples,
        "successful_sample_count": successful_samples,
        "observed_wait_sample_count": observed_wait_samples,
        "observed_waiting_backends": len(waiting_backend_pids),
        "rows_written": rows_written,
        "telemetry_error_count": telemetry_errors,
        "dropped_sample_count": dropped_samples,
        "buffer_overflow_count": buffer_overflows,
        "query_latency_ms_mean": (
            query_latency_sum_ms / successful_samples if successful_samples else 0.0
        ),
        "query_latency_ms_max": query_latency_max_ms,
        "elapsed_seconds": elapsed_seconds,
        "raw_query_text_persisted": "NO",
    }


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _either_signal_exists(first: Path, second: Path) -> bool:
    return first.exists() or second.exists()


async def _run_collector(args: argparse.Namespace) -> int:
    output_path = Path(args.output)
    summary_path = Path(args.summary)
    ready_path = Path(args.ready_file)
    start_path = Path(args.start_file)
    stop_path = Path(args.stop_file)
    database_url = os.getenv(str(args.database_url_env))
    if database_url is None:
        _write_json(
            summary_path,
            {
                "schema_version": 1,
                "successful_sample_count": 0,
                "observed_wait_sample_count": 0,
                "observed_waiting_backends": 0,
                "rows_written": 0,
                "telemetry_error_count": 1,
                "dropped_sample_count": 0,
                "buffer_overflow_count": 0,
                "failure_type": "MissingDatabaseEnvironment",
            },
        )
        _write_json(ready_path, {"status": "ERROR"})
        return 1

    ready_announced = False
    try:
        connection = await AsyncConnection.connect(
            psycopg_dsn(database_url),
            autocommit=True,
            row_factory=dict_row,
        )
        async with connection:
            await connection.execute("SET default_transaction_read_only = on")
            await connection.execute("SET application_name = 'evalops_passive_telemetry'")

            async def fetch_sample(limit: int) -> list[Mapping[str, object]]:
                async with connection.cursor() as cursor:
                    await cursor.execute(POSTGRES_TELEMETRY_QUERY, (limit,))
                    return list(await cursor.fetchall())

            _write_json(ready_path, {"status": "READY"})
            ready_announced = True
            while not await asyncio.to_thread(  # noqa: ASYNC110 - file-signal IPC polling
                _either_signal_exists, start_path, stop_path
            ):
                await asyncio.sleep(0.01)
            summary = await collect_telemetry(
                fetch_sample=fetch_sample,
                output_path=output_path,
                stop_requested=stop_path.exists,
                sampling_hz=int(args.sampling_hz),
                max_rows_per_sample=int(args.max_rows_per_sample),
                max_samples=int(args.max_samples),
            )
    except Exception as error:
        summary = {
            "schema_version": 1,
            "successful_sample_count": 0,
            "observed_wait_sample_count": 0,
            "observed_waiting_backends": 0,
            "rows_written": 0,
            "telemetry_error_count": 1,
            "dropped_sample_count": 0,
            "buffer_overflow_count": 0,
            "failure_type": type(error).__name__,
        }
        if not ready_announced:
            _write_json(ready_path, {"status": "ERROR"})
    _write_json(summary_path, summary)
    return 0 if int(summary["telemetry_error_count"]) == 0 else 1


async def start_passive_telemetry_process(
    *,
    directory: Path,
    database_url_env: str,
    sampling_hz: int,
    ready_timeout_seconds: float = 15.0,
) -> PassiveTelemetryProcess:
    """Start the isolated collector and wait only for readiness, never for workload I/O."""
    await asyncio.to_thread(directory.mkdir, parents=True, exist_ok=False)
    output_path = directory / "samples.jsonl"
    summary_path = directory / "summary.json"
    ready_path = directory / "ready.json"
    start_path = directory / "start.signal"
    stop_path = directory / "stop.signal"
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "scripts.postgres_wait_telemetry",
        "--database-url-env",
        database_url_env,
        "--output",
        str(output_path),
        "--summary",
        str(summary_path),
        "--ready-file",
        str(ready_path),
        "--start-file",
        str(start_path),
        "--stop-file",
        str(stop_path),
        "--sampling-hz",
        str(sampling_hz),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = perf_counter() + ready_timeout_seconds
    while perf_counter() < deadline:
        if await asyncio.to_thread(ready_path.exists) or process.returncode is not None:
            break
        await asyncio.sleep(0.01)
    return PassiveTelemetryProcess(
        process=process,
        directory=directory,
        start_path=start_path,
        stop_path=stop_path,
        summary_path=summary_path,
    )


async def begin_passive_telemetry_process(handle: PassiveTelemetryProcess) -> None:
    if handle.process.returncode is None:
        await asyncio.to_thread(
            handle.start_path.write_text,
            "start\n",
            encoding="utf-8",
            newline="\n",
        )


async def stop_passive_telemetry_process(
    handle: PassiveTelemetryProcess,
    *,
    timeout_seconds: float = 15.0,
) -> dict[str, object]:
    if handle.process.returncode is None:
        await asyncio.to_thread(
            handle.stop_path.write_text,
            "stop\n",
            encoding="utf-8",
            newline="\n",
        )
        try:
            await asyncio.wait_for(handle.process.wait(), timeout=timeout_seconds)
        except TimeoutError:
            handle.process.kill()
            await handle.process.wait()
    try:
        summary_text = await asyncio.to_thread(handle.summary_path.read_text, encoding="utf-8")
        summary = json.loads(summary_text)
        if not isinstance(summary, dict):
            raise ValueError("telemetry summary is not an object")
        return summary
    except (OSError, json.JSONDecodeError, ValueError):
        return {
            "schema_version": 1,
            "successful_sample_count": 0,
            "observed_wait_sample_count": 0,
            "observed_waiting_backends": 0,
            "rows_written": 0,
            "telemetry_error_count": 1,
            "dropped_sample_count": 0,
            "buffer_overflow_count": 0,
            "failure_type": "TelemetrySummaryUnavailable",
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url-env", default="EVALOPS_EXPERIMENT_DATABASE_URL")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--ready-file", type=Path, required=True)
    parser.add_argument("--start-file", type=Path, required=True)
    parser.add_argument("--stop-file", type=Path, required=True)
    parser.add_argument("--sampling-hz", type=int, required=True)
    parser.add_argument("--max-rows-per-sample", type=int, default=256)
    parser.add_argument("--max-samples", type=int, default=10_000)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(_run_collector(args))
    except Exception as error:
        print(f"passive telemetry failed: error_type={type(error).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

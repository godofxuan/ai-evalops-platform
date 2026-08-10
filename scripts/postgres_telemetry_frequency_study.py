"""Compare passive telemetry loop frequencies for local engineering selection only."""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
import tracemalloc
from collections.abc import Mapping, Sequence
from pathlib import Path
from time import perf_counter, process_time

from scripts.postgres_wait_telemetry import collect_telemetry

FREQUENCIES = (1, 5, 10, 20)
HISTORICAL_REPRESENTATIVE_JOBS_PER_SECOND = 27.153354854829008
REPRESENTATIVE_SAMPLE_JOBS = 100


def _synthetic_rows() -> list[Mapping[str, object]]:
    return [
        {
            "observed_at": "2026-08-11T00:00:00+00:00",
            "pid": 1_000 + index,
            "state": "active",
            "wait_event_type": "Lock" if index == 0 else None,
            "wait_event": "transactionid" if index == 0 else None,
            "backend_type": "client backend",
            "query_fingerprint": f"{index:032x}",
            "query_category": "job_selection",
            "locktype": "transactionid" if index == 0 else None,
            "mode": "ShareLock" if index == 0 else None,
            "granted": index != 0,
            "relation_identity": "evaluation_jobs",
        }
        for index in range(16)
    ]


async def _study_frequency(
    *, frequency: int, duration_seconds: float, root: Path
) -> dict[str, object]:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    loop.call_later(duration_seconds, stop.set)
    rows = _synthetic_rows()

    async def fetch_sample(limit: int) -> Sequence[Mapping[str, object]]:
        return rows[:limit]

    tracemalloc.start()
    cpu_started = process_time()
    wall_started = perf_counter()
    summary = await collect_telemetry(
        fetch_sample=fetch_sample,
        output_path=root / f"{frequency}hz.jsonl",
        stop_requested=stop.is_set,
        sampling_hz=frequency,
        max_rows_per_sample=256,
        max_samples=10_000,
    )
    wall_seconds = perf_counter() - wall_started
    cpu_seconds = process_time() - cpu_started
    _current_bytes, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    output_size = (root / f"{frequency}hz.jsonl").stat().st_size
    sample_count = int(summary["successful_sample_count"])
    representative_seconds = REPRESENTATIVE_SAMPLE_JOBS / HISTORICAL_REPRESENTATIVE_JOBS_PER_SECOND
    return {
        "frequency_hz": frequency,
        "duration_seconds": wall_seconds,
        "successful_samples": sample_count,
        "rows_per_sample": len(rows),
        "process_cpu_seconds": cpu_seconds,
        "process_cpu_percent_of_one_core": cpu_seconds / wall_seconds * 100,
        "python_peak_traced_bytes": peak_bytes,
        "jsonl_bytes": output_size,
        "jsonl_bytes_per_second": output_size / wall_seconds,
        "modeled_sample_opportunities_in_representative_period": (
            representative_seconds * frequency
        ),
        "database_query_latency": "NOT_RUN_NO_LOCAL_POSTGRESQL",
        "database_query_overhead": "NOT_RUN_NO_LOCAL_POSTGRESQL",
        "scope": "LOCAL_SYNTHETIC_PROJECTION_AND_STREAMING_ONLY",
    }


async def _run(*, duration_seconds: float) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="evalops-telemetry-frequency-") as temporary:
        root = Path(temporary)
        observations = [
            await _study_frequency(
                frequency=frequency,
                duration_seconds=duration_seconds,
                root=root,
            )
            for frequency in FREQUENCIES
        ]
    return {
        "schema_version": 1,
        "status": "LOCAL_ENGINEERING_SELECTION_ONLY",
        "frequencies_hz": list(FREQUENCIES),
        "observations": observations,
        "selected_frequency_hz": 5,
        "selection_reason": (
            "5 Hz provides about 18 sample opportunities in the historical 100-job period while "
            "limiting polling to half of 10 Hz and one quarter of 20 Hz; 1 Hz provides fewer than "
            "four opportunities. Real database query cost remains unverified locally."
        ),
        "measurement_validity_claim": "NOT_PERMITTED_FROM_LOCAL_STUDY",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration-seconds", type=float, default=3.0)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.duration_seconds <= 0:
        raise SystemExit("duration must be positive")
    report = asyncio.run(_run(duration_seconds=float(args.duration_seconds)))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"local telemetry frequency selected: {report['selected_frequency_hz']} Hz")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

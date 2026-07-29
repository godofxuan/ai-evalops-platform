import argparse
import asyncio
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.experiment_support import (
    ExperimentClient,
    ExperimentError,
    experiment_envelope,
    failed_experiment_envelope,
    percentile,
    write_report,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the real 500-case worker-scaling experiment against Compose."
    )
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--api-key-env", default="EVALOPS_EXPERIMENT_API_KEY")
    parser.add_argument("--compose-file", type=Path, default=Path("deploy/compose.yaml"))
    parser.add_argument("--workers", default="1,2,4,8")
    parser.add_argument("--cases", type=int, default=500)
    parser.add_argument("--delay-ms", type=int, default=25)
    parser.add_argument("--poll-seconds", type=float, default=0.5)
    parser.add_argument("--deadline-seconds", type=float, default=900)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/results/phase_9_worker_scaling.json"),
    )
    return parser


def _scale_workers(compose_file: Path, workers: int) -> None:
    subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(compose_file),
            "up",
            "--detach",
            "--scale",
            f"worker={workers}",
            "worker",
        ],
        check=True,
    )


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    worker_counts = [int(value) for value in args.workers.split(",")]
    if any(value < 1 for value in worker_counts):
        raise ExperimentError("worker counts must all be positive")
    if args.cases < 1:
        raise ExperimentError("case count must be positive")
    report = experiment_envelope(
        experiment="worker_scaling",
        configuration={
            "workers": worker_counts,
            "cases": args.cases,
            "delay_ms": args.delay_ms,
            "api_url": args.api_url,
        },
    )
    cases = [
        {
            "case_id": f"load-{index:04d}",
            "question": f"synthetic load case {index}",
            "expected_answer": "mock answer",
            "metadata": {},
        }
        for index in range(args.cases)
    ]
    async with ExperimentClient(
        api_url=args.api_url,
        api_key_env=args.api_key_env,
        timeout_seconds=30,
    ) as client:
        version_id = await client.create_dataset_version(
            name_prefix="phase9-load",
            cases=cases,
        )
        for workers in worker_counts:
            await asyncio.to_thread(_scale_workers, args.compose_file, workers)
            run = await client.create_run(
                dataset_version_id=version_id,
                target_config={
                    "answer": "mock answer",
                    "fixed_delay_ms": args.delay_ms,
                },
                idempotency_key=f"phase9-load-{workers}-{datetime.now(UTC).timestamp()}",
            )
            snapshot, wall_seconds = await client.wait_for_run(
                str(run["id"]),
                poll_seconds=args.poll_seconds,
                deadline_seconds=args.deadline_seconds,
            )
            case_rows = await client.list_all_cases(str(run["id"]))
            latencies = [
                float(item["latency_ms"]) for item in case_rows if item["latency_ms"] is not None
            ]
            case_ids = [str(item["case_id"]) for item in case_rows]
            report["results"].append(
                {
                    "workers": workers,
                    "run_id": run["id"],
                    "status": snapshot["status"],
                    "wall_seconds": wall_seconds,
                    "throughput_cases_per_second": (
                        len(case_rows) / wall_seconds if wall_seconds > 0 else None
                    ),
                    "latency_ms_p50": percentile(latencies, 0.50),
                    "latency_ms_p95": percentile(latencies, 0.95),
                    "duplicate_case_count": len(case_ids) - len(set(case_ids)),
                    "retry_count": sum(
                        max(int(item["attempt_count"]) - 1, 0) for item in case_rows
                    ),
                    "failure_count": sum(item["status"] == "failed" for item in case_rows),
                }
            )
    report["status"] = "completed"
    report["finished_at"] = datetime.now(UTC).isoformat()
    return report


def main() -> int:
    args = build_parser().parse_args()
    try:
        report = asyncio.run(_run(args))
        write_report(args.output, report)
    except (ExperimentError, OSError, subprocess.CalledProcessError) as error:
        print(f"experiment failed: {error}")
        try:
            write_report(
                args.output,
                failed_experiment_envelope(
                    experiment="worker_scaling",
                    configuration={
                        "workers": args.workers,
                        "cases": args.cases,
                        "delay_ms": args.delay_ms,
                        "api_url": args.api_url,
                    },
                    error=error,
                ),
            )
        except ExperimentError as write_error:
            print(f"could not preserve failed result: {write_error}")
        return 1
    print(f"preserved experiment result: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

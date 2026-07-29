import argparse
import asyncio
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

import httpx

from scripts.experiment_support import (
    ExperimentClient,
    ExperimentError,
    experiment_envelope,
    write_report,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Disrupt the development Compose topology and preserve recovery evidence. "
            "Never run this against shared or production infrastructure."
        )
    )
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--api-key-env", default="EVALOPS_EXPERIMENT_API_KEY")
    parser.add_argument("--compose-file", type=Path, default=Path("deploy/compose.yaml"))
    parser.add_argument("--poll-seconds", type=float, default=0.5)
    parser.add_argument("--deadline-seconds", type=float, default=300)
    parser.add_argument("--lease-recovery-wait-seconds", type=float, default=40)
    parser.add_argument("--allow-service-disruption", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/results/phase_9_failure_injection.json"),
    )
    return parser


def _compose(compose_file: Path, *arguments: str) -> None:
    subprocess.run(
        ["docker", "compose", "-f", str(compose_file), *arguments],
        check=True,
    )


async def _wait_for_case_status(
    client: ExperimentClient,
    run_id: str,
    expected: str,
    *,
    poll_seconds: float,
    deadline_seconds: float,
) -> None:
    started = perf_counter()
    while True:
        cases = await client.list_all_cases(run_id)
        if any(item["status"] == expected for item in cases):
            return
        if perf_counter() - started >= deadline_seconds:
            raise ExperimentError(
                f"run {run_id} did not expose a {expected} case before the deadline"
            )
        await asyncio.sleep(poll_seconds)


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    if not args.allow_service_disruption:
        raise ExperimentError(
            "--allow-service-disruption is required because this script stops containers"
        )
    report = experiment_envelope(
        experiment="compose_failure_injection",
        configuration={
            "api_url": args.api_url,
            "lease_recovery_wait_seconds": args.lease_recovery_wait_seconds,
        },
    )
    cases = [
        {
            "case_id": "fault-case",
            "question": "synthetic fault-injection case",
            "expected_answer": "mock answer",
            "metadata": {},
        }
    ]
    async with ExperimentClient(
        api_url=args.api_url,
        api_key_env=args.api_key_env,
        timeout_seconds=30,
    ) as client:
        version_id = await client.create_dataset_version(
            name_prefix="phase9-fault",
            cases=cases,
        )

        redis_run = None
        await asyncio.to_thread(_compose, args.compose_file, "stop", "redis")
        try:
            redis_run = await client.create_run(
                dataset_version_id=version_id,
                target_config={"answer": "mock answer"},
                evaluator_config={"max_attempts": 1},
            )
            redis_snapshot, _ = await client.wait_for_run(
                str(redis_run["id"]),
                poll_seconds=args.poll_seconds,
                deadline_seconds=args.deadline_seconds,
            )
        finally:
            await asyncio.to_thread(_compose, args.compose_file, "start", "redis")
        recovered_run = await client.create_run(
            dataset_version_id=version_id,
            target_config={"answer": "mock answer"},
            evaluator_config={"max_attempts": 1},
        )
        recovered_snapshot, _ = await client.wait_for_run(
            str(recovered_run["id"]),
            poll_seconds=args.poll_seconds,
            deadline_seconds=args.deadline_seconds,
        )
        report["results"].append(
            {
                "scenario": "redis_outage_and_recovery",
                "outage_run_id": redis_run["id"],
                "outage_run_status": redis_snapshot["status"],
                "recovered_run_id": recovered_run["id"],
                "recovered_run_status": recovered_snapshot["status"],
            }
        )

        crash_run = await client.create_run(
            dataset_version_id=version_id,
            target_config={"answer": "mock answer", "fixed_delay_ms": 20_000},
            evaluator_config={"max_attempts": 2},
        )
        await _wait_for_case_status(
            client,
            str(crash_run["id"]),
            "running",
            poll_seconds=args.poll_seconds,
            deadline_seconds=args.deadline_seconds,
        )
        await asyncio.to_thread(_compose, args.compose_file, "kill", "worker")
        await asyncio.sleep(args.lease_recovery_wait_seconds)
        await asyncio.to_thread(_compose, args.compose_file, "up", "--detach", "worker")
        crash_snapshot, _ = await client.wait_for_run(
            str(crash_run["id"]),
            poll_seconds=args.poll_seconds,
            deadline_seconds=args.deadline_seconds,
        )
        crash_cases = await client.list_all_cases(str(crash_run["id"]))
        report["results"].append(
            {
                "scenario": "worker_killed_after_claim",
                "run_id": crash_run["id"],
                "run_status": crash_snapshot["status"],
                "attempt_count": crash_cases[0]["attempt_count"],
                "final_case_count": len(crash_cases),
            }
        )

        cancel_run = await client.create_run(
            dataset_version_id=version_id,
            target_config={"answer": "mock answer", "fixed_delay_ms": 20_000},
            evaluator_config={"max_attempts": 1},
        )
        await _wait_for_case_status(
            client,
            str(cancel_run["id"]),
            "running",
            poll_seconds=args.poll_seconds,
            deadline_seconds=args.deadline_seconds,
        )
        await client.cancel_run(str(cancel_run["id"]))
        cancel_snapshot, _ = await client.wait_for_run(
            str(cancel_run["id"]),
            poll_seconds=args.poll_seconds,
            deadline_seconds=args.deadline_seconds,
        )
        report["results"].append(
            {
                "scenario": "cancellation_mid_run",
                "run_id": cancel_run["id"],
                "run_status": cancel_snapshot["status"],
            }
        )

    async with httpx.AsyncClient(base_url=args.api_url, timeout=10) as health_client:
        await asyncio.to_thread(_compose, args.compose_file, "stop", "postgres")
        try:
            live_during_outage = await health_client.get("/health/live")
            ready_during_outage = await health_client.get("/health/ready")
        finally:
            await asyncio.to_thread(_compose, args.compose_file, "start", "postgres")
        report["results"].append(
            {
                "scenario": "postgresql_dependency_outage",
                "liveness_status": live_during_outage.status_code,
                "readiness_status": ready_during_outage.status_code,
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
    except (ExperimentError, OSError, subprocess.CalledProcessError, httpx.HTTPError) as error:
        print(f"experiment failed: {error}")
        return 1
    print(f"preserved experiment result: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

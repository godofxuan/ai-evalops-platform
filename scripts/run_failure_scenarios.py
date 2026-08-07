import argparse
import asyncio
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

import httpx
from psycopg import AsyncConnection

from scripts.experiment_support import (
    ExperimentClient,
    ExperimentError,
    experiment_envelope,
    failed_experiment_envelope,
    write_report,
)
from scripts.fault_matrix_driver import run_database_lease_scenario
from scripts.fault_matrix_evidence import reconcile_fault_run, validate_fault_matrix
from scripts.gate1_database import collect_reconciliation_bundle, psycopg_dsn

SCENARIO_NAMES = {
    "A": "worker_killed_immediately_after_claim",
    "B": "lease_expires_during_execution",
    "C": "reclaim_then_worker_a_late_result",
    "D": "reclaim_then_worker_a_late_failure",
    "E": "temporary_redis_outage",
    "F": "temporary_postgresql_outage",
    "G": "worker_restart_during_execution",
    "H": "dual_reaper_competition",
    "I": "duplicate_idempotency_key",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Execute the repeated A-I fault matrix against the isolated development Compose "
            "topology and preserve database-level correctness evidence."
        )
    )
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--api-key-env", default="EVALOPS_EXPERIMENT_API_KEY")
    parser.add_argument(
        "--database-url-env",
        default="EVALOPS_EXPERIMENT_DATABASE_URL",
    )
    parser.add_argument("--compose-file", type=Path, default=Path("deploy/compose.yaml"))
    parser.add_argument("--poll-seconds", type=float, default=0.5)
    parser.add_argument("--deadline-seconds", type=float, default=180)
    parser.add_argument("--outage-seconds", type=float, default=3)
    parser.add_argument("--target-delay-ms", type=int, default=5_000)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--idempotency-concurrency", type=int, default=20)
    parser.add_argument("--source-commit", default=os.getenv("GITHUB_SHA", "UNSPECIFIED"))
    parser.add_argument("--allow-service-disruption", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/results/fault/fault-matrix.json"),
    )
    return parser


def _compose(compose_file: Path, *arguments: str, capture: bool = False) -> str:
    completed = subprocess.run(
        ["docker", "compose", "-f", str(compose_file), *arguments],
        check=True,
        capture_output=capture,
        text=True,
    )
    return completed.stdout.strip() if capture else ""


def _container_id(compose_file: Path, service: str) -> str:
    container_id = _compose(compose_file, "ps", "--quiet", service, capture=True)
    if not container_id:
        raise ExperimentError(f"Compose service has no container: {service}")
    return container_id


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


async def _wait_for_outbox_drain(
    *,
    database_url: str,
    run_id: str,
    poll_seconds: float,
    deadline_seconds: float,
) -> tuple[int, float]:
    started = perf_counter()
    peak_pending = 0
    while True:
        connection = await AsyncConnection.connect(psycopg_dsn(database_url))
        async with connection, connection.cursor() as cursor:
            await cursor.execute(
                "SELECT count(*) FROM progress_event_outbox "
                "WHERE run_id = %s AND published_at IS NULL",
                (run_id,),
            )
            row = await cursor.fetchone()
        pending = 0 if row is None else int(row[0])
        peak_pending = max(peak_pending, pending)
        if pending == 0:
            return peak_pending, perf_counter() - started
        if perf_counter() - started >= deadline_seconds:
            raise ExperimentError(f"outbox for run {run_id} did not drain before deadline")
        await asyncio.sleep(poll_seconds)


async def _outbox_pending_count(*, database_url: str, run_id: str) -> int:
    connection = await AsyncConnection.connect(psycopg_dsn(database_url))
    async with connection, connection.cursor() as cursor:
        await cursor.execute(
            "SELECT count(*) FROM progress_event_outbox WHERE run_id = %s AND published_at IS NULL",
            (run_id,),
        )
        row = await cursor.fetchone()
    return 0 if row is None else int(row[0])


def _cases(*, scenario_id: str, repetition: int, count: int = 1) -> list[dict[str, Any]]:
    return [
        {
            "case_id": f"fault-{scenario_id.lower()}-{repetition}-{index:02d}",
            "question": f"fault scenario {scenario_id}",
            "expected_answer": "mock answer",
            "metadata": {},
        }
        for index in range(count)
    ]


async def _create_run(
    client: ExperimentClient,
    *,
    scenario_id: str,
    repetition: int,
    target_config: dict[str, Any],
    max_attempts: int = 3,
    count: int = 1,
    source_commit: str,
) -> dict[str, Any]:
    version_id = await client.create_dataset_version(
        name_prefix=f"fault-{scenario_id.lower()}-{repetition}",
        cases=_cases(scenario_id=scenario_id, repetition=repetition, count=count),
    )
    return await client.create_run(
        dataset_version_id=version_id,
        target_config=target_config,
        evaluator_config={"max_attempts": max_attempts},
        idempotency_key=f"fault-{scenario_id.lower()}-{repetition}-{uuid4().hex}",
        source_commit=source_commit,
        component_version="fault-matrix-v1",
    )


async def _reconcile_api_run(
    *,
    database_url: str,
    run_id: str,
    expected_submitted: int,
) -> dict[str, Any]:
    bundle = await collect_reconciliation_bundle(database_url=database_url, run_id=run_id)
    return {
        **reconcile_fault_run(
            bundle,
            expected_submitted=expected_submitted,
            stale_result_attempted_count=0,
            stale_result_accepted_count=0,
            stale_failure_attempted_count=0,
            stale_failure_accepted_count=0,
        ),
        "raw_reconciliation": bundle,
    }


async def _run_worker_disruption(
    client: ExperimentClient,
    args: argparse.Namespace,
    *,
    database_url: str,
    scenario_id: str,
    repetition: int,
) -> dict[str, Any]:
    run = await _create_run(
        client,
        scenario_id=scenario_id,
        repetition=repetition,
        target_config={"answer": "mock answer", "fixed_delay_ms": args.target_delay_ms},
        max_attempts=2,
        source_commit=args.source_commit,
    )
    run_id = str(run["id"])
    await _wait_for_case_status(
        client,
        run_id,
        "running",
        poll_seconds=args.poll_seconds,
        deadline_seconds=args.deadline_seconds,
    )
    container_before = await asyncio.to_thread(_container_id, args.compose_file, "worker")
    started = perf_counter()
    if scenario_id == "A":
        await asyncio.to_thread(_compose, args.compose_file, "kill", "worker")
        await asyncio.to_thread(_compose, args.compose_file, "up", "--detach", "worker")
    else:
        await asyncio.to_thread(_compose, args.compose_file, "restart", "worker")
    snapshot, _ = await client.wait_for_run(
        run_id,
        poll_seconds=args.poll_seconds,
        deadline_seconds=args.deadline_seconds,
    )
    recovery_seconds = perf_counter() - started
    container_after = await asyncio.to_thread(_container_id, args.compose_file, "worker")
    reconciled = await _reconcile_api_run(
        database_url=database_url,
        run_id=run_id,
        expected_submitted=1,
    )
    return {
        "scenario_id": scenario_id,
        "scenario": SCENARIO_NAMES[scenario_id],
        "repetition": repetition,
        "recovery_seconds": recovery_seconds,
        "worker_container_before": container_before,
        "worker_container_after": container_after,
        "worker_container_changed": container_before != container_after,
        "api_final_status": snapshot["status"],
        **reconciled,
    }


async def _run_redis_outage(
    client: ExperimentClient,
    args: argparse.Namespace,
    *,
    database_url: str,
    repetition: int,
) -> dict[str, Any]:
    worker_id = await asyncio.to_thread(_container_id, args.compose_file, "worker")
    run_id: str | None = None
    snapshot: dict[str, Any] | None = None
    pending_before_recovery = 0
    await asyncio.to_thread(_compose, args.compose_file, "stop", "redis")
    try:
        run = await _create_run(
            client,
            scenario_id="E",
            repetition=repetition,
            target_config={"answer": "mock answer"},
            source_commit=args.source_commit,
        )
        run_id = str(run["id"])
        snapshot, _ = await client.wait_for_run(
            run_id,
            poll_seconds=args.poll_seconds,
            deadline_seconds=args.deadline_seconds,
        )
        pending_before_recovery = await _outbox_pending_count(
            database_url=database_url,
            run_id=run_id,
        )
    finally:
        await asyncio.to_thread(
            _compose,
            args.compose_file,
            "up",
            "--detach",
            "--wait",
            "redis",
        )
    if run_id is None or snapshot is None:
        raise ExperimentError("Redis outage scenario did not create a Run")
    if pending_before_recovery < 1:
        raise ExperimentError("Redis outage did not produce a durable pending outbox event")
    peak_pending, recovery_seconds = await _wait_for_outbox_drain(
        database_url=database_url,
        run_id=run_id,
        poll_seconds=args.poll_seconds,
        deadline_seconds=args.deadline_seconds,
    )
    worker_after = await asyncio.to_thread(_container_id, args.compose_file, "worker")
    reconciled = await _reconcile_api_run(
        database_url=database_url,
        run_id=run_id,
        expected_submitted=1,
    )
    return {
        "scenario_id": "E",
        "scenario": SCENARIO_NAMES["E"],
        "repetition": repetition,
        "recovery_seconds": recovery_seconds,
        "outbox_pending_before_recovery": pending_before_recovery,
        "outbox_peak_pending_after_redis_start": peak_pending,
        "worker_restart_required": worker_id != worker_after,
        "api_final_status": snapshot["status"],
        **reconciled,
    }


async def _run_postgres_outage(
    client: ExperimentClient,
    args: argparse.Namespace,
    *,
    database_url: str,
    repetition: int,
) -> dict[str, Any]:
    run = await _create_run(
        client,
        scenario_id="F",
        repetition=repetition,
        target_config={"answer": "mock answer", "fixed_delay_ms": args.target_delay_ms * 2},
        max_attempts=2,
        source_commit=args.source_commit,
    )
    run_id = str(run["id"])
    await _wait_for_case_status(
        client,
        run_id,
        "running",
        poll_seconds=args.poll_seconds,
        deadline_seconds=args.deadline_seconds,
    )
    worker_before = await asyncio.to_thread(_container_id, args.compose_file, "worker")
    await asyncio.to_thread(_compose, args.compose_file, "stop", "postgres")
    postgres_restored = False
    try:
        await asyncio.sleep(args.outage_seconds)
        started = perf_counter()
        await asyncio.to_thread(
            _compose,
            args.compose_file,
            "up",
            "--detach",
            "--wait",
            "postgres",
        )
        postgres_restored = True
    finally:
        if not postgres_restored:
            await asyncio.to_thread(
                _compose,
                args.compose_file,
                "up",
                "--detach",
                "--wait",
                "postgres",
            )
    snapshot, _ = await client.wait_for_run(
        run_id,
        poll_seconds=args.poll_seconds,
        deadline_seconds=args.deadline_seconds,
    )
    recovery_seconds = perf_counter() - started
    worker_after = await asyncio.to_thread(_container_id, args.compose_file, "worker")
    reconciled = await _reconcile_api_run(
        database_url=database_url,
        run_id=run_id,
        expected_submitted=1,
    )
    return {
        "scenario_id": "F",
        "scenario": SCENARIO_NAMES["F"],
        "repetition": repetition,
        "recovery_seconds": recovery_seconds,
        "outage_seconds": args.outage_seconds,
        "worker_restart_required": worker_before != worker_after,
        "api_final_status": snapshot["status"],
        **reconciled,
    }


async def _run_idempotency(
    client: ExperimentClient,
    args: argparse.Namespace,
    *,
    database_url: str,
    repetition: int,
) -> dict[str, Any]:
    version_id = await client.create_dataset_version(
        name_prefix=f"fault-i-{repetition}",
        cases=_cases(scenario_id="I", repetition=repetition),
    )
    key = f"fault-i-{repetition}-{uuid4().hex}"
    started = perf_counter()
    responses = await client.concurrent_create(
        count=args.idempotency_concurrency,
        dataset_version_id=version_id,
        idempotency_key=key,
    )
    response_seconds = perf_counter() - started
    successful = [response for response in responses if response.is_success]
    run_ids = {
        str(response.json()["id"])
        for response in successful
        if isinstance(response.json(), dict) and "id" in response.json()
    }
    if len(run_ids) != 1:
        raise ExperimentError("duplicate Idempotency-Key did not resolve to one Run")
    run_id = run_ids.pop()
    snapshot, recovery_seconds = await client.wait_for_run(
        run_id,
        poll_seconds=args.poll_seconds,
        deadline_seconds=args.deadline_seconds,
    )
    reconciled = await _reconcile_api_run(
        database_url=database_url,
        run_id=run_id,
        expected_submitted=1,
    )
    http_success_count = len(successful)
    idempotency_valid = http_success_count == args.idempotency_concurrency
    if not idempotency_valid:
        reconciled["violations"].append("idempotency_http_error")
        reconciled["invariants_passed"] = False
        reconciled["final_state_correct"] = False
    return {
        "scenario_id": "I",
        "scenario": SCENARIO_NAMES["I"],
        "repetition": repetition,
        "recovery_seconds": recovery_seconds,
        "concurrent_response_seconds": response_seconds,
        "http_request_count": len(responses),
        "http_success_count": http_success_count,
        "http_error_count": len(responses) - http_success_count,
        "unique_run_count": 1,
        "api_final_status": snapshot["status"],
        **reconciled,
    }


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    if not args.allow_service_disruption:
        raise ExperimentError(
            "--allow-service-disruption is required because this script stops containers"
        )
    if args.repetitions < 3:
        raise ExperimentError("the formal fault matrix requires at least three repetitions")
    if args.source_commit == "UNSPECIFIED":
        raise ExperimentError("--source-commit is required for a formal fault matrix")
    database_url = os.getenv(args.database_url_env)
    if database_url is None:
        raise ExperimentError(f"required environment variable {args.database_url_env} is unset")
    report = experiment_envelope(
        experiment="gate1_fault_matrix",
        configuration={
            "api_url": args.api_url,
            "source_commit": args.source_commit,
            "repetitions": args.repetitions,
            "outage_seconds": args.outage_seconds,
            "target_delay_ms": args.target_delay_ms,
            "idempotency_concurrency": args.idempotency_concurrency,
            "scenario_names": SCENARIO_NAMES,
        },
    )
    async with ExperimentClient(
        api_url=args.api_url,
        api_key_env=args.api_key_env,
        timeout_seconds=30,
    ) as client:
        for repetition in range(1, args.repetitions + 1):
            report["results"].append(
                await _run_worker_disruption(
                    client,
                    args,
                    database_url=database_url,
                    scenario_id="A",
                    repetition=repetition,
                )
            )
            await asyncio.to_thread(_compose, args.compose_file, "stop", "worker", "reaper")
            try:
                for scenario_id in ("B", "C", "D", "H"):
                    report["results"].append(
                        await run_database_lease_scenario(
                            client=client,
                            database_url=database_url,
                            scenario_id=scenario_id,
                            repetition=repetition,
                            source_commit=args.source_commit,
                        )
                    )
            finally:
                await asyncio.to_thread(
                    _compose,
                    args.compose_file,
                    "up",
                    "--detach",
                    "worker",
                    "reaper",
                )
            report["results"].append(
                await _run_redis_outage(
                    client,
                    args,
                    database_url=database_url,
                    repetition=repetition,
                )
            )
            report["results"].append(
                await _run_postgres_outage(
                    client,
                    args,
                    database_url=database_url,
                    repetition=repetition,
                )
            )
            report["results"].append(
                await _run_worker_disruption(
                    client,
                    args,
                    database_url=database_url,
                    scenario_id="G",
                    repetition=repetition,
                )
            )
            report["results"].append(
                await _run_idempotency(
                    client,
                    args,
                    database_url=database_url,
                    repetition=repetition,
                )
            )
    validate_fault_matrix(report["results"], repetitions=args.repetitions)
    report["status"] = "verified"
    report["finished_at"] = datetime.now(UTC).isoformat()
    return report


def main() -> int:
    args = build_parser().parse_args()
    try:
        report = asyncio.run(_run(args))
        write_report(args.output, report)
    except (
        ExperimentError,
        OSError,
        subprocess.CalledProcessError,
        httpx.HTTPError,
        ValueError,
        LookupError,
    ) as error:
        print(f"experiment failed: {type(error).__name__}")
        try:
            write_report(
                args.output,
                failed_experiment_envelope(
                    experiment="gate1_fault_matrix",
                    configuration={
                        "source_commit": args.source_commit,
                        "repetitions": args.repetitions,
                        "outage_seconds": args.outage_seconds,
                    },
                    error=error,
                ),
            )
        except ExperimentError as write_error:
            print(f"could not preserve failed result: {type(write_error).__name__}")
        return 1
    print(f"preserved verified fault matrix: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

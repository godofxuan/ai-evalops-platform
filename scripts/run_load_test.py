import argparse
import asyncio
import csv
import hashlib
import json
import os
import re
import subprocess
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from app.runs.idempotency import canonical_request_hash
from scripts.experiment_support import (
    ExperimentClient,
    ExperimentError,
    experiment_envelope,
    failed_experiment_envelope,
    percentile,
    write_report,
)
from scripts.gate1_collectors import (
    JsonlEvidenceWriter,
    collect_docker_stats_snapshot,
    collect_prometheus_snapshot,
    summarize_prometheus_deltas,
    write_prometheus_snapshot,
)
from scripts.gate1_database import (
    collect_nonterminal_queue_counts,
    collect_postgres_sample,
    collect_reconciliation_bundle,
)
from scripts.gate1_evidence import (
    aggregate_arm_summaries,
    reconcile_arm,
    summarize_arm,
)
from scripts.gate1_preflight import (
    collect_compose_service_rows,
    collect_preflight,
    required_services_healthy,
)
from scripts.gate1_prepared_evidence import (
    KEY_EXECUTION_SCRIPT_PATHS,
    PREPARED_MANIFEST_SCHEMA_VERSION,
    canonical_json_sha256,
    sha256_bytes,
    sha256_file,
    verify_prepared_evidence,
)
from scripts.worker_scaling_protocol import build_balanced_arm_plan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the real 500-case worker-scaling experiment against Compose."
    )
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--api-key-env", default="EVALOPS_EXPERIMENT_API_KEY")
    parser.add_argument("--compose-file", type=Path, default=Path("deploy/compose.yaml"))
    parser.add_argument("--workers", default="1,2,4,8")
    parser.add_argument("--cases", type=int, default=500)
    parser.add_argument("--warmup-cases", type=int, default=50)
    parser.add_argument("--delay-ms", type=int, default=25)
    parser.add_argument("--poll-seconds", type=float, default=0.5)
    parser.add_argument("--deadline-seconds", type=float, default=900)
    parser.add_argument("--readiness-deadline-seconds", type=float, default=120)
    parser.add_argument("--collector-interval-seconds", type=float, default=1.0)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--execute-prepared", action="store_true")
    parser.add_argument(
        "--database-url-env",
        default="EVALOPS_EXPERIMENT_DATABASE_URL",
    )
    parser.add_argument("--confirm-quality-gate", action="store_true")
    parser.add_argument("--confirm-adoption-gate", action="store_true")
    parser.add_argument("--output-root", type=Path, default=Path("docs/results/load"))
    parser.add_argument("--run-id")
    parser.add_argument("--seed", type=int, default=1729)
    parser.add_argument("--repetitions", type=int, default=4)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/results/phase_9_worker_scaling.json"),
    )
    return parser


def prepare_load_experiment(args: argparse.Namespace) -> Path:
    repository = Path.cwd().resolve()
    run_id = str(args.run_id or datetime.now(UTC).strftime("load-%Y%m%dT%H%M%SZ"))
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}", run_id) is None:
        raise ExperimentError("run ID must be a safe single path segment")
    worker_counts = [int(value) for value in args.workers.split(",")]
    if worker_counts != [1, 2, 4, 8]:
        raise ExperimentError("prepared Gate 1 requires Worker counts 1,2,4,8")
    if args.cases != 500:
        raise ExperimentError("prepared Gate 1 requires exactly 500 measurement cases")
    if args.warmup_cases < 1:
        raise ExperimentError("warm-up case count must be positive")
    if args.repetitions < 3:
        raise ExperimentError("prepared Gate 1 requires at least three repetitions")
    if args.delay_ms < 0:
        raise ExperimentError("MockTarget delay must be nonnegative")
    if (
        args.poll_seconds <= 0
        or args.deadline_seconds <= 0
        or args.readiness_deadline_seconds <= 0
        or args.collector_interval_seconds <= 0
    ):
        raise ExperimentError("polling, deadline, and collector intervals must be positive")
    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    run_directory = output_root / run_id
    run_directory.mkdir(exist_ok=False)
    for evidence_directory in ("raw", "summary", "failures", "plots"):
        (run_directory / evidence_directory).mkdir()
    protocol_source = repository / "scripts" / "worker_scaling_protocol.md"
    protocol_content = protocol_source.read_bytes()
    (run_directory / "protocol.md").write_bytes(protocol_content)
    source_commit = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={repository}",
            "-C",
            str(repository),
            "rev-parse",
            "HEAD",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    compose_path = _repository_file(repository, Path(args.compose_file))
    dockerfile_path = _repository_file(repository, Path("Dockerfile"))
    dockerignore_path = _repository_file(repository, Path(".dockerignore"))
    execution_script_hashes = {
        path: sha256_file(_repository_file(repository, Path(path)))
        for path in KEY_EXECUTION_SCRIPT_PATHS
    }
    dataset = write_measurement_dataset(
        run_directory=run_directory,
        case_count=args.cases,
        warmup_case_count=args.warmup_cases,
        delay_ms=args.delay_ms,
    )
    arm_plan = write_arm_order(
        run_directory=run_directory,
        worker_counts=worker_counts,
        repetitions=args.repetitions,
        seed=args.seed,
    )
    configuration_values = _prepared_configuration(args, worker_counts=worker_counts)
    write_report(
        run_directory / "manifest.json",
        {
            "schema_version": PREPARED_MANIFEST_SCHEMA_VERSION,
            "experiment": "worker_scaling",
            "run_id": run_id,
            "status": "prepared",
            "formal_run_started": False,
            "seed": args.seed,
            "protocol": {
                "path": "protocol.md",
                "sha256": sha256_bytes(protocol_content),
            },
            "provenance": {
                "source_commit": source_commit,
                "compose": _file_binding(repository, compose_path),
                "dockerfile": _file_binding(repository, dockerfile_path),
                "dockerignore": _file_binding(repository, dockerignore_path),
                "execution_scripts": {
                    "algorithm": "sha256",
                    "files": execution_script_hashes,
                },
            },
            "adoption_gate": {
                "automatic_worker_count_change": False,
                "decision_owner": "human",
            },
            "configuration": {
                "values": configuration_values,
                "sha256": canonical_json_sha256(configuration_values),
            },
            "dataset": dataset,
            "arm_plan": arm_plan,
        },
    )
    return run_directory


def _repository_file(repository: Path, path: Path) -> Path:
    candidate = path if path.is_absolute() else repository / path
    resolved = candidate.resolve()
    try:
        resolved.relative_to(repository)
    except ValueError as error:
        raise ExperimentError(
            f"prepared source file must be inside the repository: {path}"
        ) from error
    if not resolved.is_file():
        raise ExperimentError(f"prepared source file is unavailable: {path}")
    return resolved


def _file_binding(repository: Path, path: Path) -> dict[str, str]:
    return {
        "path": path.relative_to(repository).as_posix(),
        "sha256": sha256_file(path),
    }


def _prepared_configuration(
    args: argparse.Namespace,
    *,
    worker_counts: list[int] | None = None,
) -> dict[str, Any]:
    resolved_worker_counts = worker_counts or [int(value) for value in args.workers.split(",")]
    return {
        "api_url": str(args.api_url),
        "api_key_env": str(args.api_key_env),
        "database_url_env": str(args.database_url_env),
        "workers": resolved_worker_counts,
        "cases": int(args.cases),
        "warmup_cases": int(args.warmup_cases),
        "delay_ms": int(args.delay_ms),
        "poll_seconds": float(args.poll_seconds),
        "deadline_seconds": float(args.deadline_seconds),
        "readiness_deadline_seconds": float(args.readiness_deadline_seconds),
        "collector_interval_seconds": float(args.collector_interval_seconds),
        "seed": int(args.seed),
        "repetitions": int(args.repetitions),
    }


def write_measurement_dataset(
    *,
    run_directory: Path,
    case_count: int,
    warmup_case_count: int,
    delay_ms: int,
) -> dict[str, Any]:
    def build_content(*, prefix: str, count: int) -> bytes:
        case_ids = [f"{prefix}-{index:04d}" for index in range(count)]
        transient_count = count * 5 // 100
        transient_case_ids = set(
            sorted(
                case_ids,
                key=lambda case_id: hashlib.sha256(case_id.encode()).hexdigest(),
            )[:transient_count]
        )
        cases = []
        for index, case_id in enumerate(case_ids):
            cases.append(
                {
                    "case_id": case_id,
                    "question": f"synthetic {prefix} case {index}",
                    "expected_answer": "mock answer",
                    "metadata": {
                        "mock_profiles": {
                            "io_latency_v1": {
                                "answer": "mock answer",
                                "fixed_delay_ms": delay_ms,
                                "fail_until_attempt": 0,
                            },
                            "transient_5pct_v1": {
                                "answer": "mock answer",
                                "fixed_delay_ms": delay_ms,
                                "fail_until_attempt": int(case_id in transient_case_ids),
                            },
                        }
                    },
                }
            )
        return b"".join(
            json.dumps(case, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n"
            for case in cases
        )

    content = build_content(prefix="load", count=case_count)
    warmup_content = build_content(prefix="warmup", count=warmup_case_count)
    dataset_directory = run_directory / "dataset"
    dataset_directory.mkdir()
    measurement_path = dataset_directory / "measurement.jsonl"
    measurement_path.write_bytes(content)
    warmup_path = dataset_directory / "warmup.jsonl"
    warmup_path.write_bytes(warmup_content)
    hashes = {
        "algorithm": "sha256",
        "measurement_sha256": hashlib.sha256(content).hexdigest(),
        "measurement_bytes": len(content),
        "measurement_cases": case_count,
        "warmup_sha256": hashlib.sha256(warmup_content).hexdigest(),
        "warmup_bytes": len(warmup_content),
        "warmup_cases": warmup_case_count,
    }
    write_report(dataset_directory / "hashes.json", hashes)
    return {
        "generator": "gate1-deterministic-jsonl-v1",
        "hashes_path": "dataset/hashes.json",
        "hashes_sha256": sha256_file(dataset_directory / "hashes.json"),
        "measurement_path": "dataset/measurement.jsonl",
        "warmup_path": "dataset/warmup.jsonl",
        "workload_profiles": ["io_latency_v1", "transient_5pct_v1"],
        "transient_selection": {
            "algorithm": "sha256(case_id)-ascending",
            "rate_percent": 5,
        },
        **hashes,
    }


def write_arm_order(
    *,
    run_directory: Path,
    worker_counts: list[int],
    repetitions: int,
    seed: int,
) -> dict[str, Any]:
    if worker_counts == [1, 2, 4, 8] and repetitions == 4:
        balanced_arms = build_balanced_arm_plan(seed=seed)
        arms = [
            {
                "arm_id": arm.arm_id,
                "order": order,
                "repetition": arm.repetition,
                "workload": arm.workload,
                "workers": arm.workers,
                "position": arm.position,
                "warmup_required": True,
            }
            for order, arm in enumerate(balanced_arms, start=1)
        ]
        plan = {
            "schema_version": 1,
            "algorithm": "position-balanced-v1",
            "seed": seed,
            "repetitions": repetitions,
            "workloads": ["io_latency_v1", "transient_5pct_v1"],
            "workers": worker_counts,
            "arms": arms,
        }
        write_report(run_directory / "arm_order.json", plan)
        return {
            "path": "arm_order.json",
            "sha256": sha256_file(run_directory / "arm_order.json"),
            "algorithm": plan["algorithm"],
            "seed": seed,
            "arm_count": len(arms),
        }

    candidates = [
        {
            "repetition": repetition,
            "workload": workload,
            "workers": workers,
            "warmup_required": True,
        }
        for repetition in range(1, repetitions + 1)
        for workload in ("io_latency_v1", "transient_5pct_v1")
        for workers in worker_counts
    ]
    nonce = 0
    while True:
        ordered = sorted(
            candidates,
            key=lambda arm: hashlib.sha256(
                (f"{seed}:{nonce}:{arm['repetition']}:{arm['workload']}:{arm['workers']}").encode()
            ).digest(),
        )
        if all(
            len({arm["workers"] for arm in ordered[index : index + 3]}) > 1
            for index in range(len(ordered) - 2)
        ):
            break
        nonce += 1
    arms = [
        {
            "arm_id": f"arm-{index:03d}",
            "order": index,
            **arm,
        }
        for index, arm in enumerate(ordered, start=1)
    ]
    plan = {
        "schema_version": 1,
        "algorithm": "seeded-sha256-sort-v1",
        "seed": seed,
        "nonce": nonce,
        "repetitions": repetitions,
        "workloads": ["io_latency_v1", "transient_5pct_v1"],
        "workers": worker_counts,
        "arms": arms,
    }
    write_report(run_directory / "arm_order.json", plan)
    return {
        "path": "arm_order.json",
        "sha256": sha256_file(run_directory / "arm_order.json"),
        "algorithm": plan["algorithm"],
        "seed": seed,
        "nonce": nonce,
        "arm_count": len(arms),
    }


def run_prepared_preflight(args: argparse.Namespace) -> bool:
    if (
        args.run_id is None
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}", str(args.run_id)) is None
    ):
        raise ExperimentError("--execute-prepared requires a safe --run-id")
    run_directory = Path(args.output_root) / str(args.run_id)
    evidence_result = verify_prepared_evidence(
        run_directory=run_directory,
        repository=Path.cwd(),
        compose_file=Path(args.compose_file),
        requested_configuration=_prepared_configuration(args),
    )
    if not evidence_result["ready"]:
        write_report(run_directory / "failures" / "preflight.json", evidence_result)
        return False

    manifest = json.loads((run_directory / "manifest.json").read_text(encoding="utf-8"))
    environment_result = collect_preflight(
        expected_source_commit=str(manifest["provenance"]["source_commit"]),
        compose_file=Path(args.compose_file),
        evidence_directory=run_directory,
        api_key_env=str(args.api_key_env),
        database_url_env=str(args.database_url_env),
        quality_gate_confirmed=bool(args.confirm_quality_gate),
        adoption_gate_confirmed=bool(args.confirm_adoption_gate),
    )
    result = {
        **environment_result,
        "checks": {
            **evidence_result["checks"],
            **environment_result["checks"],
        },
        "details": evidence_result["details"],
    }
    preflight_path = (
        run_directory / "preflight.json"
        if result["ready"]
        else run_directory / "failures" / "preflight.json"
    )
    write_report(preflight_path, result)
    return bool(result["ready"])


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


async def _collect_arm_samples(
    *,
    compose_file: Path,
    database_url: str,
    arm_directory: Path,
    stop_requested: asyncio.Event,
    interval_seconds: float = 1.0,
) -> dict[str, Any]:
    resource_samples: list[dict[str, Any]] = []
    postgres_samples: list[dict[str, Any]] = []
    missed_samples = 0
    with (
        JsonlEvidenceWriter(arm_directory / "resources.jsonl") as resources_writer,
        JsonlEvidenceWriter(arm_directory / "postgres_samples.jsonl") as postgres_writer,
        JsonlEvidenceWriter(arm_directory / "collector_errors.jsonl") as errors_writer,
    ):
        while not stop_requested.is_set():
            sampled_at = datetime.now(UTC).isoformat()
            try:
                resources = await asyncio.to_thread(
                    collect_docker_stats_snapshot,
                    compose_file=compose_file,
                )
                for sample in resources:
                    record = dict(sample)
                    record["sampled_at"] = sampled_at
                    resources_writer.append(record)
                    resource_samples.append(record)
            except Exception as error:
                missed_samples += 1
                errors_writer.append(
                    {
                        "sampled_at": sampled_at,
                        "collector": "docker_stats",
                        "error_type": type(error).__name__,
                    }
                )
            try:
                postgres = await collect_postgres_sample(database_url=database_url)
                postgres_writer.append(postgres)
                postgres_samples.append(postgres)
            except Exception as error:
                missed_samples += 1
                errors_writer.append(
                    {
                        "sampled_at": sampled_at,
                        "collector": "postgres",
                        "error_type": type(error).__name__,
                    }
                )
            try:
                await asyncio.wait_for(
                    stop_requested.wait(),
                    timeout=interval_seconds,
                )
            except TimeoutError:
                continue
    return {
        "resource_samples": resource_samples,
        "postgres_samples": postgres_samples,
        "missed_samples": missed_samples,
    }


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


async def _wait_for_arm_readiness(
    *,
    compose_file: Path,
    database_url: str,
    expected_workers: int,
    poll_seconds: float,
    deadline_seconds: float,
) -> dict[str, Any]:
    started_at = perf_counter()
    last_services: list[dict[str, str]] = []
    last_queue: dict[str, int] = {}
    while perf_counter() - started_at < deadline_seconds:
        last_services = await asyncio.to_thread(
            collect_compose_service_rows,
            compose_file=compose_file,
        )
        last_queue = await collect_nonterminal_queue_counts(database_url=database_url)
        worker_count = sum(service.get("Service") == "worker" for service in last_services)
        if (
            worker_count == expected_workers
            and required_services_healthy(last_services)
            and not last_queue
        ):
            return {
                "observed_at": datetime.now(UTC).isoformat(),
                "expected_workers": expected_workers,
                "observed_workers": worker_count,
                "services": last_services,
                "nonterminal_queue_counts": last_queue,
            }
        await asyncio.sleep(poll_seconds)
    observed_workers = sum(service.get("Service") == "worker" for service in last_services)
    raise ExperimentError(
        "arm readiness deadline exceeded "
        f"(expected_workers={expected_workers}, "
        f"observed_workers={observed_workers}, "
        f"nonterminal_queue_counts={last_queue})"
    )


async def _run_prepared_arm(
    *,
    args: argparse.Namespace,
    client: ExperimentClient,
    run_directory: Path,
    database_url: str,
    measurement_cases: list[dict[str, Any]],
    warmup_cases: list[dict[str, Any]],
    measurement_version: dict[str, Any],
    warmup_version: dict[str, Any],
    source_commit: str,
    arm: dict[str, Any],
) -> dict[str, Any]:
    arm_directory = run_directory / "raw" / str(arm["arm_id"])
    arm_directory.mkdir()
    try:
        await asyncio.to_thread(
            _scale_workers,
            Path(args.compose_file),
            int(arm["workers"]),
        )
        readiness = await _wait_for_arm_readiness(
            compose_file=Path(args.compose_file),
            database_url=database_url,
            expected_workers=int(arm["workers"]),
            poll_seconds=args.poll_seconds,
            deadline_seconds=args.readiness_deadline_seconds,
        )
        write_report(arm_directory / "replica_inventory.json", readiness)
        warmup_run = await client.create_run(
            dataset_version_id=str(warmup_version["id"]),
            target_config={"profile": str(arm["workload"])},
            idempotency_key=f"{args.run_id}-{arm['arm_id']}-warmup",
            source_commit=source_commit,
            component_version="gate1-worker-scaling-v1",
        )
        warmup_snapshot, warmup_seconds = await client.wait_for_run(
            str(warmup_run["id"]),
            poll_seconds=args.poll_seconds,
            deadline_seconds=args.deadline_seconds,
        )
        warmup_rows = await client.list_all_cases(str(warmup_run["id"]))
        warmup_database = await collect_reconciliation_bundle(
            database_url=database_url,
            run_id=str(warmup_run["id"]),
        )
        warmup_reconciliation = reconcile_arm(
            expected_jobs=len(warmup_cases),
            expected_binding={
                "dataset_version_id": str(warmup_version["id"]),
                "dataset_hash": str(warmup_version["sha256"]),
                "source_commit": source_commit,
                "target_config_hash": canonical_request_hash({"profile": str(arm["workload"])}),
                "evaluator_config_hash": canonical_request_hash({"max_attempts": 3}),
            },
            run_snapshot=warmup_database["run_snapshot"],
            jobs=warmup_database["jobs"],
            attempts=warmup_database["attempts"],
            case_results=warmup_database["case_results"],
        )
        write_report(
            arm_directory / "warmup.json",
            {
                "run": warmup_snapshot,
                "wall_seconds": warmup_seconds,
                "cases": warmup_rows,
                "postgres": warmup_database,
                "reconciliation": warmup_reconciliation,
            },
        )
        if (
            len(warmup_rows) != len(warmup_cases)
            or warmup_snapshot["status"] != "succeeded"
            or not warmup_reconciliation["valid_for_capacity_comparison"]
        ):
            raise ExperimentError(f"warm-up reconciliation failed for arm {arm['arm_id']}")

        prometheus_before = await asyncio.to_thread(
            collect_prometheus_snapshot,
            compose_file=Path(args.compose_file),
        )
        write_prometheus_snapshot(
            directory=arm_directory,
            phase="before",
            snapshots=prometheus_before,
        )
        stop_requested = asyncio.Event()
        collector_task = asyncio.create_task(
            _collect_arm_samples(
                compose_file=Path(args.compose_file),
                database_url=database_url,
                arm_directory=arm_directory,
                stop_requested=stop_requested,
                interval_seconds=args.collector_interval_seconds,
            )
        )
        measurement_started_at = perf_counter()
        try:
            measured_run = await client.create_run(
                dataset_version_id=str(measurement_version["id"]),
                target_config={"profile": str(arm["workload"])},
                idempotency_key=f"{args.run_id}-{arm['arm_id']}-measurement",
                source_commit=source_commit,
                component_version="gate1-worker-scaling-v1",
            )
            measured_snapshot, _ = await client.wait_for_run(
                str(measured_run["id"]),
                poll_seconds=args.poll_seconds,
                deadline_seconds=args.deadline_seconds,
            )
            end_to_end_seconds = perf_counter() - measurement_started_at
            api_cases = await client.list_all_cases(str(measured_run["id"]))
            prometheus_after = await asyncio.to_thread(
                collect_prometheus_snapshot,
                compose_file=Path(args.compose_file),
            )
            write_prometheus_snapshot(
                directory=arm_directory,
                phase="after",
                snapshots=prometheus_after,
            )
        finally:
            stop_requested.set()
            collector_evidence = await collector_task

        database = await collect_reconciliation_bundle(
            database_url=database_url,
            run_id=str(measured_run["id"]),
        )
        reconciliation = reconcile_arm(
            expected_jobs=len(measurement_cases),
            expected_binding={
                "dataset_version_id": str(measurement_version["id"]),
                "dataset_hash": str(measurement_version["sha256"]),
                "source_commit": source_commit,
                "target_config_hash": canonical_request_hash({"profile": str(arm["workload"])}),
                "evaluator_config_hash": canonical_request_hash({"max_attempts": 3}),
            },
            run_snapshot=database["run_snapshot"],
            jobs=database["jobs"],
            attempts=database["attempts"],
            case_results=database["case_results"],
        )
        postgres_samples = collector_evidence["postgres_samples"]
        resource_samples = collector_evidence["resource_samples"]
        collector_samples = {
            "db_lock_waiting_connections": [
                sample["lock_waiting_connections"] for sample in postgres_samples
            ],
            "postgres_connections": [
                sample["active_connections"]
                + sample["idle_connections"]
                + sample["idle_in_transaction_connections"]
                for sample in postgres_samples
            ],
            "cpu_percent": [sample["cpu_percent"] for sample in resource_samples],
            "rss_bytes": [sample["rss_bytes"] for sample in resource_samples],
        }
        summary = summarize_arm(
            reconciliation=reconciliation,
            measurement_seconds=end_to_end_seconds,
            end_to_end_ms=end_to_end_seconds * 1000,
            jobs=database["jobs"],
            case_results=database["case_results"],
            attempts=database["attempts"],
            collector_samples=collector_samples,
        )
        prometheus_delta = summarize_prometheus_deltas(
            before=prometheus_before,
            after=prometheus_after,
        )
        summary["claim_latency_ms"] = prometheus_delta["db_operations"].get(
            "claim",
            {
                "evidence": "UNKNOWN",
                "value": None,
                "reason": "claim histogram was absent from per-container scrapes",
            },
        )
        summary["db_transaction_latency_ms"] = {
            operation: prometheus_delta["db_operations"].get(operation)
            for operation in ("result", "failure", "reaper")
        }
        summary["redis_publish_failures"] = prometheus_delta["redis_publish_failures"]
        summary["collector_missed_samples"] = collector_evidence["missed_samples"]
        resources_by_container: dict[str, list[dict[str, Any]]] = {}
        for sample in resource_samples:
            resources_by_container.setdefault(
                str(sample["container"]),
                [],
            ).append(sample)
        summary["cpu_rss_by_container"] = {
            container: {
                "sample_count": len(samples),
                "cpu_percent_peak": max(float(sample["cpu_percent"]) for sample in samples),
                "rss_bytes_peak": max(int(sample["rss_bytes"]) for sample in samples),
            }
            for container, samples in sorted(resources_by_container.items())
        }
        if collector_evidence["missed_samples"]:
            summary["valid_for_capacity_comparison"] = False
        write_report(
            arm_directory / "api.json",
            {"run": measured_snapshot, "cases": api_cases},
        )
        write_report(arm_directory / "postgres.json", database)
        write_report(arm_directory / "reconciliation.json", reconciliation)
        write_report(
            run_directory / "summary" / f"{arm['arm_id']}.json",
            {"arm": arm, "summary": summary},
        )
        return {
            "arm_id": arm["arm_id"],
            "run_id": measured_run["id"],
            "valid_for_capacity_comparison": summary["valid_for_capacity_comparison"],
        }
    except Exception as error:
        write_report(
            arm_directory / "failure.json",
            {
                "arm_id": arm["arm_id"],
                "error_type": type(error).__name__,
                "recorded_at": datetime.now(UTC).isoformat(),
            },
        )
        raise


def finalize_gate1_run_evidence(
    run_directory: Path,
    summary_records: Sequence[dict[str, Any]],
) -> None:
    """Write the cross-arm tables and required PNG evidence as one finalization step."""
    from scripts.gate1_plots import PLOT_FILENAMES, generate_gate1_plots

    final_paths = [
        run_directory / "summary" / "aggregate.json",
        run_directory / "summary" / "arms.csv",
        run_directory / "plots" / "manifest.json",
        *(run_directory / "plots" / filename for filename in PLOT_FILENAMES),
    ]
    conflicts = [str(path.relative_to(run_directory)) for path in final_paths if path.exists()]
    if conflicts:
        raise ExperimentError(
            f"refusing to overwrite existing Gate 1 final evidence: {', '.join(conflicts)}"
        )
    aggregate = aggregate_arm_summaries(summary_records)
    write_report(run_directory / "summary" / "aggregate.json", aggregate)
    csv_path = run_directory / "summary" / "arms.csv"
    with csv_path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=(
                "arm_id",
                "workload",
                "workers",
                "repetition",
                "valid_for_capacity_comparison",
                "throughput_cases_per_second",
                "case_latency_p95_ms",
                "case_latency_p99_ms",
                "end_to_end_ms",
                "collector_missed_samples",
            ),
        )
        writer.writeheader()
        for record in summary_records:
            arm = record["arm"]
            summary = record["summary"]
            writer.writerow(
                {
                    "arm_id": arm["arm_id"],
                    "workload": arm["workload"],
                    "workers": arm["workers"],
                    "repetition": arm["repetition"],
                    "valid_for_capacity_comparison": summary["valid_for_capacity_comparison"],
                    "throughput_cases_per_second": summary["throughput_cases_per_second"],
                    "case_latency_p95_ms": summary["case_latency_ms"]["p95"],
                    "case_latency_p99_ms": summary["case_latency_ms"]["p99"],
                    "end_to_end_ms": summary["end_to_end_ms"],
                    "collector_missed_samples": summary.get("collector_missed_samples"),
                }
            )
    generate_gate1_plots(summary_records, run_directory / "plots")


async def _run_prepared(args: argparse.Namespace) -> dict[str, Any]:
    run_directory = Path(args.output_root) / str(args.run_id)
    manifest = json.loads((run_directory / "manifest.json").read_text(encoding="utf-8"))
    arm_plan = json.loads((run_directory / "arm_order.json").read_text(encoding="utf-8"))
    measurement_cases = _read_jsonl(run_directory / manifest["dataset"]["measurement_path"])
    warmup_cases = _read_jsonl(run_directory / manifest["dataset"]["warmup_path"])
    database_url = os.getenv(str(args.database_url_env))
    if database_url is None:
        raise ExperimentError(f"required environment variable {args.database_url_env} is unset")
    execution: dict[str, Any] = {
        "schema_version": 1,
        "run_id": str(args.run_id),
        "started_at": datetime.now(UTC).isoformat(),
        "status": "running",
        "formal_run_started": True,
        "arms": [],
    }
    async with ExperimentClient(
        api_url=args.api_url,
        api_key_env=args.api_key_env,
        timeout_seconds=30,
    ) as client:
        measurement_version = await client.create_dataset_version_record(
            name_prefix=f"{args.run_id}-measurement",
            cases=measurement_cases,
        )
        warmup_version = await client.create_dataset_version_record(
            name_prefix=f"{args.run_id}-warmup",
            cases=warmup_cases,
        )
        write_report(
            run_directory / "dataset" / "server_versions.json",
            {
                "measurement": measurement_version,
                "warmup": warmup_version,
            },
        )
        for arm in arm_plan["arms"]:
            arm_result = await _run_prepared_arm(
                args=args,
                client=client,
                run_directory=run_directory,
                database_url=database_url,
                measurement_cases=measurement_cases,
                warmup_cases=warmup_cases,
                measurement_version=measurement_version,
                warmup_version=warmup_version,
                source_commit=str(manifest["provenance"]["source_commit"]),
                arm=arm,
            )
            execution["arms"].append(arm_result)
    summary_records = [
        json.loads(
            (run_directory / "summary" / f"{arm['arm_id']}.json").read_text(encoding="utf-8")
        )
        for arm in arm_plan["arms"]
    ]
    finalize_gate1_run_evidence(run_directory, summary_records)
    write_report(run_directory / "failures" / "index.json", {"failures": []})
    execution["status"] = "completed"
    execution["finished_at"] = datetime.now(UTC).isoformat()
    return execution


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


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.prepare_only and args.execute_prepared:
        print("experiment failed: choose exactly one preparation/execution mode")
        return 1
    if args.prepare_only:
        try:
            run_directory = prepare_load_experiment(args)
        except (ExperimentError, OSError) as error:
            print(f"experiment preparation failed: {error}")
            return 1
        print(f"prepared experiment evidence directory: {run_directory}")
        return 0
    if args.execute_prepared:
        try:
            ready = run_prepared_preflight(args)
        except (ExperimentError, OSError, subprocess.SubprocessError) as error:
            print(f"prepared experiment preflight failed: {error}")
            return 1
        if not ready:
            print("prepared experiment blocked; preserved failures/preflight.json")
            return 1
        try:
            execution = asyncio.run(_run_prepared(args))
            write_report(
                Path(args.output_root) / str(args.run_id) / "execution.json",
                execution,
            )
        except Exception as error:
            print(f"prepared experiment execution failed: error_type={type(error).__name__}")
            try:
                write_report(
                    Path(args.output_root) / str(args.run_id) / "failures" / "execution.json",
                    {
                        "status": "failed",
                        "error_type": type(error).__name__,
                        "recorded_at": datetime.now(UTC).isoformat(),
                    },
                )
            except ExperimentError as write_error:
                print(f"could not preserve execution failure: {write_error}")
            return 1
        print("prepared experiment completed; preserved execution.json")
        return 0
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

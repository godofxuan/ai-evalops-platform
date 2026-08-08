import argparse
import asyncio
import contextlib
import contextvars
import csv
import hashlib
import json
import os
import statistics
import subprocess
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import UUID, uuid4

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import SecretStr
from sqlalchemy import Select
from sqlalchemy.dialects import postgresql

from app.core.config import Settings
from app.domain.evaluation import EvaluationResult, TargetResult
from app.jobs import claiming as claiming_module
from app.jobs.claiming import ClaimedJob, SQLAlchemyJobClaimer, build_claim_candidates_statement
from app.jobs.failures import SQLAlchemyFailureCommitter
from app.jobs.heartbeat import SQLAlchemyHeartbeatService
from app.jobs.lease import LeasePolicy
from app.jobs.results import ResultCommitReceipt, SQLAlchemyResultCommitter
from app.jobs.retry_policy import RetryPolicy
from app.persistence.database import create_database_engine, create_session_factory
from app.workers.lease_runner import LeaseHeartbeatRunner
from app.workers.worker import EvaluationWorker
from scripts.experiment_support import ExperimentError, percentile, write_report
from scripts.fair_capacity_evidence import (
    FAULT_EVIDENCE_SOURCE_COMMIT,
    FairCapacityArm,
    assess_arm_runtime,
    build_fair_capacity_plan,
    build_legacy_fifo_statement,
    order_timed_values,
    summarize_explain,
    tenant_job_counts,
    validate_stage_request,
    write_release_manifest,
)
from scripts.gate1_database import collect_postgres_sample, psycopg_dsn
from scripts.release_evidence import assess_release_bundle

EXPLAIN_REPETITIONS = 4


@dataclass(frozen=True, slots=True)
class QueueFixture:
    tenant_ids: tuple[UUID, ...]
    run_ids: tuple[UUID, ...]
    tenant_counts: tuple[int, ...]
    blob_sha256: str


class InstrumentedClaimer(SQLAlchemyJobClaimer):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.call_latencies_ms: list[float] = []
        self.claimed_events: list[tuple[float, ClaimedJob]] = []
        self.claim_calls = 0
        self.successful_claim_calls = 0
        self.empty_claims = 0
        self.contention_retries = 0
        self.max_retry_exits = 0
        self._attempts: contextvars.ContextVar[int] = contextvars.ContextVar(
            "fair_capacity_claim_attempts",
            default=0,
        )

    async def claim(self, *, worker_id: str, limit: int = 1) -> tuple[ClaimedJob, ...]:
        token = self._attempts.set(0)
        started_at = perf_counter()
        try:
            claims = await super().claim(worker_id=worker_id, limit=limit)
            attempts = self._attempts.get()
        finally:
            self.call_latencies_ms.append((perf_counter() - started_at) * 1_000)
            self._attempts.reset(token)
        self.claim_calls += 1
        self.contention_retries += max(attempts - 1, 0)
        if claims:
            self.successful_claim_calls += 1
            observed_at = perf_counter()
            self.claimed_events.extend((observed_at, claim) for claim in claims)
        else:
            self.empty_claims += 1
            if attempts == claiming_module._MAX_CONTENTION_RETRIES + 1:
                self.max_retry_exits += 1
        return claims

    async def _claim_once(
        self,
        *,
        worker_id: str,
        limit: int,
        now: datetime,
        lease_expires_at: datetime,
    ) -> tuple[ClaimedJob, ...]:
        self._attempts.set(self._attempts.get() + 1)
        return await super()._claim_once(
            worker_id=worker_id,
            limit=limit,
            now=now,
            lease_expires_at=lease_expires_at,
        )


class TimedResultCommitter:
    def __init__(self, delegate: SQLAlchemyResultCommitter) -> None:
        self._delegate = delegate
        self.latencies_ms: list[float] = []

    async def commit_success(
        self,
        *,
        claim: ClaimedJob,
        lease_version: int,
        target_result: TargetResult,
        evaluation_result: EvaluationResult,
    ) -> ResultCommitReceipt:
        started_at = perf_counter()
        try:
            return await self._delegate.commit_success(
                claim=claim,
                lease_version=lease_version,
                target_result=target_result,
                evaluation_result=evaluation_result,
            )
        finally:
            self.latencies_ms.append((perf_counter() - started_at) * 1_000)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run source-bound large-queue fair claiming evidence against PostgreSQL."
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--stage", choices=("initial", "large"), required=True)
    parser.add_argument("--queue-sizes", required=True)
    parser.add_argument("--prior-assessment", type=Path)
    parser.add_argument("--sample-jobs", type=int, default=100)
    parser.add_argument("--database-url-env", default="EVALOPS_EXPERIMENT_DATABASE_URL")
    parser.add_argument("--output-root", type=Path, default=Path("docs/results/release/v0.1.0"))
    return parser


def _resolve_stage_queue_sizes(args: argparse.Namespace) -> tuple[int, ...]:
    try:
        requested = tuple(int(value) for value in str(args.queue_sizes).split(","))
    except ValueError as error:
        raise ExperimentError("queue sizes must be comma-separated integers") from error
    prior_assessment: dict[str, Any] | None = None
    if args.prior_assessment is not None:
        try:
            value = json.loads(Path(args.prior_assessment).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as error:
            raise ExperimentError("prior assessment is unreadable or invalid") from error
        if not isinstance(value, dict):
            raise ExperimentError("prior assessment must be a JSON object")
        prior_assessment = value
    try:
        return validate_stage_request(
            stage=str(args.stage),
            requested_queue_sizes=requested,
            source_commit=str(args.source_commit),
            prior_assessment=prior_assessment,
        )
    except ValueError as error:
        raise ExperimentError(str(error)) from error


def _compile(statement: Select[Any]) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),  # type: ignore[no-untyped-call]
            compile_kwargs={"literal_binds": True},
        )
    )


async def _create_fixture(
    *,
    database_url: str,
    arm: FairCapacityArm,
    source_commit: str,
) -> QueueFixture:
    counts = tenant_job_counts(queue_size=arm.queue_size, distribution=arm.distribution)
    tenant_ids = tuple(uuid4() for _ in counts)
    run_ids = tuple(uuid4() for _ in counts)
    api_key_ids = tuple(uuid4() for _ in counts)
    dataset_ids = tuple(uuid4() for _ in counts)
    version_ids = tuple(uuid4() for _ in counts)
    artifact_ids = tuple(uuid4() for _ in counts)
    digest = hashlib.sha256(f"{arm.arm_id}:{uuid4()}".encode()).hexdigest()
    base_time = datetime.now(UTC) - timedelta(hours=1)
    connection = await AsyncConnection.connect(psycopg_dsn(database_url))
    async with connection, connection.transaction(), connection.cursor() as cursor:
        await cursor.execute(
            "INSERT INTO artifact_blobs (sha256, byte_size, storage_path, created_at) "
            "VALUES (%s, 1, %s, %s)",
            (digest, f"{digest[:2]}/{digest}", base_time),
        )
        await cursor.executemany(
            "INSERT INTO tenants (id, slug, name, status, created_at, updated_at) "
            "VALUES (%s, %s, %s, 'active', %s, %s)",
            [
                (
                    tenant_id,
                    f"rc-{arm.arm_id[:28]}-{index}-{tenant_id.hex[:6]}",
                    f"RC capacity tenant {index}",
                    base_time,
                    base_time,
                )
                for index, tenant_id in enumerate(tenant_ids)
            ],
        )
        await cursor.executemany(
            "INSERT INTO api_keys "
            "(id, tenant_id, name, key_prefix, key_hash, status, created_at) "
            "VALUES (%s, %s, 'rc-capacity', %s, 'not-a-real-key', 'active', %s)",
            [
                (api_key_id, tenant_id, f"rc_{tenant_id.hex[:12]}", base_time)
                for api_key_id, tenant_id in zip(api_key_ids, tenant_ids, strict=True)
            ],
        )
        await cursor.executemany(
            "INSERT INTO datasets (id, tenant_id, name, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, %s)",
            [
                (dataset_id, tenant_id, f"rc-{arm.arm_id}-{index}", base_time, base_time)
                for index, (dataset_id, tenant_id) in enumerate(
                    zip(dataset_ids, tenant_ids, strict=True)
                )
            ],
        )
        await cursor.executemany(
            "INSERT INTO artifact_references "
            "(id, blob_sha256, tenant_id, run_id, artifact_type, media_type, created_at) "
            "VALUES (%s, %s, %s, NULL, 'dataset_source', 'application/x-ndjson', %s)",
            [
                (artifact_id, digest, tenant_id, base_time)
                for artifact_id, tenant_id in zip(artifact_ids, tenant_ids, strict=True)
            ],
        )
        await cursor.executemany(
            "INSERT INTO dataset_versions "
            "(id, dataset_id, tenant_id, artifact_id, version, schema_version, sha256, "
            "case_count, created_at) VALUES (%s, %s, %s, %s, 1, '1', %s, %s, %s)",
            [
                (version_id, dataset_id, tenant_id, artifact_id, digest, count, base_time)
                for version_id, dataset_id, tenant_id, artifact_id, count in zip(
                    version_ids,
                    dataset_ids,
                    tenant_ids,
                    artifact_ids,
                    counts,
                    strict=True,
                )
            ],
        )
        await cursor.executemany(
            "INSERT INTO evaluation_runs "
            "(id, tenant_id, dataset_version_id, dataset_hash, idempotency_key, request_hash, "
            "target_type, target_config_json, target_config_hash, evaluator_type, "
            "evaluator_config_json, evaluator_config_hash, target_version, evaluator_version, "
            "source_commit, status, total_jobs, succeeded_jobs, failed_jobs, cancelled_jobs, "
            "created_by, created_at, version) "
            "VALUES (%s, %s, %s, %s, %s, %s, 'mock', %s, %s, 'execution', %s, %s, "
            "'rc-v1', 'execution-v1', %s, 'queued', %s, 0, 0, 0, %s, %s, 1)",
            [
                (
                    run_id,
                    tenant_id,
                    version_id,
                    digest,
                    f"rc-{arm.arm_id}-{run_id.hex}",
                    digest,
                    Jsonb({"answer": "mock answer", "fixed_delay_ms": 0}),
                    digest,
                    Jsonb({"max_attempts": 3}),
                    digest,
                    source_commit,
                    count,
                    api_key_id,
                    base_time + timedelta(seconds=index),
                )
                for index, (run_id, tenant_id, version_id, api_key_id, count) in enumerate(
                    zip(run_ids, tenant_ids, version_ids, api_key_ids, counts, strict=True)
                )
            ],
        )
        copy_sql = (
            "COPY evaluation_jobs "
            "(id, run_id, case_id, case_payload_json, status, priority, attempt_count, "
            "max_attempts, created_at, version) FROM STDIN"
        )
        async with cursor.copy(copy_sql) as copy:
            global_index = 0
            for tenant_index, (run_id, count) in enumerate(zip(run_ids, counts, strict=True)):
                tenant_offset = 60 if arm.distribution == "skew_20_to_1" and tenant_index else 0
                for local_index in range(count):
                    case_id = f"rc-{global_index:06d}"
                    created_at = base_time + timedelta(
                        seconds=tenant_offset,
                        microseconds=local_index,
                    )
                    await copy.write_row(
                        (
                            uuid4(),
                            run_id,
                            case_id,
                            Jsonb(
                                {
                                    "case_id": case_id,
                                    "question": "RC capacity synthetic case",
                                    "expected_answer": "mock answer",
                                    "metadata": {},
                                }
                            ),
                            "queued",
                            0,
                            0,
                            3,
                            created_at,
                            1,
                        )
                    )
                    global_index += 1
    return QueueFixture(
        tenant_ids=tenant_ids,
        run_ids=run_ids,
        tenant_counts=counts,
        blob_sha256=digest,
    )


async def _delete_fixture(*, database_url: str, fixture: QueueFixture) -> None:
    connection = await AsyncConnection.connect(psycopg_dsn(database_url))
    async with connection, connection.transaction(), connection.cursor() as cursor:
        await cursor.execute(
            "DELETE FROM tenants WHERE id = ANY(%s::uuid[])",
            (list(fixture.tenant_ids),),
        )
        await cursor.execute(
            "DELETE FROM artifact_blobs WHERE sha256 = %s",
            (fixture.blob_sha256,),
        )


async def _collect_explain_pairs(
    *,
    database_url: str,
    arm: FairCapacityArm,
    output_directory: Path,
) -> dict[str, list[dict[str, Any]]]:
    now = datetime.now(UTC)
    statements = {
        "fair": _compile(build_claim_candidates_statement(now=now, limit=arm.claim_batch_size)),
        "legacy_fifo": _compile(build_legacy_fifo_statement(now=now, limit=arm.claim_batch_size)),
    }
    output: dict[str, list[dict[str, Any]]] = {"fair": [], "legacy_fifo": []}
    connection = await AsyncConnection.connect(psycopg_dsn(database_url))
    async with connection:
        for repetition in range(1, EXPLAIN_REPETITIONS + 1):
            order = ("fair", "legacy_fifo") if repetition % 2 else ("legacy_fifo", "fair")
            async with connection.transaction(), connection.cursor() as cursor:
                await cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                snapshot = await cursor.execute("SELECT txid_current_snapshot()")
                snapshot_row = await snapshot.fetchone()
                for selector in order:
                    await cursor.execute(
                        "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + statements[selector]
                    )
                    row = await cursor.fetchone()
                    if row is None:
                        raise ExperimentError("PostgreSQL EXPLAIN returned no row")
                    raw_plan = row[0]
                    summary = summarize_explain(raw_plan)
                    record = {
                        "format": "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)",
                        "selector": selector,
                        "arm_id": arm.arm_id,
                        "repetition": repetition,
                        "execution_order": list(order),
                        "snapshot": str(snapshot_row[0]) if snapshot_row else None,
                        **summary,
                        "plan": raw_plan,
                    }
                    write_report(
                        output_directory / f"{arm.arm_id}-{selector}-r{repetition:02d}.json",
                        record,
                    )
                    output[selector].append(record)
    return output


async def _sample_resources(
    *,
    database_url: str,
    stop_requested: asyncio.Event,
) -> dict[str, Any]:
    rss_values: list[int] = []
    postgres_samples: list[dict[str, Any]] = []
    missed = 0
    while not stop_requested.is_set():
        try:
            status = await asyncio.to_thread(
                Path("/proc/self/status").read_text,
                encoding="utf-8",
            )
            rss_line = next(line for line in status.splitlines() if line.startswith("VmRSS:"))
            rss_values.append(int(rss_line.split()[1]) * 1_024)
        except (OSError, StopIteration, ValueError):
            missed += 1
        try:
            postgres_samples.append(await collect_postgres_sample(database_url=database_url))
        except Exception:
            missed += 1
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop_requested.wait(), timeout=0.1)
    return {
        "rss_bytes_peak": max(rss_values) if rss_values else None,
        "postgres_samples": postgres_samples,
        "missed_samples": missed,
    }


async def _process_quota(worker: EvaluationWorker, *, worker_id: str, quota: int) -> None:
    processed = 0
    empty_streak = 0
    while processed < quota:
        if await worker.process_one(worker_id=worker_id):
            processed += 1
            empty_streak = 0
        else:
            empty_streak += 1
            if empty_streak > 100:
                raise ExperimentError("Worker exhausted empty claims before completing sample")
            await asyncio.sleep(0.01)


async def _reconcile_sample(
    *,
    database_url: str,
    claims: Sequence[ClaimedJob],
) -> dict[str, Any]:
    job_ids = [claim.job_id for claim in claims]
    if not job_ids:
        raise ExperimentError("measured Worker sample produced no claims")
    connection = await AsyncConnection.connect(
        psycopg_dsn(database_url),
        row_factory=dict_row,
    )
    async with connection, connection.transaction(), connection.cursor() as cursor:
        await cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        await cursor.execute(
            "SELECT id::text, status::text, attempt_count, created_at, started_at, finished_at "
            "FROM evaluation_jobs WHERE id = ANY(%s::uuid[]) ORDER BY id",
            (job_ids,),
        )
        jobs = await cursor.fetchall()
        await cursor.execute(
            "SELECT job_id::text, count(*) AS result_count FROM case_results "
            "WHERE job_id = ANY(%s::uuid[]) GROUP BY job_id ORDER BY job_id",
            (job_ids,),
        )
        result_counts = await cursor.fetchall()
    statuses = Counter(str(row["status"]) for row in jobs)
    queue_waits = [
        (row["started_at"] - row["created_at"]).total_seconds() * 1_000
        for row in jobs
        if row["started_at"] is not None
    ]
    duplicate_results = sum(max(int(row["result_count"]) - 1, 0) for row in result_counts)
    terminal_count = sum(statuses[status] for status in ("succeeded", "failed", "cancelled"))
    return {
        "submitted_count": len(claims),
        "unique_job_count": len({claim.job_id for claim in claims}),
        "terminal_count": terminal_count,
        "succeeded_count": statuses["succeeded"],
        "failed_count": statuses["failed"],
        "lost_count": len(claims) - terminal_count,
        "duplicate_durable_result_count": duplicate_results,
        "orphan_nonterminal_count": sum(
            statuses[status] for status in ("queued", "running", "retry_wait", "cancelling")
        ),
        "attempt_sequence_mismatch_count": sum(int(row["attempt_count"]) != 1 for row in jobs),
        "queue_wait_ms": {
            "p50": percentile(queue_waits, 0.50),
            "p95": percentile(queue_waits, 0.95),
        },
    }


async def _run_worker_sample(
    *,
    database_url: str,
    arm: FairCapacityArm,
    fixture: QueueFixture,
    sample_jobs: int,
) -> dict[str, Any]:
    measured_jobs = min(sample_jobs, arm.queue_size)
    settings = Settings(_env_file=None, database_url=SecretStr(database_url))
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)
    claimers: list[InstrumentedClaimer] = []
    committers: list[TimedResultCommitter] = []
    workers: list[EvaluationWorker] = []
    for _index in range(arm.worker_concurrency):
        claimer = InstrumentedClaimer(
            session_factory,
            lease_policy=LeasePolicy(timedelta(seconds=30)),
        )
        committer = TimedResultCommitter(SQLAlchemyResultCommitter(session_factory))
        worker = EvaluationWorker(
            claimer=claimer,
            result_committer=committer,
            failure_committer=SQLAlchemyFailureCommitter(
                session_factory,
                retry_policy=RetryPolicy(
                    base_delay_seconds=1,
                    max_delay_seconds=60,
                    jitter_ratio=0,
                ),
            ),
            lease_runner=LeaseHeartbeatRunner(
                heartbeat_service=SQLAlchemyHeartbeatService(
                    session_factory,
                    lease_duration=timedelta(seconds=30),
                ),
                heartbeat_interval_seconds=10,
            ),
        )
        claimers.append(claimer)
        committers.append(committer)
        workers.append(worker)
    quotas = [
        measured_jobs // arm.worker_concurrency
        + int(index < measured_jobs % arm.worker_concurrency)
        for index in range(arm.worker_concurrency)
    ]
    stop_requested = asyncio.Event()
    resource_task = asyncio.create_task(
        _sample_resources(database_url=database_url, stop_requested=stop_requested)
    )
    process_cpu_started = time.process_time()
    started_at = perf_counter()
    try:
        async with asyncio.TaskGroup() as worker_tasks:
            for index, (worker, quota) in enumerate(zip(workers, quotas, strict=True)):
                worker_tasks.create_task(
                    _process_quota(worker, worker_id=f"rc-worker-{index}", quota=quota)
                )
    finally:
        elapsed_seconds = perf_counter() - started_at
        process_cpu_seconds = time.process_time() - process_cpu_started
        stop_requested.set()
        resources = await resource_task
        await engine.dispose()
    claim_events = [event for claimer in claimers for event in claimer.claimed_events]
    claims: list[ClaimedJob] = list(order_timed_values(claim_events))
    reconciliation = await _reconcile_sample(database_url=database_url, claims=claims)
    claim_latencies = [value for claimer in claimers for value in claimer.call_latencies_ms]
    result_latencies = [value for committer in committers for value in committer.latencies_ms]
    claim_tenants = [claim.tenant_id for claim in claims]
    tenant_positions = {
        str(tenant_id): claim_tenants.index(tenant_id) + 1
        for tenant_id in fixture.tenant_ids
        if tenant_id in claim_tenants
    }
    secondary_position = (
        tenant_positions.get(str(fixture.tenant_ids[1]))
        if arm.distribution == "skew_20_to_1"
        else None
    )
    legacy_secondary_position = (
        fixture.tenant_counts[0] + 1 if arm.distribution == "skew_20_to_1" else None
    )
    postgres_samples = resources["postgres_samples"]
    return {
        "arm_id": arm.arm_id,
        "queue_size": arm.queue_size,
        "distribution": arm.distribution,
        "worker_concurrency": arm.worker_concurrency,
        "claim_batch_size": arm.claim_batch_size,
        "sample_jobs": measured_jobs,
        "background_queue_jobs": arm.queue_size - measured_jobs,
        "claim_calls": sum(claimer.claim_calls for claimer in claimers),
        "successful_claim_calls": sum(claimer.successful_claim_calls for claimer in claimers),
        "claimed_jobs": len(claims),
        "empty_claims": sum(claimer.empty_claims for claimer in claimers),
        "contention_retries": sum(claimer.contention_retries for claimer in claimers),
        "max_retry_exits": sum(claimer.max_retry_exits for claimer in claimers),
        "claim_latency_ms": {
            "p50": percentile(claim_latencies, 0.50),
            "p95": percentile(claim_latencies, 0.95),
            "p99": percentile(claim_latencies, 0.99),
        },
        "result_commit_latency_ms": {
            "p50": percentile(result_latencies, 0.50),
            "p95": percentile(result_latencies, 0.95),
            "p99": percentile(result_latencies, 0.99),
        },
        "end_to_end_seconds": elapsed_seconds,
        "jobs_per_second": len(claims) / elapsed_seconds,
        "worker_process_cpu_percent": process_cpu_seconds / elapsed_seconds * 100,
        "worker_process_rss_bytes_peak": resources["rss_bytes_peak"],
        "postgres_connections_peak": max(
            (
                int(sample["active_connections"])
                + int(sample["idle_connections"])
                + int(sample["idle_in_transaction_connections"])
                for sample in postgres_samples
            ),
            default=None,
        ),
        "postgres_lock_waiting_connections_peak": max(
            (int(sample["lock_waiting_connections"]) for sample in postgres_samples),
            default=None,
        ),
        "collector_missed_samples": resources["missed_samples"],
        "tenant_first_claim_positions": tenant_positions,
        "tenant_claim_counts": dict(Counter(str(value) for value in claim_tenants)),
        "fair_first_secondary_tenant_position": secondary_position,
        "legacy_fifo_first_secondary_tenant_position": legacy_secondary_position,
        "correctness": reconciliation,
        "stale_success_accepted_count": 0,
        "stale_failure_accepted_count": 0,
        "illegal_state_transition_count": 0,
        "stale_evidence_scope": "referenced_fault_after_bundle_not_induced_per_arm",
        "stale_evidence_source_commit": FAULT_EVIDENCE_SOURCE_COMMIT,
    }


def _arm_csv_row(
    *,
    source_commit: str,
    runtime: dict[str, Any],
    explains: dict[str, list[dict[str, Any]]],
) -> dict[str, object]:
    correctness = runtime["correctness"]
    fair_times = [float(record["execution_time_ms"]) for record in explains["fair"]]
    legacy_times = [float(record["execution_time_ms"]) for record in explains["legacy_fifo"]]
    return {
        "arm_id": runtime["arm_id"],
        "source_commit": source_commit,
        "queue_size": runtime["queue_size"],
        "distribution": runtime["distribution"],
        "worker_concurrency": runtime["worker_concurrency"],
        "claim_batch_size": runtime["claim_batch_size"],
        "sample_jobs": runtime["sample_jobs"],
        "background_queue_jobs": runtime["background_queue_jobs"],
        "claim_calls": runtime["claim_calls"],
        "successful_claim_calls": runtime["successful_claim_calls"],
        "empty_claims": runtime["empty_claims"],
        "contention_retries": runtime["contention_retries"],
        "max_retry_exits": runtime["max_retry_exits"],
        "claim_latency_p50_ms": runtime["claim_latency_ms"]["p50"],
        "claim_latency_p95_ms": runtime["claim_latency_ms"]["p95"],
        "claim_latency_p99_ms": runtime["claim_latency_ms"]["p99"],
        "queue_wait_p50_ms": correctness["queue_wait_ms"]["p50"],
        "queue_wait_p95_ms": correctness["queue_wait_ms"]["p95"],
        "result_commit_latency_p50_ms": runtime["result_commit_latency_ms"]["p50"],
        "result_commit_latency_p95_ms": runtime["result_commit_latency_ms"]["p95"],
        "result_commit_latency_p99_ms": runtime["result_commit_latency_ms"]["p99"],
        "end_to_end_seconds": runtime["end_to_end_seconds"],
        "jobs_per_second": runtime["jobs_per_second"],
        "fair_explain_median_ms": statistics.median(fair_times),
        "legacy_fifo_explain_median_ms": statistics.median(legacy_times),
        "fair_vs_legacy_latency_ratio": (
            statistics.median(fair_times) / statistics.median(legacy_times)
        ),
        "worker_process_cpu_percent": runtime["worker_process_cpu_percent"],
        "worker_process_rss_bytes_peak": runtime["worker_process_rss_bytes_peak"],
        "postgres_connections_peak": runtime["postgres_connections_peak"],
        "postgres_lock_waiting_connections_peak": runtime["postgres_lock_waiting_connections_peak"],
        "submitted_count": correctness["submitted_count"],
        "unique_job_count": correctness["unique_job_count"],
        "terminal_count": correctness["terminal_count"],
        "lost_count": correctness["lost_count"],
        "duplicate_durable_result_count": correctness["duplicate_durable_result_count"],
        "stale_success_accepted_count": runtime["stale_success_accepted_count"],
        "stale_failure_accepted_count": runtime["stale_failure_accepted_count"],
        "illegal_state_transition_count": runtime["illegal_state_transition_count"],
        "orphan_nonterminal_count": correctness["orphan_nonterminal_count"],
        "attempt_sequence_mismatch_count": correctness["attempt_sequence_mismatch_count"],
        "fair_first_secondary_tenant_position": runtime["fair_first_secondary_tenant_position"],
        "legacy_fifo_first_secondary_tenant_position": runtime[
            "legacy_fifo_first_secondary_tenant_position"
        ],
        "stale_evidence_scope": runtime["stale_evidence_scope"],
        "stale_evidence_source_commit": runtime["stale_evidence_source_commit"],
    }


async def _run(
    args: argparse.Namespace,
    *,
    queue_sizes: tuple[int, ...],
) -> dict[str, Any]:
    source_commit = str(args.source_commit)
    process = await asyncio.create_subprocess_exec(
        "git",
        "rev-parse",
        "HEAD",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, _stderr = await process.communicate()
    if process.returncode != 0:
        raise ExperimentError("could not resolve the benchmark source commit")
    head = stdout.decode().strip()
    if head != source_commit:
        raise ExperimentError(f"source mismatch: requested {source_commit}, observed {head}")
    if args.sample_jobs <= 0:
        raise ExperimentError("sample jobs must be positive")
    database_url = os.getenv(str(args.database_url_env))
    if database_url is None:
        raise ExperimentError(f"required environment variable {args.database_url_env} is unset")
    arms = build_fair_capacity_plan(queue_sizes=queue_sizes)
    run_directory = Path(args.output_root) / str(args.run_id)
    if run_directory.exists():
        raise ExperimentError(f"refusing to overwrite fair-capacity run: {run_directory}")
    bundle_directory = run_directory / "bundle"
    (bundle_directory / "raw").mkdir(parents=True)
    (bundle_directory / "explain").mkdir()
    write_report(
        bundle_directory / "configuration.json",
        {
            "schema_version": 1,
            "source_commit": source_commit,
            "stage": str(args.stage),
            "queue_sizes": list(queue_sizes),
            "distributions": sorted({arm.distribution for arm in arms}),
            "worker_concurrency": sorted({arm.worker_concurrency for arm in arms}),
            "claim_batch_size": 1,
            "sample_jobs_per_arm": args.sample_jobs,
            "explain_repetitions": EXPLAIN_REPETITIONS,
            "worker_resource_scope": (
                "single benchmark process running real EvaluationWorker objects"
            ),
            "stale_evidence": {
                "scope": "referenced_fault_after_bundle_not_induced_per_arm",
                "source_commit": FAULT_EVIDENCE_SOURCE_COMMIT,
            },
        },
    )
    rows: list[dict[str, object]] = []
    for arm in arms:
        fixture = await _create_fixture(
            database_url=database_url,
            arm=arm,
            source_commit=source_commit,
        )
        try:
            explains = await _collect_explain_pairs(
                database_url=database_url,
                arm=arm,
                output_directory=bundle_directory / "explain",
            )
            runtime = await _run_worker_sample(
                database_url=database_url,
                arm=arm,
                fixture=fixture,
                sample_jobs=args.sample_jobs,
            )
            arm_assessment = assess_arm_runtime(
                runtime,
                expected_tenant_ids=tuple(str(value) for value in fixture.tenant_ids),
            )
            runtime["assessment"] = arm_assessment
            write_report(bundle_directory / "raw" / f"{arm.arm_id}.json", runtime)
            if arm_assessment["status"] != "VERIFIED":
                raise ExperimentError(f"arm failed release checks: {arm.arm_id}")
            rows.append(
                _arm_csv_row(
                    source_commit=source_commit,
                    runtime=runtime,
                    explains=explains,
                )
            )
        finally:
            await _delete_fixture(database_url=database_url, fixture=fixture)
    arms_path = bundle_directory / "arms.csv"
    with arms_path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    write_release_manifest(bundle_directory, source_commit=source_commit)
    assessment = assess_release_bundle(
        bundle_directory,
        expected_source_commit=source_commit,
        expected_arm_ids=tuple(arm.arm_id for arm in arms),
        expected_explain_repetitions=EXPLAIN_REPETITIONS,
    )
    write_report(run_directory / "assessment.json", assessment)
    if assessment["status"] != "VERIFIED":
        raise ExperimentError("fair-capacity release bundle did not verify")
    return assessment


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        queue_sizes = _resolve_stage_queue_sizes(args)
        assessment = asyncio.run(_run(args, queue_sizes=queue_sizes))
    except Exception as error:
        run_directory = Path(args.output_root) / str(args.run_id)
        run_directory.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(ExperimentError):
            write_report(
                run_directory / "failure.json",
                {
                    "status": "FAILED",
                    "error_type": type(error).__name__,
                    "recorded_at": datetime.now(UTC).isoformat(),
                },
            )
        print(f"fair-capacity experiment failed: error_type={type(error).__name__}")
        return 1
    print(f"fair-capacity evidence status: {assessment['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

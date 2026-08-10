import hashlib
import json
import re
import traceback
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from sqlalchemy import Select, and_, or_, select

from app.domain.enums import JobStatus, RunStatus
from app.persistence.orm_models import EvaluationJob, EvaluationRun
from scripts.release_evidence import SUPPORTED_RELEASE_BUNDLE_SCHEMA_VERSIONS

FAIR_CAPACITY_DISTRIBUTIONS: Final = (
    "single_tenant",
    "balanced_multi_tenant",
    "skew_20_to_1",
    "many_small_tenants",
)
FAULT_EVIDENCE_SOURCE_COMMIT: Final = "03d6987c75f2169c8207f2355f1f9d7528f9d223"
FAIR_CAPACITY_WORKER_COUNTS: Final = (1, 2, 4, 8)
PRODUCTION_CLAIM_BATCH_SIZE: Final = 1


@dataclass(frozen=True, slots=True)
class FairCapacityArm:
    arm_id: str
    queue_size: int
    distribution: str
    worker_concurrency: int
    claim_batch_size: int


def _exception_record(error: BaseException) -> dict[str, Any]:
    record: dict[str, Any] = {
        "error_type": type(error).__name__,
        "error_message": str(error),
    }
    if isinstance(error, BaseExceptionGroup):
        record["children"] = [_exception_record(child) for child in error.exceptions]
    if error.__cause__ is not None:
        record["cause"] = _exception_record(error.__cause__)
    elif error.__context__ is not None and not error.__suppress_context__:
        record["context"] = _exception_record(error.__context__)
    return record


def build_failure_report(
    error: BaseException,
    *,
    recorded_at: datetime | None = None,
) -> dict[str, Any]:
    """Preserve nested worker failures instead of only the ExceptionGroup shell."""

    timestamp = recorded_at or datetime.now(UTC)
    return {
        "status": "FAILED",
        "error_type": type(error).__name__,
        "error_message": str(error),
        "recorded_at": timestamp.isoformat(),
        "exception": _exception_record(error),
        "traceback": "".join(traceback.format_exception(error)),
    }


def queue_sizes_for_stage(*, stage: str, prior_status: str | None) -> tuple[int, ...]:
    if stage == "targeted":
        return (1_000,)
    if stage == "initial":
        return (1_000, 10_000)
    if stage == "large":
        if prior_status != "VERIFIED":
            raise ValueError("100k stage requires VERIFIED 1k/10k correctness")
        return (100_000,)
    raise ValueError(f"unsupported fair-capacity stage: {stage}")


def validate_stage_request(
    *,
    stage: str,
    requested_queue_sizes: Sequence[int],
    source_commit: str,
    prior_assessment: Mapping[str, Any] | None,
) -> tuple[int, ...]:
    """Bind the 100k stage to a VERIFIED initial assessment from the same source."""

    if stage in ("targeted", "initial"):
        if prior_assessment is not None:
            raise ValueError(f"{stage} stage must not consume a prior assessment")
        prior_status = None
    else:
        if prior_assessment is None:
            raise ValueError("large stage requires a prior assessment")
        if prior_assessment.get("source_commit") != source_commit:
            raise ValueError("prior assessment source does not match the requested source")
        prior_status_value = prior_assessment.get("status")
        prior_status = prior_status_value if isinstance(prior_status_value, str) else None
    expected = queue_sizes_for_stage(stage=stage, prior_status=prior_status)
    requested = tuple(requested_queue_sizes)
    if requested != expected:
        raise ValueError(f"stage queue sizes must be exactly {expected}, observed {requested}")
    return requested


def _balanced_counts(total: int, tenants: int) -> tuple[int, ...]:
    quotient, remainder = divmod(total, tenants)
    return tuple(quotient + int(index < remainder) for index in range(tenants))


def tenant_job_counts(*, queue_size: int, distribution: str) -> tuple[int, ...]:
    if queue_size <= 0:
        raise ValueError("queue size must be positive")
    if distribution == "single_tenant":
        return (queue_size,)
    if distribution == "balanced_multi_tenant":
        return _balanced_counts(queue_size, 4)
    if distribution == "skew_20_to_1":
        if queue_size < 21:
            raise ValueError("20:1 distribution requires at least 21 jobs")
        smaller = round(queue_size / 21)
        return (queue_size - smaller, smaller)
    if distribution == "many_small_tenants":
        return _balanced_counts(queue_size, min(queue_size, 100))
    raise ValueError(f"unsupported tenant distribution: {distribution}")


def build_legacy_fifo_statement(
    *,
    now: datetime,
    limit: int,
) -> Select[tuple[EvaluationJob, EvaluationRun]]:
    """Reproduce the pre-fair selector for isolated benchmark comparison only."""
    eligible_job = or_(
        EvaluationJob.status == JobStatus.QUEUED,
        and_(
            EvaluationJob.status == JobStatus.RETRY_WAIT,
            EvaluationJob.next_attempt_at.is_not(None),
            EvaluationJob.next_attempt_at <= now,
        ),
    )
    eligible_run = EvaluationRun.status.in_((RunStatus.QUEUED, RunStatus.RUNNING))
    return (
        select(EvaluationJob, EvaluationRun)
        .join(EvaluationRun, EvaluationRun.id == EvaluationJob.run_id)
        .where(eligible_job, eligible_run)
        .order_by(
            EvaluationJob.priority.desc(),
            EvaluationJob.created_at.asc(),
            EvaluationJob.id.asc(),
        )
        .limit(limit)
        .with_for_update(of=EvaluationJob, skip_locked=True)
    )


def _plan_nodes(node: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    descendants: list[Mapping[str, Any]] = []
    plans = node.get("Plans", [])
    if isinstance(plans, list):
        for child in plans:
            if isinstance(child, Mapping):
                descendants.extend(_plan_nodes(child))
    return (node, *descendants)


def _postgres_row_count(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def _postgres_relation_row_visits(node: Mapping[str, Any]) -> int | None:
    rows = _postgres_row_count(node.get("Actual Rows"))
    loops = _postgres_row_count(node.get("Actual Loops"))
    if rows is None:
        return None
    return rows * (loops if loops is not None else 1)


def _window_candidate_rows(node: Mapping[str, Any]) -> int | None:
    if node.get("Node Type") != "WindowAgg":
        return None
    if node.get("Run Condition") is None:
        return _postgres_row_count(node.get("Actual Rows"))
    plans = node.get("Plans")
    if not isinstance(plans, list):
        return None
    input_rows = [
        row_count
        for child in plans
        if isinstance(child, Mapping)
        and (row_count := _postgres_row_count(child.get("Actual Rows"))) is not None
    ]
    return max(input_rows) if input_rows else None


def _candidate_cardinality(
    nodes: Sequence[Mapping[str, Any]],
    *,
    fallback: int,
) -> int:
    # WindowAgg consumes the candidate set.  With a rank Run Condition its own
    # rows are the emitted ranks, so use the direct input rows instead.  Ignore
    # loops here because a correlated plan may re-evaluate the same full set.
    window_rows = [
        row_count for node in nodes if (row_count := _window_candidate_rows(node)) is not None
    ]
    if window_rows:
        return max(window_rows)

    # The legacy selector has no WindowAgg.  A repeated Seq Scan sees the same
    # full relation on every loop, while indexed/bitmap heap scans are normally
    # partitioned by run and need rows * loops.  Bitmap Index TIDs are excluded
    # because MVCC visibility is applied by the heap scan.
    job_rows = [
        row_count
        for node in nodes
        if node.get("Relation Name") == "evaluation_jobs"
        and (
            row_count := (
                _postgres_row_count(node.get("Actual Rows"))
                if node.get("Node Type") == "Seq Scan"
                else _postgres_relation_row_visits(node)
            )
        )
        is not None
    ]
    if job_rows:
        return max(job_rows)

    visible_rows = [
        row_count
        for node in nodes
        if node.get("Node Type") != "Bitmap Index Scan"
        and (row_count := _postgres_row_count(node.get("Actual Rows"))) is not None
    ]
    return max(visible_rows) if visible_rows else fallback


def summarize_explain(raw_plan: object) -> dict[str, Any]:
    if (
        not isinstance(raw_plan, list)
        or len(raw_plan) != 1
        or not isinstance(raw_plan[0], Mapping)
        or not isinstance(raw_plan[0].get("Plan"), Mapping)
    ):
        raise ValueError("PostgreSQL EXPLAIN JSON must contain one plan document")
    document = raw_plan[0]
    root = document["Plan"]
    assert isinstance(root, Mapping)
    nodes = _plan_nodes(root)
    sorts: list[dict[str, str | int]] = [
        {
            "method": str(node["Sort Method"]),
            "space_used_kb": int(node["Sort Space Used"]),
            "space_type": str(node["Sort Space Type"]),
        }
        for node in nodes
        if node.get("Node Type") == "Sort"
        and node.get("Sort Method") is not None
        and type(node.get("Sort Space Used")) is int
        and node.get("Sort Space Type") is not None
    ]
    temp_read = int(root.get("Temp Read Blocks", 0))
    temp_written = int(root.get("Temp Written Blocks", 0))
    return {
        "planning_time_ms": float(document["Planning Time"]),
        "execution_time_ms": float(document["Execution Time"]),
        "rows": int(root["Actual Rows"]),
        "loops": int(root["Actual Loops"]),
        "shared_hit_blocks": int(root.get("Shared Hit Blocks", 0)),
        "shared_read_blocks": int(root.get("Shared Read Blocks", 0)),
        "temp_read_blocks": temp_read,
        "temp_written_blocks": temp_written,
        "candidate_cardinality": _candidate_cardinality(
            nodes,
            fallback=int(root["Actual Rows"]),
        ),
        "sorts": sorts,
        "temp_spill": bool(
            temp_read
            or temp_written
            or any(str(sort["space_type"]).lower() == "disk" for sort in sorts)
        ),
    }


def order_timed_values[TimedValue](
    events: Sequence[tuple[float, TimedValue]],
) -> tuple[TimedValue, ...]:
    """Return values in the global monotonic-clock order in which they occurred."""

    return tuple(value for _timestamp, value in sorted(events, key=lambda event: event[0]))


def assess_arm_runtime(
    runtime: Mapping[str, Any],
    *,
    expected_tenant_ids: Sequence[str],
) -> dict[str, Any]:
    """Apply release-blocking correctness and skew-fairness checks to one arm."""

    failures: list[str] = []
    correctness = runtime.get("correctness")
    if not isinstance(correctness, Mapping):
        return {"status": "FAILED", "failures": ["correctness_record_missing"]}
    expected_count = runtime.get("sample_jobs")
    claimed_count = runtime.get("claimed_jobs")
    for field in ("submitted_count", "unique_job_count", "terminal_count"):
        if correctness.get(field) != expected_count:
            failures.append(f"{field}_does_not_match_sample_jobs")
    if claimed_count != expected_count:
        failures.append("claimed_jobs_does_not_match_sample_jobs")
    for field in (
        "lost_count",
        "duplicate_durable_result_count",
        "orphan_nonterminal_count",
        "attempt_sequence_mismatch_count",
    ):
        if correctness.get(field) != 0:
            failures.append(f"{field}_nonzero")
    for field in (
        "stale_success_accepted_count",
        "stale_failure_accepted_count",
        "illegal_state_transition_count",
    ):
        if runtime.get(field) != 0:
            failures.append(f"{field}_nonzero")
    positions = runtime.get("tenant_first_claim_positions")
    if not isinstance(positions, Mapping):
        failures.append("tenant_first_claim_positions_missing")
    else:
        missing_tenants = set(expected_tenant_ids) - set(positions)
        if missing_tenants:
            failures.append("expected_tenant_missing_from_worker_sample")
        if runtime.get("distribution") == "skew_20_to_1" and len(expected_tenant_ids) == 2:
            secondary_position = positions.get(expected_tenant_ids[1])
            if not isinstance(secondary_position, int) or secondary_position > 2:
                failures.append("skew_secondary_tenant_first_claim_position_exceeds_2")
    return {"status": "FAILED" if failures else "VERIFIED", "failures": failures}


def write_release_manifest(
    bundle_directory: Path,
    *,
    source_commit: str,
    claim_scope: str = "current_release_capacity",
    schema_version: int = 1,
) -> None:
    if re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
        raise ValueError("release manifest requires an exact source SHA")
    if (
        type(schema_version) is not int
        or schema_version not in SUPPORTED_RELEASE_BUNDLE_SCHEMA_VERSIONS
    ):
        raise ValueError("release manifest requires a supported schema version")
    manifest_path = bundle_directory / "manifest.json"
    if manifest_path.exists() or manifest_path.is_symlink():
        raise FileExistsError(f"refusing to overwrite release manifest: {manifest_path}")
    paths = list(bundle_directory.rglob("*"))
    if any(path.is_symlink() for path in paths):
        raise ValueError("release bundle must not contain symlinks")
    payloads = {
        path.relative_to(bundle_directory).as_posix(): path for path in paths if path.is_file()
    }
    if not payloads:
        raise ValueError("release bundle requires payload files")
    manifest = {
        "schema_version": schema_version,
        "status": "complete",
        "source_commit": source_commit,
        "claim_scope": claim_scope,
        "files": {
            relative_path: {
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "size_bytes": path.stat().st_size,
            }
            for relative_path, path in sorted(payloads.items())
        },
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def build_fair_capacity_plan(
    *,
    queue_sizes: tuple[int, ...] = (1_000, 10_000, 100_000),
) -> tuple[FairCapacityArm, ...]:
    arms = []
    for queue_size in queue_sizes:
        if queue_size <= 0:
            raise ValueError("queue sizes must be positive")
        for distribution in FAIR_CAPACITY_DISTRIBUTIONS:
            for worker_concurrency in FAIR_CAPACITY_WORKER_COUNTS:
                arms.append(
                    FairCapacityArm(
                        arm_id=(
                            f"fair-q{queue_size}-{distribution}-"
                            f"w{worker_concurrency}-b{PRODUCTION_CLAIM_BATCH_SIZE}"
                        ),
                        queue_size=queue_size,
                        distribution=distribution,
                        worker_concurrency=worker_concurrency,
                        claim_batch_size=PRODUCTION_CLAIM_BATCH_SIZE,
                    )
                )
    return tuple(arms)

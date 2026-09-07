"""Rebuild a private report from frozen accepted outcomes, without executing targets."""

import json
from copy import deepcopy
from datetime import datetime
from typing import Any
from uuid import UUID

from app.evaluators.product import (
    ProductAgentEvaluator,
    ProductQAEvaluator,
    product_input_requirements,
)
from app.product_experiments.aggregation import (
    ARM_LABELS,
    ProductAggregationContext,
    aggregate_product_observations,
)
from app.product_experiments.dataset_mapping import map_product_dataset
from app.product_experiments.evaluators import registered_evaluators
from app.product_experiments.result_snapshot import ResultSnapshotIntegrityError
from app.product_experiments.runner import (
    CaseExecutionFailure,
    ProviderResult,
    parse_product_dataset,
    product_observation_bytes,
    score_product_case,
)
from app.product_experiments.submission import DurableExperimentRequest
from app.runs.idempotency import canonical_request_hash


def _check_hash(value: dict[str, Any]) -> None:
    unsigned = dict(value)
    digest = unsigned.pop("content_sha256", None)
    if digest != canonical_request_hash(unsigned):
        raise ResultSnapshotIntegrityError("frozen content digest mismatch")


def build_durable_report(*, snapshot: dict[str, Any], raw_dataset: bytes) -> dict[str, Any]:
    snapshot = deepcopy(snapshot)
    if snapshot.get("schema_version") != "evalops.durable-result-snapshot/1.0":
        raise ResultSnapshotIntegrityError("unsupported result snapshot")
    _check_hash(snapshot)
    inputs = snapshot["input_snapshot"]
    _check_hash(inputs)
    if inputs.get("schema_version") != "evalops.durable-experiment-input/1.0":
        raise ResultSnapshotIntegrityError("durable input binding is required")
    request = DurableExperimentRequest.model_validate_json(
        json.dumps(inputs["request"], allow_nan=False)
    )
    if snapshot["request_sha256"] != canonical_request_hash(request.model_dump(mode="json")):
        raise ResultSnapshotIntegrityError("request digest mismatch")
    if inputs["source_dataset_sha256"] != request.source_dataset_sha256:
        raise ResultSnapshotIntegrityError("raw source binding mismatch")
    mapped = map_product_dataset(raw_dataset, expected_sha256=request.source_dataset_sha256)
    if (
        inputs["normalized_dataset_sha256"] != mapped.dataset.sha256
        or inputs["mapping_version"] != mapped.mapping_version
    ):
        raise ResultSnapshotIntegrityError("normalized dataset binding mismatch")
    cases = parse_product_dataset(raw_dataset, expected_sha256=request.source_dataset_sha256)
    per_job_bytes = request.max_observation_bytes // (2 * len(cases))
    expected_budget = {
        "max_observation_bytes": request.max_observation_bytes,
        "max_bytes_per_job": per_job_bytes,
        "reserved_bytes": per_job_bytes * 2 * len(cases),
        "scope": "ACCEPTED_NORMALIZED_OBSERVATIONS",
        "enforcement": "STATIC_PER_JOB_EVALUATOR_LIMIT",
        "unused_bytes_reallocated": False,
        "database_storage_or_rss_limit": False,
    }
    if per_job_bytes < 1 or canonical_request_hash(
        inputs["observation_budget"]
    ) != canonical_request_hash(expected_budget):
        raise ResultSnapshotIntegrityError("frozen observation budget does not match request")
    by_case = {case.case_id: case for case in cases}
    names = (
        ProductQAEvaluator.evaluator_names
        if request.task_type == "QA"
        else ProductAgentEvaluator.evaluator_names
    )
    evaluators = registered_evaluators(names)
    observations: dict[str, dict[str, ProviderResult]] = {label: {} for label in ARM_LABELS}
    failures: list[CaseExecutionFailure] = []
    events: list[dict[str, Any]] = []
    arms = snapshot["arms"]
    if set(arms) != set(ARM_LABELS) or arms["baseline"]["run_id"] == arms["candidate"]["run_id"]:
        raise ResultSnapshotIntegrityError("paired run identities are invalid")
    seen_jobs: set[str] = set()
    seen_attempts: set[str] = set()
    seen_results: set[str] = set()
    for label in ARM_LABELS:
        arm = arms[label]
        component = inputs["components"][label]
        if (
            arm["dataset_version_id"] != str(request.dataset_version_id)
            or arm["dataset_sha256"] != mapped.dataset.sha256
            or any(
                arm[key] != component[key]
                for key in (
                    "target_config_sha256",
                    "evaluator_config_sha256",
                    "target_version",
                    "evaluator_version",
                )
            )
            or arm["evaluator_version"] != "product-v2"
            or arm["target_version"] != getattr(request, label).target_version
        ):
            raise ResultSnapshotIntegrityError("run components do not match frozen input")
        rows = arm["jobs"]
        if len(rows) != len(cases) or {row["case_id"] for row in rows} != set(by_case):
            raise ResultSnapshotIntegrityError("final outcome coverage differs from source dataset")
        for row in rows:
            identity = row["case_id"]
            if row["run_id"] != arm["run_id"] or row["job_id"] in seen_jobs:
                raise ResultSnapshotIntegrityError(
                    "job identity is duplicated or belongs to another run"
                )
            UUID(row["job_id"])
            seen_jobs.add(row["job_id"])
            if row["job_status"] in {"failed", "cancelled"}:
                if row["metrics"] is not None or row["accepted_attempt_id"] is not None:
                    raise ResultSnapshotIntegrityError(
                        "non-success outcome contains accepted metrics"
                    )
                failures.append(
                    CaseExecutionFailure(
                        arm=label,
                        case_id=identity,
                        error_code=row.get("error_code")
                        or (
                            "experiment_cancelled"
                            if row["job_status"] == "cancelled"
                            else "job_execution_failed"
                        ),
                        retryable=False,
                    )
                )
                continue
            if (
                row["job_status"] != "succeeded"
                or row["accepted_attempt_id"] is None
                or row["accepted_attempt_id"] in seen_attempts
                or row["result_id"] is None
                or row["result_id"] in seen_results
                or type(row["accepted_attempt_number"]) is not int
                or not 1
                <= row["accepted_attempt_number"]
                == row["attempt_count"]
                <= request.max_attempts
            ):
                raise ResultSnapshotIntegrityError("final result lacks a unique accepted attempt")
            UUID(row["accepted_attempt_id"])
            UUID(row["result_id"])
            seen_attempts.add(row["accepted_attempt_id"])
            seen_results.add(row["result_id"])
            if not isinstance(row["accepted_started_at"], str) or not isinstance(
                row["accepted_finished_at"], str
            ):
                raise ResultSnapshotIntegrityError("accepted attempt timestamps are missing")
            started = datetime.fromisoformat(row["accepted_started_at"])
            finished = datetime.fromisoformat(row["accepted_finished_at"])
            if started.tzinfo is None or finished.tzinfo is None or finished < started:
                raise ResultSnapshotIntegrityError("accepted attempt timestamps are invalid")
            metrics = row["metrics"]
            if (
                metrics["product_schema_version"] != "evalops.worker-product-observation/2.0"
                or metrics["product_task_type"] != request.task_type
            ):
                raise ResultSnapshotIntegrityError("worker observation schema or task mismatch")
            observation = ProviderResult.model_validate_json(
                json.dumps(metrics["product_observation"], allow_nan=False)
            )
            if product_observation_bytes(observation) > per_job_bytes:
                raise ResultSnapshotIntegrityError("accepted observation exceeds frozen budget")
            missing = product_input_requirements(by_case[identity], task_type=request.task_type)
            if observation.cost_usd is None:
                missing.append("MISSING_COST_MEASUREMENT")
            if request.task_type == "AGENT_TOOL_USE" and observation.missing_fields:
                missing.append("MISSING_AGENT_OBSERVATION")
            expected_scores = (
                {}
                if missing
                else score_product_case(by_case[identity], observation, evaluators=evaluators)
            )
            if (
                metrics["product_missing"] != missing
                or metrics["product_status"] != ("INSUFFICIENT_EVIDENCE" if missing else "OBSERVED")
                or canonical_request_hash(metrics["product_scores"])
                != canonical_request_hash(expected_scores)
            ):
                raise ResultSnapshotIntegrityError("stored worker scores do not reproduce")
            observations[label][identity] = observation
            events.append(
                {
                    "arm": label,
                    "case_id": identity,
                    "run_id": row["run_id"],
                    "job_id": row["job_id"],
                    "attempt_id": row["accepted_attempt_id"],
                    "attempt_number": row["accepted_attempt_number"],
                    "started_at_utc": row["accepted_started_at"],
                    "finished_at_utc": row["accepted_finished_at"],
                    "observation_status": "OBSERVED",
                }
            )
    result = aggregate_product_observations(
        context=ProductAggregationContext(
            experiment_id=request.experiment_id,
            execution_id=UUID(snapshot["experiment_id"]),
            scope=request.scope,
            task_type=request.task_type,
            dataset_sha256=request.source_dataset_sha256,
            evalops_sha=inputs["evalops_sha"],
            input_snapshot=None,
            source_identities={
                label: {
                    "repository": getattr(request, label).source_repository,
                    "sha": getattr(request, label).source_sha,
                    "provider_type": "http",
                }
                for label in ARM_LABELS
            },
            policy=request.policy,
            agent_comparison_policy=request.agent_comparison_policy,
            citation_precision_min=request.citation_precision_min,
            evaluator_names=names,
        ),
        cases=cases,
        observations=observations,
        execution_errors=failures,
        execution_events=events,
    )
    report: dict[str, Any] = {
        "schema_version": "evalops.durable-experiment-report/1.0",
        "aggregation_version": "evalops.product-aggregation/2.0",
        "result_snapshot_sha256": snapshot["content_sha256"],
        "result_snapshot": snapshot,
        "raw_dataset_sha256": request.source_dataset_sha256,
        "normalized_dataset_sha256": mapped.dataset.sha256,
        "result": result.model_dump(mode="json"),
        "formal_quality_claim_allowed": False,
        "production_ready": False,
    }
    report["content_sha256"] = canonical_request_hash(report)
    return report

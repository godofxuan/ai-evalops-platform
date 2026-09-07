from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.domain.enums import AttemptOutcome, JobStatus
from app.domain.evaluation import EvaluationCase, TargetResult
from app.evaluators.product import ProductAgentEvaluator, ProductQAEvaluator
from app.persistence.orm_models import CaseResult, EvaluationJob, JobAttempt
from app.product_experiments.result_snapshot import freeze_durable_job
from app.product_experiments.submission import prepare_durable_experiment
from app.runs.idempotency import canonical_request_hash
from tests.unit.product_experiments.test_submission import submission_inputs as submission_inputs


@pytest.fixture
async def durable_evidence(submission_inputs):
    pending = await prepare_durable_experiment(**submission_inputs)
    arms = {}
    now = datetime(2026, 9, 7, tzinfo=UTC)
    for label, arm in (("baseline", pending.baseline), ("candidate", pending.candidate)):
        run_id = uuid4()
        jobs = []
        for payload in arm.cases:
            case = EvaluationCase.from_payload(payload)
            evaluator = (
                ProductQAEvaluator()
                if arm.evaluator_type == "product_qa_v2"
                else ProductAgentEvaluator()
            )
            metrics = evaluator.evaluate(
                case,
                TargetResult(
                    answer="private answer",
                    citations=({"source_id": "gold"},),
                    sources=(),
                    trace={
                        "cost_usd": 0.01,
                        "tool_calls": [],
                        "tool_error": False,
                        "terminal_state": "completed",
                        "budget_exhausted": False,
                    },
                    token_usage=None,
                    latency_ms=10,
                ),
                attempt_number=2,
            ).metrics
            job_id, attempt_id = uuid4(), uuid4()
            job = EvaluationJob(
                id=job_id,
                run_id=run_id,
                case_id=case.case_id,
                status=JobStatus.SUCCEEDED,
                attempt_count=2,
                version=7,
            )
            result = CaseResult(
                id=uuid4(),
                job_id=job_id,
                run_id=run_id,
                case_id=case.case_id,
                accepted_attempt_id=attempt_id,
                metrics_json=metrics,
            )
            attempt = JobAttempt(
                id=attempt_id,
                job_id=job_id,
                attempt_number=2,
                outcome=AttemptOutcome.SUCCEEDED,
                started_at=now,
                finished_at=now,
            )
            jobs.append(freeze_durable_job(job, result, attempt))
        arms[label] = {
            "run_id": str(run_id),
            "run_version": 7,
            "run_status": "succeeded",
            "dataset_version_id": str(arm.dataset_version_id),
            "dataset_sha256": arm.dataset_hash,
            "target_config_sha256": arm.target_config_hash,
            "evaluator_config_sha256": arm.evaluator_config_hash,
            "target_version": arm.target_version,
            "evaluator_version": arm.evaluator_version,
            "jobs": jobs,
        }
    snapshot = {
        "schema_version": "evalops.durable-result-snapshot/1.0",
        "experiment_id": str(uuid4()),
        "tenant_id": str(pending.tenant_id),
        "request_sha256": pending.request_hash,
        "input_snapshot": pending.snapshot,
        "source_artifact_reference_id": str(uuid4()),
        "arms": arms,
        "formal_quality_claim_allowed": False,
        "production_ready": False,
    }
    snapshot["content_sha256"] = canonical_request_hash(snapshot)
    return snapshot, submission_inputs["dataset_payload"]


@pytest.mark.parametrize("submission_inputs", ["QA", "AGENT_TOOL_USE"], indirect=True)
async def test_durable_report_rebuilds_worker_metrics_without_target_calls(
    durable_evidence,
) -> None:
    from app.product_experiments.durable_report import build_durable_report

    snapshot, raw = durable_evidence
    report = build_durable_report(snapshot=snapshot, raw_dataset=raw)
    assert build_durable_report(snapshot=snapshot, raw_dataset=raw) == report
    assert report["schema_version"] == "evalops.durable-experiment-report/1.0"
    assert report["result_snapshot_sha256"] == snapshot["content_sha256"]
    result = report["result"]
    assert result["execution_id"] == snapshot["experiment_id"]
    assert result["status"] == "INSUFFICIENT_EVIDENCE"  # Two fixture cases are not 100 cases.
    assert result["case_count"] == 2
    assert len(result["case_comparisons"]) == 2
    assert result["case_comparisons"][0]["candidate_task_success"] == 1.0
    assert result["formal_quality_claim_allowed"] is False
    assert len(result["execution_events"]) == 4
    assert all(row["attempt_number"] == 2 for row in result["execution_events"])
    unsigned = dict(report)
    digest = unsigned.pop("content_sha256")
    assert canonical_request_hash(unsigned) == digest


@pytest.mark.parametrize(
    "change",
    [
        "scores",
        "dataset_version",
        "component",
        "coverage",
        "old_attempt",
        "duplicate_result",
        "unfinished",
        "observation_budget",
        "requested_version",
    ],
)
async def test_rehashed_tampering_cannot_gain_a_valid_durable_report(
    durable_evidence, change
) -> None:
    from app.product_experiments.durable_report import build_durable_report

    snapshot, raw = durable_evidence
    arm = snapshot["arms"]["candidate"]
    row = arm["jobs"][0]
    if change == "scores":
        row["metrics"]["product_scores"]["reference_answer"] = 0.0
    elif change == "dataset_version":
        arm["dataset_version_id"] = str(uuid4())
    elif change == "component":
        arm["target_config_sha256"] = "0" * 64
    elif change == "coverage":
        arm["jobs"].pop()
    elif change == "old_attempt":
        row["accepted_attempt_number"] = 1
    elif change == "duplicate_result":
        row["result_id"] = arm["jobs"][1]["result_id"]
    elif change == "unfinished":
        row["accepted_finished_at"] = None
    elif change == "requested_version":
        snapshot["input_snapshot"]["request"]["candidate"]["target_version"] = "different-version"
        snapshot["request_sha256"] = canonical_request_hash(snapshot["input_snapshot"]["request"])
    else:
        snapshot["input_snapshot"]["observation_budget"]["max_bytes_per_job"] = 1
    inputs = snapshot["input_snapshot"]
    inputs.pop("content_sha256")
    inputs["content_sha256"] = canonical_request_hash(inputs)
    snapshot.pop("content_sha256")
    snapshot["content_sha256"] = canonical_request_hash(snapshot)
    with pytest.raises(ValueError):
        build_durable_report(snapshot=snapshot, raw_dataset=raw)


async def test_one_failed_arm_case_cannot_be_dropped_to_create_quality_pass(
    durable_evidence,
) -> None:
    from app.product_experiments.durable_report import build_durable_report

    snapshot, raw = durable_evidence
    row = snapshot["arms"]["candidate"]["jobs"][0]
    row.update(
        job_status="failed",
        accepted_attempt_id=None,
        accepted_attempt_number=None,
        accepted_started_at=None,
        accepted_finished_at=None,
        result_id=None,
        metrics=None,
        error_code="target_timeout",
    )
    snapshot["arms"]["candidate"]["run_status"] = "partially_succeeded"
    snapshot.pop("content_sha256")
    snapshot["content_sha256"] = canonical_request_hash(snapshot)
    result = build_durable_report(snapshot=snapshot, raw_dataset=raw)["result"]
    assert result["status"] == "EXECUTION_FAILED" and result["case_count"] == 2
    assert result["case_comparisons"] == []
    assert result["execution_errors"][0]["error_code"] == "target_timeout"
    assert sum(len(rows) for rows in result["observations"].values()) == 3

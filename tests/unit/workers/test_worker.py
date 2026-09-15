import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

import pytest
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.core.telemetry import Telemetry
from app.domain.evaluation import (
    EvaluationCase,
    EvaluationResult,
    ExecutionContext,
    TargetResult,
    TokenUsage,
)
from app.jobs.claiming import ClaimedJob
from app.jobs.retry_policy import classify_failure
from app.observability.metrics import PlatformMetrics
from app.product_experiments.dataset_mapping import map_product_dataset
from app.targets.base import TargetHTTPError
from app.workers.worker import EvaluationWorker

RUN_ID = UUID("00000000-0000-0000-0000-000000000601")
JOB_ID = UUID("00000000-0000-0000-0000-000000000701")
TENANT_ID = UUID("00000000-0000-0000-0000-000000000201")
ATTEMPT_ID = UUID("00000000-0000-0000-0000-000000000801")


class SingleClaimer:
    def __init__(self, claim: ClaimedJob) -> None:
        self.claimed_job = claim

    async def claim(self, *, worker_id: str, limit: int = 1) -> tuple[ClaimedJob, ...]:
        assert worker_id == "worker-1"
        assert limit == 1
        return (self.claimed_job,)


class RecordingTarget:
    def __init__(self) -> None:
        self.case_id: str | None = None

    async def execute_case(
        self,
        case: EvaluationCase,
        context: ExecutionContext,
    ) -> TargetResult:
        self.case_id = case.case_id
        assert context.attempt_number == 1
        return TargetResult(
            answer="4",
            citations=(),
            sources=(),
            trace={},
            token_usage=TokenUsage(input_tokens=5, output_tokens=1),
            latency_ms=12,
        )


class RecordingEvaluator:
    def evaluate(
        self,
        case: EvaluationCase,
        target_result: TargetResult,
        *,
        attempt_number: int,
    ) -> EvaluationResult:
        assert case.case_id == "case-1"
        assert target_result.answer == "4"
        assert attempt_number == 1
        return EvaluationResult(metrics={"lexical_exact_match": True})


class RecordingCommitter:
    def __init__(self) -> None:
        self.committed = False

    async def commit_success(self, **kwargs: object) -> None:
        self.committed = True
        assert kwargs["lease_version"] == 2
        assert cast(TargetResult, kwargs["target_result"]).answer == "4"


class RecordingFailureCommitter:
    def __init__(self) -> None:
        self.failure: BaseException | None = None

    async def commit_failure(self, **kwargs: object) -> None:
        self.failure = cast(BaseException, kwargs["error"])


class PassThroughLeaseRunner:
    async def run(
        self,
        *,
        claim: ClaimedJob,
        context: ExecutionContext,
        operation: object,
    ) -> tuple[TargetResult, int]:
        del context
        return await cast(Any, operation), claim.version


class RenewingLeaseRunner(PassThroughLeaseRunner):
    async def run(
        self,
        *,
        claim: ClaimedJob,
        context: ExecutionContext,
        operation: object,
    ) -> tuple[TargetResult, int]:
        del context
        return await cast(Any, operation), claim.version + 3


@pytest.mark.parametrize("attempt", [1, 2])
@pytest.mark.parametrize("in_flight", [False, True])
async def test_expired_experiment_deadline_is_not_reset_by_retry(
    attempt: int, in_flight: bool
) -> None:
    claim = ClaimedJob(
        job_id=JOB_ID,
        run_id=RUN_ID,
        tenant_id=TENANT_ID,
        case_id="case-1",
        case_payload={"case_id": "case-1", "question": "q", "metadata": {}},
        attempt_id=ATTEMPT_ID,
        attempt_number=attempt,
        worker_id="worker-1",
        lease_expires_at=datetime.now(UTC) + timedelta(seconds=30),
        version=2,
        target_type="mock",
        target_config={"outcome": "http_500", "fixed_delay_ms": 500 if in_flight else 0},
        target_version="v1",
        evaluator_type="basic_answer",
        evaluator_config={},
        evaluator_version="builtin-v1",
        execution_deadline_at=datetime.now(UTC) + timedelta(seconds=0.1)
        if in_flight
        else datetime(2000, 1, 1, tzinfo=UTC),
    )
    success = RecordingCommitter()
    failure = RecordingFailureCommitter()
    worker = EvaluationWorker(
        claimer=SingleClaimer(claim),
        result_committer=success,
        failure_committer=failure,
        lease_runner=PassThroughLeaseRunner(),
    )
    assert await worker.process_one(worker_id="worker-1")
    assert not success.committed and failure.failure is not None
    classified = classify_failure(failure.failure)
    assert classified.error_code == "experiment_deadline_exceeded"
    assert classified.retryable is False


@pytest.mark.parametrize("attempt", [1, 2])
async def test_worker_does_not_retry_or_commit_an_over_budget_product_observation(
    attempt: int,
) -> None:
    raw = json.dumps(
        [
            {
                "case_id": str(index),
                "category": "qa",
                "prompt": "q",
                "reference_answer": "a",
                "expected_citation_ids": ["gold"],
            }
            for index in range(2)
        ]
    ).encode()
    mapped = map_product_dataset(raw, expected_sha256=hashlib.sha256(raw).hexdigest())
    claim = ClaimedJob(
        job_id=JOB_ID,
        run_id=RUN_ID,
        tenant_id=TENANT_ID,
        case_id="0",
        case_payload=mapped.dataset.cases[0].model_dump(),
        attempt_id=ATTEMPT_ID,
        attempt_number=attempt,
        worker_id="worker-1",
        lease_expires_at=datetime.now(UTC) + timedelta(seconds=30),
        version=2,
        target_type="mock",
        target_config={"answer": "a", "trace": {"cost_usd": 0.0}},
        target_version="v1",
        evaluator_type="product_qa_v2",
        evaluator_config={"max_observation_bytes_per_case": 1},
        evaluator_version="product-v2",
    )
    success, failure = RecordingCommitter(), RecordingFailureCommitter()
    worker = EvaluationWorker(
        claimer=SingleClaimer(claim),
        result_committer=success,
        failure_committer=failure,
        lease_runner=PassThroughLeaseRunner(),
    )
    assert await worker.process_one(worker_id="worker-1")
    assert not success.committed and failure.failure is not None
    classified = classify_failure(failure.failure)
    assert classified.error_code == "experiment_observation_budget_exceeded"
    assert classified.retryable is False


async def test_worker_executes_target_evaluator_and_result_commit_pipeline() -> None:
    claim = ClaimedJob(
        job_id=JOB_ID,
        run_id=RUN_ID,
        tenant_id=TENANT_ID,
        case_id="case-1",
        case_payload={
            "case_id": "case-1",
            "question": "What is 2 + 2?",
            "expected_answer": "4",
            "metadata": {},
        },
        attempt_id=ATTEMPT_ID,
        attempt_number=1,
        worker_id="worker-1",
        lease_expires_at=datetime.now(UTC) + timedelta(seconds=30),
        version=2,
        target_type="mock",
        target_config={},
        target_version="v1",
        evaluator_type="basic_answer",
        evaluator_config={},
        evaluator_version="v1",
    )
    target = RecordingTarget()
    evaluator = RecordingEvaluator()
    committer = RecordingCommitter()
    failure_committer = RecordingFailureCommitter()
    worker = EvaluationWorker(
        claimer=SingleClaimer(claim),
        target_factory=lambda _kind, _config: target,
        evaluator_factory=lambda _kind, _config: evaluator,
        result_committer=committer,
        failure_committer=failure_committer,
        lease_runner=PassThroughLeaseRunner(),
    )

    processed = await worker.process_one(worker_id="worker-1")

    assert processed is True
    assert target.case_id == "case-1"
    assert committer.committed is True
    assert failure_committer.failure is None


class FailingTarget(RecordingTarget):
    async def execute_case(
        self,
        case: EvaluationCase,
        context: ExecutionContext,
    ) -> TargetResult:
        del case, context
        raise TargetHTTPError(429)


async def test_worker_persists_target_failure_instead_of_losing_claim() -> None:
    claimed_job = ClaimedJob(
        job_id=JOB_ID,
        run_id=RUN_ID,
        tenant_id=TENANT_ID,
        case_id="case-1",
        case_payload={
            "case_id": "case-1",
            "question": "q",
            "expected_answer": "a",
            "metadata": {},
        },
        attempt_id=ATTEMPT_ID,
        attempt_number=1,
        worker_id="worker-1",
        lease_expires_at=datetime.now(UTC) + timedelta(seconds=30),
        version=2,
        target_type="mock",
        target_config={},
        target_version="v1",
        evaluator_type="execution",
        evaluator_config={},
        evaluator_version="v1",
    )
    result_committer = RecordingCommitter()
    failure_committer = RecordingFailureCommitter()
    metrics = PlatformMetrics()
    worker = EvaluationWorker(
        claimer=SingleClaimer(claimed_job),
        target_factory=lambda _kind, _config: FailingTarget(),
        evaluator_factory=lambda _kind, _config: RecordingEvaluator(),
        result_committer=result_committer,
        failure_committer=failure_committer,
        lease_runner=PassThroughLeaseRunner(),
        metrics=metrics,
    )

    assert await worker.process_one(worker_id="worker-1") is True
    assert isinstance(failure_committer.failure, TargetHTTPError)
    assert result_committer.committed is False
    assert (
        'db_operation_duration_seconds_count{operation="failure"} 1.0'
        in metrics.render().decode("utf-8")
    )


async def test_worker_commits_with_latest_heartbeat_lease_version() -> None:
    claimed_job = ClaimedJob(
        job_id=JOB_ID,
        run_id=RUN_ID,
        tenant_id=TENANT_ID,
        case_id="case-1",
        case_payload={"case_id": "case-1", "question": "q", "metadata": {}},
        attempt_id=ATTEMPT_ID,
        attempt_number=1,
        worker_id="worker-1",
        lease_expires_at=datetime.now(UTC) + timedelta(seconds=30),
        version=2,
        target_type="mock",
        target_config={},
        target_version="v1",
        evaluator_type="execution",
        evaluator_config={},
        evaluator_version="v1",
    )

    class LatestVersionCommitter:
        async def commit_success(self, **kwargs: object) -> None:
            assert kwargs["lease_version"] == 5

    worker = EvaluationWorker(
        claimer=SingleClaimer(claimed_job),
        target_factory=lambda _kind, _config: RecordingTarget(),
        evaluator_factory=lambda _kind, _config: RecordingEvaluator(),
        result_committer=LatestVersionCommitter(),
        failure_committer=RecordingFailureCommitter(),
        lease_runner=RenewingLeaseRunner(),
    )

    assert await worker.process_one(worker_id="worker-1") is True


async def test_worker_never_publishes_outside_the_state_transaction() -> None:
    claimed_job = ClaimedJob(
        job_id=JOB_ID,
        run_id=RUN_ID,
        tenant_id=TENANT_ID,
        case_id="case-1",
        case_payload={"case_id": "case-1", "question": "q", "metadata": {}},
        attempt_id=ATTEMPT_ID,
        attempt_number=1,
        worker_id="worker-1",
        lease_expires_at=datetime.now(UTC) + timedelta(seconds=30),
        version=2,
        target_type="mock",
        target_config={},
        target_version="v1",
        evaluator_type="execution",
        evaluator_config={},
        evaluator_version="v1",
    )

    committer = RecordingCommitter()
    worker = EvaluationWorker(
        claimer=SingleClaimer(claimed_job),
        target_factory=lambda _kind, _config: RecordingTarget(),
        evaluator_factory=lambda _kind, _config: RecordingEvaluator(),
        result_committer=committer,
        failure_committer=RecordingFailureCommitter(),
        lease_runner=PassThroughLeaseRunner(),
    )

    assert await worker.process_one(worker_id="worker-1") is True
    assert committer.committed is True


async def test_worker_emits_pipeline_spans_and_success_metrics() -> None:
    exporter = InMemorySpanExporter()
    telemetry = Telemetry(
        service_name="evalops-worker-test",
        span_processors=(SimpleSpanProcessor(exporter),),
    )
    with telemetry.start_as_current_span("run.create") as origin_span:
        origin_context = origin_span.get_span_context()
        origin_traceparent = telemetry.capture_traceparent()
    assert origin_traceparent is not None

    claimed_job = ClaimedJob(
        job_id=JOB_ID,
        run_id=RUN_ID,
        tenant_id=TENANT_ID,
        case_id="case-1",
        case_payload={"case_id": "case-1", "question": "q", "metadata": {}},
        attempt_id=ATTEMPT_ID,
        attempt_number=1,
        worker_id="worker-1",
        lease_expires_at=datetime.now(UTC) + timedelta(seconds=30),
        version=2,
        target_type="mock",
        target_config={},
        target_version="v1",
        evaluator_type="execution",
        evaluator_config={},
        evaluator_version="v1",
        origin_traceparent=origin_traceparent,
    )
    metrics = PlatformMetrics()

    worker = EvaluationWorker(
        claimer=SingleClaimer(claimed_job),
        target_factory=lambda _kind, _config: RecordingTarget(),
        evaluator_factory=lambda _kind, _config: RecordingEvaluator(),
        result_committer=RecordingCommitter(),
        failure_committer=RecordingFailureCommitter(),
        lease_runner=PassThroughLeaseRunner(),
        metrics=metrics,
        telemetry=telemetry,
    )

    assert await worker.process_one(worker_id="worker-1") is True

    spans = exporter.get_finished_spans()
    span_names = {span.name for span in spans}
    assert {
        "job.claim",
        "job.process",
        "target.call",
        "evaluator.evaluate",
        "result.persist",
    } <= span_names
    assert "progress.publish" not in span_names
    process_span = next(span for span in spans if span.name == "job.process")
    assert process_span.parent is None
    assert process_span.context.trace_id != origin_context.trace_id
    assert len(process_span.links) == 1
    assert process_span.links[0].context.trace_id == origin_context.trace_id
    assert process_span.links[0].context.span_id == origin_context.span_id
    assert process_span.attributes is not None
    assert process_span.attributes["attempt.number"] == 1
    rendered = metrics.render().decode("utf-8")
    assert "job_succeeded_total 1.0" in rendered
    assert "case_duration_count 1.0" in rendered
    assert 'db_operation_duration_seconds_count{operation="claim"} 1.0' in rendered
    assert 'db_operation_duration_seconds_count{operation="result"} 1.0' in rendered

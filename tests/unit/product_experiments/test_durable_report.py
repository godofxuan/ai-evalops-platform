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
from tests.unit.product_experiments.test_submission import (
    authenticated_submission_setup as authenticated_submission_setup,
)
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


@pytest.mark.parametrize("latencies", [(0, 0), (0, 1), (1, 0)])
async def test_submillisecond_http_measurements_do_not_break_report_serialization(
    durable_evidence, latencies
) -> None:
    from app.product_experiments.durable_report import build_durable_report
    from app.product_experiments.export_service import encode_report

    snapshot, raw = durable_evidence
    for arm, latency in zip(("baseline", "candidate"), latencies, strict=True):
        for row in snapshot["arms"][arm]["jobs"]:
            row["metrics"]["product_observation"]["latency_ms"] = float(latency)
    snapshot.pop("content_sha256")
    snapshot["content_sha256"] = canonical_request_hash(snapshot)
    report = build_durable_report(snapshot=snapshot, raw_dataset=raw)
    assert report["result"]["status"] == "INSUFFICIENT_EVIDENCE"
    assert encode_report(report)


@pytest.mark.parametrize("bad", ["answer", "terminal"])
async def test_legacy_bad_success_is_bounded_evidence_invalid_without_rewriting_snapshot(
    durable_evidence, bad
):
    import copy

    from app.product_experiments.durable_report import build_durable_report
    from app.product_experiments.result_snapshot import ResultSnapshotIntegrityError

    snapshot, raw = durable_evidence
    observation = snapshot["arms"]["candidate"]["jobs"][0]["metrics"]["product_observation"]
    if bad == "answer":
        observation["answer"] = "SECRET_SYNTHETIC" * 10000
    else:
        observation.update(terminal_state="failed", source_terminal_state="answer")
    snapshot.pop("content_sha256")
    snapshot["content_sha256"] = canonical_request_hash(snapshot)
    original = copy.deepcopy(snapshot)
    with pytest.raises(ResultSnapshotIntegrityError, match="evidence_invalid_for_current_code"):
        build_durable_report(snapshot=snapshot, raw_dataset=raw)
    assert snapshot == original


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


@pytest.mark.parametrize("mode", ["valid", "too_deep", "store_retry"])
async def test_report_export_publishes_once_and_replays_without_source_or_result_reread(
    durable_evidence, tmp_path, mode, authenticated_submission_setup
) -> None:
    import hashlib
    from uuid import UUID

    from app.artifacts.service import ArtifactAccessService, ArtifactReferenceLocation
    from app.artifacts.storage import LocalArtifactStore
    from app.auth.principals import Principal
    from app.product_experiments.export_service import ProductReportExporter
    from app.product_experiments.report_persistence import PublishedProductReport

    snapshot, raw = durable_evidence
    if mode == "too_deep":
        nested = {}
        for _ in range(70):
            nested = {"nested": nested}
        snapshot["arms"]["candidate"]["jobs"][0]["metrics"]["product_observation"]["citations"][0][
            "extra"
        ] = nested
        snapshot.pop("content_sha256")
        snapshot["content_sha256"] = canonical_request_hash(snapshot)
    tenant_id = UUID(snapshot["tenant_id"])
    experiment_id = UUID(snapshot["experiment_id"])
    source_id = UUID(snapshot["source_artifact_reference_id"])
    baseline_id = UUID(snapshot["arms"]["baseline"]["run_id"])
    store = LocalArtifactStore(tmp_path / "objects")
    source = await store.put_bytes(raw)
    links = {(tenant_id, source_id, None): source.sha256}

    class Gateway:
        async def get_location(self, *, tenant_id, reference_id, run_id):
            digest = links.get((tenant_id, reference_id, run_id))
            return None if digest is None else ArtifactReferenceLocation(reference_id, digest)

    class ResultDatabase:
        calls = 0

        async def read(self, **kwargs):
            self.calls += 1
            assert self.calls <= (2 if mode == "store_retry" else 1), (
                "published report replay must not reread live results"
            )
            return snapshot

    class PublicationDatabase:
        receipt = None

        async def get(self, **kwargs):
            return self.receipt

        async def publish(self, *, principal, snapshot, stored):
            assert self.receipt is None
            reference_id = uuid4()
            links[(tenant_id, reference_id, baseline_id)] = stored.sha256
            self.receipt = PublishedProductReport(
                experiment_id,
                tenant_id,
                baseline_id,
                reference_id,
                stored.sha256,
                snapshot["content_sha256"],
            )
            return self.receipt

    class TransientStoreBoundary:
        failed = False

        async def put_bytes(self, content):
            stored = await store.put_bytes(content)
            if mode == "store_retry" and not self.failed:
                self.failed = True
                # The blob may exist even though the remote acknowledgement was lost.
                raise OSError("synthetic_blob_acknowledgement_lost")
            return stored

        async def get_bytes(self, sha256):
            return await store.get_bytes(sha256)

        async def check_ready(self):
            return await store.check_ready()

    database = PublicationDatabase()
    exporter = ProductReportExporter(
        reader=ResultDatabase(),
        repository=database,
        artifact_access=ArtifactAccessService(gateway=Gateway(), store=store),
        artifact_store=TransientStoreBoundary(),
    )
    principal = Principal(tenant_id=tenant_id, api_key_id=uuid4(), key_prefix="test")
    if mode == "too_deep":
        with pytest.raises(ValueError):
            await exporter.export(principal=principal, experiment_id=experiment_id)
        assert database.receipt is None, (
            "unreadable report must never become the immutable publication"
        )
        return
    if mode == "store_retry":
        with pytest.raises(OSError, match="synthetic_blob_acknowledgement_lost"):
            await exporter.export(principal=principal, experiment_id=experiment_id)
        assert database.receipt is None, "lost blob acknowledgement must not publish a success"
    first = await exporter.export(principal=principal, experiment_id=experiment_id)
    links.pop((tenant_id, source_id, None))
    second = await exporter.export(principal=principal, experiment_id=experiment_id)
    assert second == first
    assert hashlib.sha256(first.payload).hexdigest() == first.receipt.content_sha256
    assert first.report["result"]["status"] == "INSUFFICIENT_EVIDENCE"
    from httpx import ASGITransport, AsyncClient

    application = authenticated_submission_setup["application"]
    application.state.product_experiment_exporter = exporter
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        url = f"/api/v1/experiments/{experiment_id}/export"
        headers = authenticated_submission_setup["headers"]
        public = await client.post(url, headers=headers)
        assert public.status_code == 200
        assert public.json()["schema_version"] == "evalops.public-durable-report/1.0"
        assert "private answer" not in public.text
        assert "result_snapshot" not in public.json()
        private = await client.post(url + "?include_private=true", headers=headers)
        assert private.status_code == 200 and private.content == first.payload
        assert private.headers["cache-control"] == "private, no-store"

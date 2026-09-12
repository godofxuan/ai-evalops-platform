import asyncio
import copy
import json
import subprocess
import sys
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest

from app.product_experiments.client import ProductAPIClient, ProductAPIError
from app.product_experiments.durable_report import build_durable_report
from app.product_experiments.export_service import encode_report
from app.product_experiments.reliability import ReliabilityPlan
from app.product_experiments.reliability_client import (
    _lock,
    collect_reliability_ledger,
    create_reliability_ledger,
    read_bounded,
    report_reliability_ledger,
    submit_reliability_ledger,
    verify_reliability_ledger,
)
from app.runs.idempotency import canonical_request_hash
from tests.unit.product_experiments.test_durable_report import durable_evidence as durable_evidence
from tests.unit.product_experiments.test_submission import submission_inputs as submission_inputs


@pytest.fixture
async def panel_evidence(durable_evidence, submission_inputs):
    """Synthetic accepted worker observations, scored and rebuilt by actual product code."""
    original, raw = durable_evidence
    plan = ReliabilityPlan(
        panel_id=uuid4(),
        tenant_id=UUID(original["tenant_id"]),
        trial_count=2,
        request=submission_inputs["request"],
        evalops_sha=submission_inputs["evalops_sha"],
        environment_sha256="e" * 64,
        sampling_kind="SYNTHETIC",
    )
    payloads, accepted = {}, {}
    for trial in range(1, 3):
        snapshot = copy.deepcopy(original)
        snapshot["experiment_id"] = str(uuid4())
        snapshot["input_snapshot"]["request"] = plan.trial_request(trial).model_dump(mode="json")
        snapshot["input_snapshot"].pop("content_sha256")
        snapshot["input_snapshot"]["content_sha256"] = canonical_request_hash(
            snapshot["input_snapshot"]
        )
        snapshot["request_sha256"] = canonical_request_hash(snapshot["input_snapshot"]["request"])
        for arm in snapshot["arms"].values():
            arm["run_id"] = str(uuid4())
            for job in arm["jobs"]:
                job["run_id"] = arm["run_id"]
                for field in ("job_id", "result_id", "accepted_attempt_id"):
                    job[field] = str(uuid4())
        snapshot.pop("content_sha256")
        snapshot["content_sha256"] = canonical_request_hash(snapshot)
        payloads[trial] = encode_report(build_durable_report(snapshot=snapshot, raw_dataset=raw))
        accepted[trial] = {
            "id": snapshot["experiment_id"],
            "baseline_run_id": snapshot["arms"]["baseline"]["run_id"],
            "candidate_run_id": snapshot["arms"]["candidate"]["run_id"],
            "status_url": f"/api/v1/experiments/{snapshot['experiment_id']}",
        }
    return plan, raw, payloads, accepted


class TransportHarness:
    """HTTP boundary stub only, not a PostgreSQL/server acceptance claim."""

    def __init__(self, evidence):
        self.plan, self.raw, self.payloads, self.accepted = evidence
        self.states = {1: "READY_FOR_ASSESSMENT", 2: "READY_FOR_ASSESSMENT"}
        self.requests = []
        self.fail_once = False
        self.submitted = set()
        self.swap_export = False

    def __call__(self, request):
        assert request.headers["authorization"] == "Bearer synthetic-key"
        self.requests.append((request.method, str(request.url)))
        if request.method == "POST" and request.url.path == "/api/v1/experiments":
            body = json.loads(request.content)
            trial = next(
                t
                for t in (1, 2)
                if request.headers["idempotency-key"] == self.plan.idempotency_key(t)
            )
            assert body["request"] == self.plan.trial_request(trial).model_dump(mode="json")
            self.submitted.add(trial)
            if self.fail_once and trial == 2:
                self.fail_once = False
                raise httpx.ConnectError("SYNTHETIC_SECRET_NOT_TO_PRINT")
            return httpx.Response(202, json=self.accepted[trial])
        trial = next(t for t in (1, 2) if self.accepted[t]["id"] in request.url.path)
        if request.method == "POST":
            assert request.url.params["include_private"] == "true"
            return httpx.Response(
                200, content=self.payloads[3 - trial if self.swap_export else trial]
            )
        run = {
            "dataset_version_id": str(self.plan.request.dataset_version_id),
            "status": "succeeded",
            "total_jobs": 2,
            "succeeded_jobs": 2,
            "failed_jobs": 0,
            "cancelled_jobs": 0,
            "created_at": "2026-09-07T00:00:00Z",
            "started_at": "2026-09-07T00:00:00Z",
            "finished_at": "2026-09-07T00:00:01Z",
        }
        receipt = self.accepted[trial]
        return httpx.Response(
            200,
            json={
                "id": receipt["id"],
                "state": self.states[trial],
                "cancel_requested": False,
                "baseline": {**run, "id": receipt["baseline_run_id"]},
                "candidate": {**run, "id": receipt["candidate_run_id"]},
            },
        )


async def test_submit_recovers_lost_response_without_new_trial(panel_evidence, tmp_path):
    plan, raw, _, _ = panel_evidence
    ledger = tmp_path / "private-ledger"
    create_reliability_ledger(ledger, plan, raw)
    harness = TransportHarness(panel_evidence)
    harness.fail_once = True
    async with httpx.AsyncClient(transport=httpx.MockTransport(harness)) as http:
        client = ProductAPIClient("http://127.0.0.1", "synthetic-key", http=http)
        with pytest.raises(ProductAPIError, match="api_transport_error"):
            await submit_reliability_ledger(ledger, client)
        first_receipt = (ledger / "receipt-01" / "receipt.json").read_bytes()
        assert not (ledger / "receipt-02").exists()
        result = await submit_reliability_ledger(ledger, client)
        assert result["submitted_trials"] == 2
        assert harness.submitted == {1, 2}
        assert len(harness.requests) == 4
        assert (ledger / "receipt-01" / "receipt.json").read_bytes() == first_receipt


async def test_collect_report_verify_missing_then_complete_private_recompute(
    panel_evidence, tmp_path
):
    plan, raw, _, _ = panel_evidence
    ledger = tmp_path / "ledger"
    create_reliability_ledger(ledger, plan, raw)
    harness = TransportHarness(panel_evidence)
    harness.states[2] = "RUNNING"
    async with httpx.AsyncClient(transport=httpx.MockTransport(harness)) as http:
        client = ProductAPIClient("http://127.0.0.1", "synthetic-key", http=http)
        await submit_reliability_ledger(ledger, client)
        first = await collect_reliability_ledger(ledger, client)
        assert first["collected_trials"] == 1
        assert first["states"]["2"] == "RUNNING"
        report_reliability_ledger(ledger, tmp_path / "partial")
        partial = json.loads((tmp_path / "partial" / "report.json").read_bytes())
        assert partial["status"] == "INSUFFICIENT_EVIDENCE"
        verify_reliability_ledger(ledger, tmp_path / "partial")
        harness.states[2] = "READY_FOR_ASSESSMENT"
        assert (await collect_reliability_ledger(ledger, client))["collected_trials"] == 2
        with pytest.raises(ValueError):
            verify_reliability_ledger(ledger, tmp_path / "partial")
        previous_requests = len(harness.requests)
        await collect_reliability_ledger(ledger, client)
        assert len(harness.requests) == previous_requests  # Already verified bundles are offline.
    report_reliability_ledger(ledger, tmp_path / "complete")
    result = verify_reliability_ledger(ledger, tmp_path / "complete")
    assert result["verification_scope"] == "PRIVATE_RECOMPUTED_PANEL"
    assert result["status"] == "COMPLETE_DESCRIPTIVE_PANEL"
    assert result["collected_trials"] == result["expected_trials"] == 2
    assert result["formal_quality_claim_allowed"] is False
    assert result["server_provenance_verified"] is False
    (tmp_path / "complete" / "report.html").write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="panel_html_mismatch"):
        verify_reliability_ledger(ledger, tmp_path / "complete")


async def test_wrong_export_identity_never_publishes_bundle(panel_evidence, tmp_path):
    plan, raw, _, _ = panel_evidence
    ledger = tmp_path / "ledger"
    create_reliability_ledger(ledger, plan, raw)
    harness = TransportHarness(panel_evidence)
    harness.swap_export = True
    async with httpx.AsyncClient(transport=httpx.MockTransport(harness)) as http:
        client = ProductAPIClient("http://127.0.0.1", "synthetic-key", http=http)
        await submit_reliability_ledger(ledger, client)
        with pytest.raises(ProductAPIError, match="api_export_invalid"):
            await collect_reliability_ledger(ledger, client)
    assert not (ledger / "trial-01").exists()


async def test_changed_replay_receipt_is_rejected_and_preserved(panel_evidence, tmp_path):
    plan, raw, _, _ = panel_evidence
    ledger = tmp_path / "ledger"
    create_reliability_ledger(ledger, plan, raw)
    harness = TransportHarness(panel_evidence)
    async with httpx.AsyncClient(transport=httpx.MockTransport(harness)) as http:
        client = ProductAPIClient("http://127.0.0.1", "synthetic-key", http=http)
        await submit_reliability_ledger(ledger, client)
        previous = (ledger / "receipt-01" / "receipt.json").read_bytes()
        harness.accepted[1]["baseline_run_id"] = str(uuid4())
        with pytest.raises(ValueError, match="ledger_replay_identity_mismatch"):
            await submit_reliability_ledger(ledger, client)
        assert (ledger / "receipt-01" / "receipt.json").read_bytes() == previous


@pytest.mark.parametrize("name", ["trial-00", "trial-03", "receipt-01-extra", "unknown"])
async def test_extra_entries_fail_closed(panel_evidence, tmp_path, name):
    plan, raw, _, _ = panel_evidence
    ledger = tmp_path / "ledger"
    create_reliability_ledger(ledger, plan, raw)
    (ledger / name).mkdir()
    with pytest.raises(ValueError, match="ledger_file_set_mismatch"):
        report_reliability_ledger(ledger, tmp_path / "report")


async def test_plan_validation_atomic_no_overwrite_and_live_lock(panel_evidence, tmp_path):
    plan, raw, _, _ = panel_evidence
    ledger = tmp_path / "ledger"
    with pytest.raises(ValueError):
        create_reliability_ledger(ledger, plan, raw + b" ")
    assert not ledger.exists()
    with _lock(ledger), pytest.raises(OSError):
        create_reliability_ledger(ledger, plan, raw)
    create_reliability_ledger(ledger, plan, raw)
    with pytest.raises(ValueError, match="output_already_exists"):
        create_reliability_ledger(ledger, plan, raw)
    assert (ledger / "dataset.json").read_bytes() == raw
    report_reliability_ledger(ledger, tmp_path / "report")
    with pytest.raises(ValueError, match="output_already_exists"):
        report_reliability_ledger(ledger, tmp_path / "report")


async def test_killed_process_releases_ledger_lock(tmp_path):
    directory = tmp_path / "ledger"
    code = (
        "import sys,time; from pathlib import Path; "
        "from app.product_experiments.reliability_client import _lock; "
        "guard=_lock(Path(sys.argv[1])); guard.__enter__(); "
        "print('LOCKED',flush=True); time.sleep(60)"
    )
    process = await asyncio.to_thread(
        subprocess.Popen,
        [sys.executable, "-c", code, str(directory)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        assert (
            await asyncio.wait_for(asyncio.to_thread(process.stdout.readline), 15)
        ).strip() == b"LOCKED"
        with pytest.raises(OSError), _lock(directory):
            pass
        process.kill()
        await asyncio.to_thread(process.wait, 10)
        with _lock(directory):
            pass  # Same path immediately usable, no stale-lock deletion.
    finally:
        if process.poll() is None:
            process.kill()
        await asyncio.to_thread(process.wait, 10)
        process.stdout.close()
        process.stderr.close()


async def test_killed_receipt_publisher_leaves_recoverable_ledger(panel_evidence, tmp_path):
    plan, raw, _, _ = panel_evidence
    ledger = tmp_path / "ledger"
    create_reliability_ledger(ledger, plan, raw)
    code = """
import sys,time
from pathlib import Path
from app.product_experiments.reliability_client import _publish
ledger = Path(sys.argv[1])
rename = Path.rename
def stopped(self, target):
    if Path(target).name == 'receipt-01':
        print('STAGED', flush=True)
        time.sleep(60)
    return rename(self, target)
Path.rename = stopped
_publish(ledger / 'receipt-01', {'receipt.json': b'{}'}, stage_parent=ledger.parent)
"""
    process = await asyncio.to_thread(
        subprocess.Popen,
        [sys.executable, "-c", code, str(ledger)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        assert (
            await asyncio.wait_for(asyncio.to_thread(process.stdout.readline), 15)
        ).strip() == b"STAGED"
        process.kill()
        await asyncio.to_thread(process.wait, 10)
    finally:
        if process.poll() is None:
            process.kill()
        await asyncio.to_thread(process.wait, 10)
        process.stdout.close()
        process.stderr.close()
    assert not (ledger / "receipt-01").exists()
    assert {item.name for item in ledger.iterdir()} == {"plan.json", "dataset.json"}
    report_reliability_ledger(ledger, tmp_path / "missing-report")
    harness = TransportHarness(panel_evidence)
    async with httpx.AsyncClient(transport=httpx.MockTransport(harness)) as http:
        client = ProductAPIClient("http://127.0.0.1", "synthetic-key", http=http)
        result = await submit_reliability_ledger(ledger, client)
        assert result["submitted_trials"] == 2


def test_bounded_read_and_ancestor_junction_rejection(tmp_path, monkeypatch):
    source = tmp_path / "source.json"
    source.write_bytes(b"12345")
    with pytest.raises(ValueError, match="ledger_file_limit"):
        read_bounded(source, 4)
    monkeypatch.setattr(Path, "is_junction", lambda path: path == tmp_path)
    with pytest.raises(ValueError, match="ledger_link_not_allowed"):
        read_bounded(source, 10)


@pytest.mark.parametrize("tamper", ["duplicate", "run_identity", "plan_hash"])
async def test_receipt_tampering_cannot_rebind_private_bundle(panel_evidence, tmp_path, tamper):
    plan, raw, _, _ = panel_evidence
    ledger = tmp_path / "ledger"
    create_reliability_ledger(ledger, plan, raw)
    harness = TransportHarness(panel_evidence)
    async with httpx.AsyncClient(transport=httpx.MockTransport(harness)) as http:
        client = ProductAPIClient("http://127.0.0.1", "synthetic-key", http=http)
        await submit_reliability_ledger(ledger, client)
        await collect_reliability_ledger(ledger, client)
    path = ledger / "receipt-02" / "receipt.json"
    receipt = json.loads(path.read_bytes())
    if tamper == "duplicate":
        receipt["accepted"]["baseline_run_id"] = harness.accepted[1]["baseline_run_id"]
    elif tamper == "run_identity":
        receipt["accepted"]["candidate_run_id"] = str(uuid4())
    else:
        receipt["plan_sha256"] = "0" * 64
    path.write_bytes(encode_report(receipt))
    with pytest.raises(ValueError):
        report_reliability_ledger(ledger, tmp_path / "report")
    assert not (tmp_path / "report").exists()

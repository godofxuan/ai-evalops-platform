import json
import os
import subprocess
import sys

from tests.unit.product_experiments.test_durable_report import durable_evidence as durable_evidence
from tests.unit.product_experiments.test_reliability_client import panel_evidence as panel_evidence
from tests.unit.product_experiments.test_submission import submission_inputs as submission_inputs


def run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "scripts.product_reliability", *map(str, args)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env={**os.environ, "EVALOPS_API_KEY": ""},
    )


async def test_offline_cli_plan_missing_report_verify_and_unique_panel(panel_evidence, tmp_path):
    plan, raw, _, _ = panel_evidence
    request, dataset = tmp_path / "request.json", tmp_path / "dataset.json"
    request.write_text(plan.request.model_dump_json(), encoding="utf-8")
    dataset.write_bytes(raw)
    arguments = (
        "--request",
        request,
        "--dataset",
        dataset,
        "--tenant-id",
        plan.tenant_id,
        "--trials",
        2,
        "--evalops-sha",
        plan.evalops_sha,
        "--environment-sha256",
        plan.environment_sha256,
        "--sampling-kind",
        "SYNTHETIC",
    )
    first = run_cli("plan", *arguments, "--ledger", tmp_path / "ledger")
    assert first.returncode == 0, first.stderr
    assert "private answer" not in first.stdout + first.stderr
    second = run_cli("plan", *arguments, "--ledger", tmp_path / "another-ledger")
    assert second.returncode == 0, second.stderr
    assert json.loads(first.stdout)["plan_sha256"] != json.loads(second.stdout)["plan_sha256"]
    created = run_cli(
        "report", "--ledger", tmp_path / "ledger", "--output-dir", tmp_path / "report"
    )
    assert created.returncode == 0, created.stderr
    verified = run_cli(
        "verify", "--ledger", tmp_path / "ledger", "--output-dir", tmp_path / "report"
    )
    assert verified.returncode == 0, verified.stderr
    summary = json.loads(verified.stdout)
    assert summary["verification_scope"] == "PRIVATE_RECOMPUTED_PANEL"
    assert summary["status"] == "INSUFFICIENT_EVIDENCE"
    assert summary["collected_trials"] == 0
    assert summary["expected_trials"] == 2
    assert summary["formal_quality_claim_allowed"] is False
    assert summary["server_provenance_verified"] is False
    report = json.loads((tmp_path / "report" / "report.json").read_bytes())
    assert report["status"] == "INSUFFICIENT_EVIDENCE"
    assert "private answer" not in verified.stdout + verified.stderr


def test_cli_missing_key_and_malformed_private_data_are_redacted(tmp_path):
    no_key = run_cli("--api-url", "http://127.0.0.1:1", "submit", "--ledger", tmp_path / "ledger")
    assert no_key.returncode == 2
    assert no_key.stderr.strip() == "invalid_reliability_input"
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    (ledger / "plan.json").write_text('{"secret":"SENSITIVE-CANARY"}', encoding="utf-8")
    malformed = run_cli("report", "--ledger", ledger, "--output-dir", tmp_path / "report")
    assert malformed.returncode == 2
    assert "SENSITIVE-CANARY" not in malformed.stdout + malformed.stderr
    assert malformed.stderr.strip() == "invalid_reliability_input"

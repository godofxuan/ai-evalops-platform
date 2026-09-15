import asyncio
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


async def cli(*args: str) -> subprocess.CompletedProcess[str]:
    return await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-m", "scripts.evaluation_workflow", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )


async def test_demo_private_verify_and_full_set_regression_are_runnable(tmp_path: Path):
    output = tmp_path / "demo"
    completed = await cli(
        "demo",
        "--task",
        "agent",
        "--output-dir",
        str(output),
        "--include-private",
        "--evalops-sha",
        "e" * 40,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert json.loads(completed.stdout)["source_scope"] == "DEMO_FIXTURES"
    verified = await cli("verify", "--bundle", str(output))
    assert verified.returncode == 0, verified.stderr
    assert json.loads(verified.stdout)["diagnostics"] == "RECOMPUTED"
    packet = json.loads((output / "review-packet.json").read_bytes())
    assert len(packet["items"]) == 240
    assert not any("arm" in item or "score" in item for item in packet["items"])
    regression = tmp_path / "regression"
    exported = await cli(
        "regressions", "--bundle", str(output), "--output-dir", str(regression), "--include-private"
    )
    assert exported.returncode == 0, exported.stderr
    assert (regression / "cases.json").read_bytes() == (output / "source/dataset.json").read_bytes()
    replay = await cli(
        "run",
        "--spec",
        str(regression / "experiment.json"),
        "--output-dir",
        str(tmp_path / "replay"),
        "--evalops-sha",
        "e" * 40,
    )
    assert replay.returncode == 0, replay.stdout + replay.stderr
    calibration = tmp_path / "calibration"
    calibrated = await cli(
        "calibrate",
        "--bundle",
        str(output),
        "--reviews",
        str(output / "reviews-template.json"),
        "--output-dir",
        str(calibration),
        "--include-private",
    )
    assert calibrated.returncode == 0, calibrated.stderr
    report = json.loads(calibrated.stdout)
    assert report["paired_labels"] == 0 and report["null_reviews"] == 240
    assert report["human_verification"] == "NOT_VERIFIED"
    checked = await cli("verify", "--bundle", str(calibration))
    assert checked.returncode == 0, checked.stderr
    assert json.loads(checked.stdout)["scope"] == "DESCRIPTIVE_CALIBRATION_ONLY"


async def test_default_demo_export_does_not_disclose_cases_or_review_inputs(tmp_path: Path):
    output = tmp_path / "public"
    completed = await cli("demo", "--output-dir", str(output), "--evalops-sha", "e" * 40)
    assert completed.returncode == 0, completed.stderr
    assert {p.name for p in output.iterdir()} == {"manifest.json", "result.json", "report.html"}
    report = json.loads((output / "result.json").read_bytes())
    assert "observations" not in report and "case_comparisons" not in report


async def test_existing_output_is_rejected_before_invalid_spec_or_execution(tmp_path: Path):
    output = tmp_path / "existing"
    output.mkdir()
    completed = await cli(
        "run",
        "--spec",
        str(tmp_path / "missing.json"),
        "--output-dir",
        str(output),
        "--evalops-sha",
        "e" * 40,
    )
    assert completed.returncode == 2
    assert not list(output.iterdir())
    assert "Traceback" not in completed.stderr


async def test_diagnostic_size_failure_keeps_accepted_source_without_rerunning(tmp_path: Path):
    root = ROOT
    original = root / "benchmarks/product_demo_v1"
    cases = json.loads((original / "cases.json").read_bytes())[:64]
    for case in cases:
        case["prompt"] = "p" * 5000
        case["reference_answer"] = "r" * 10000
        for profile in case["metadata"]["fixture_profiles"].values():
            profile["answer"] = "a" * 60000
    raw = json.dumps(cases).encode()
    (tmp_path / "cases.json").write_bytes(raw)
    spec = json.loads((original / "experiment.json").read_bytes())
    spec["dataset"] = {"path": "cases.json", "sha256": hashlib.sha256(raw).hexdigest()}
    spec["policy_path"] = str(root / "benchmarks/formal_agent_quality_v1/policy.json")
    (tmp_path / "experiment.json").write_text(json.dumps(spec), encoding="utf-8")
    output = tmp_path / "oversized"
    completed = await cli(
        "run",
        "--spec",
        str(tmp_path / "experiment.json"),
        "--output-dir",
        str(output),
        "--include-private",
        "--evalops-sha",
        "e" * 40,
    )
    assert completed.returncode == 3, completed.stdout + completed.stderr
    assert json.loads(completed.stdout)["status"] == "EXECUTED_ANALYSIS_BLOCKED"
    from app.product_experiments.learning_workflow import load_evidence

    evidence = load_evidence(output / "source")
    assert len(evidence.result.observations["candidate"]) == 64
    assert evidence.raw_dataset == raw


@pytest.mark.parametrize("task", ["qa", "agent"])
async def test_initialized_configuration_is_self_contained_and_never_overwritten(
    tmp_path: Path,
    task: str,
):
    output = tmp_path / task
    completed = await cli("init", "--task", task, "--output-dir", str(output))
    assert completed.returncode == 0, completed.stderr
    original = (output / "cases.json").read_bytes()
    repeated = await cli("init", "--task", task, "--output-dir", str(output))
    assert repeated.returncode == 2
    assert (output / "cases.json").read_bytes() == original
    spec = json.loads((output / "experiment.json").read_bytes())
    assert spec["dataset"]["path"] == "cases.json" and spec["policy_path"] == "policy.json"

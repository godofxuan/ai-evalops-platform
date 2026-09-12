from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.public_benchmarks.local_pilot import encoded, execute_plan, read_json, write_plan
from app.public_benchmarks.pilot_report import build_report, verify_report, write_report


def make_rag_run(tmp_path: Path) -> Path:
    models = ("qwen2.5:3b", "qwen3:8b")
    rows = []
    for model in models:
        for index in range(4):
            case_id = f"case-{index}"
            domain = "hotpotqa" if index < 2 else "finqa"
            rows.append(
                {
                    "benchmark": "ragbench",
                    "case_id": case_id,
                    "category": domain,
                    "model": model,
                    "model_digest": "a" * 64,
                    "context_byte_budget": 1 if index == 3 else 6000,
                    "request": {
                        "model": model,
                        "stream": False,
                        "messages": [{"role": "user", "content": case_id}],
                        "options": {"num_ctx": 8192, "num_predict": 512},
                    },
                    "reference": {
                        "case_id": case_id,
                        "domain": domain,
                        "adherence_score": index % 2 == 0,
                        "published_predictions": {
                            "gpt3_adherence": 1.0,
                            "ragas_faithfulness": None,
                            "trulens_groundedness": 0.0,
                        },
                    },
                }
            )
    plan = write_plan(
        tmp_path / "plan", rows=rows, metadata={"evidence_kind": "TEST_FIXTURE_NOT_MODEL_BENCHMARK"}
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "test"})
        if request.url.path == "/api/tags":
            return httpx.Response(
                200, json={"models": [{"name": model, "digest": "a" * 64} for model in models]}
            )
        payload = json.loads(request.content)
        index = int(payload["messages"][0]["content"].split("-")[1])
        values: dict[str, Any] = {
            "qwen2.5:3b": [True, False, None],
            "qwen3:8b": [False, True, True],
        }
        prediction = values[payload["model"]][index]
        content = json.dumps({"supported": prediction, "reason": "test"})
        return httpx.Response(
            200,
            json={
                "model": payload["model"],
                "done": True,
                "done_reason": "stop",
                "message": {"content": content},
                "load_duration": 1_000_000,
                "total_duration": 4_000_000,
                "prompt_eval_count": 10,
                "eval_count": 5,
            },
        )

    run = tmp_path / "run"
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        execute_plan(plan, run, client=client)
    return run


def test_actual_execution_ledger_reporting_keeps_failed_and_context_blocked_denominators(
    tmp_path: Path,
) -> None:
    run = make_rag_run(tmp_path)
    report = build_report(run)
    first = report["models"]["qwen2.5:3b"]
    second = report["models"]["qwen3:8b"]
    assert first["planned"] == second["planned"] == 4
    assert first["correct_full_denominator"] == 2
    assert first["accuracy_full_denominator"] == 0.5
    assert first["calibration"]["paired_count"] == 2
    assert second["correct_full_denominator"] == 1
    assert first["statuses"]["CONTEXT_BLOCKED"] == 1
    assert first["timing"]["ollama_reported_load_ms"]["p95"] == 1.0
    assert report["baselines"]["always_supported"]["accuracy"] == 0.5
    assert (
        report["published_predictions"]["groups"]["all"]["ragas_faithfulness"]["paired_count"] == 0
    )
    assert len(report["per_case"]) == 8
    assert report == build_report(run)


def test_bfcl_report_separates_official_irrelevance_pass_from_parse_failure(tmp_path: Path) -> None:
    source_root = Path(__file__).resolve().parents[3] / "artifacts/public-benchmark-20260912/bfcl"
    if not (source_root / "cases.json").exists():
        pytest.skip("Requires the pinned public BFCL source, not a mocked checker")
    case = next(
        item
        for item in json.loads((source_root / "cases.json").read_bytes())
        if item["category"] == "irrelevance"
    )
    row = {
        "benchmark": "bfcl",
        "case_id": case["id"],
        "category": "irrelevance",
        "model": "qwen2.5:3b",
        "model_digest": "a" * 64,
        "context_byte_budget": 6000,
        "reference": case,
        "request": {
            "model": "qwen2.5:3b",
            "stream": False,
            "messages": [{"role": "user", "content": "A public irrelevant question"}],
            "options": {"num_ctx": 8192, "num_predict": 512},
        },
    }
    plan = write_plan(tmp_path / "plan", rows=[row], metadata={"scope": "TEST_ONLY"})

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "test"})
        if request.url.path == "/api/tags":
            return httpx.Response(
                200, json={"models": [{"name": "qwen2.5:3b", "digest": "a" * 64}]}
            )
        return httpx.Response(
            200,
            json={
                "model": "qwen2.5:3b",
                "done": True,
                "done_reason": "stop",
                "message": {"content": "No available function can answer this question."},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        execute_plan(plan, tmp_path / "run", client=client)
    report = build_report(tmp_path / "run", source_root / "upstream")
    model = report["models"]["qwen2.5:3b"]
    assert model["official_correct_full_denominator"] == 1
    assert model["correct_full_denominator"] == 1
    assert model["strict_correct_full_denominator"] == 0
    assert model["primary_metric"] == "pinned_official_bfcl_subset_validity"
    assert report["per_case"][0]["parse_failed"] is True


def test_pairwise_bootstrap_is_same_case_stratified_exploratory_and_deterministic(
    tmp_path: Path,
) -> None:
    report = build_report(make_rag_run(tmp_path))
    comparison = report["paired_comparisons"][0]
    assert comparison["paired_case_count"] == 4
    assert comparison["right_minus_left_accuracy"] == -0.25
    assert comparison["bootstrap_resamples"] == 2000
    assert comparison["bootstrap_seed"] == 20260912
    assert comparison["strata"] == {"finqa": 2, "hotpotqa": 2}
    assert comparison["exploratory_not_confirmatory"] is True
    assert comparison["simultaneous_inference_adjusted"] is False
    assert (
        report["models"]["qwen2.5:3b"]["timing"]["measurement_isolation"] == "OBSERVED_NON_ISOLATED"
    )


def test_export_offline_verify_rejects_rehashed_report_changes_and_never_overwrites(
    tmp_path: Path,
) -> None:
    run = make_rag_run(tmp_path)
    output = tmp_path / "report"
    write_report(run, output)
    assert verify_report(output, run)["status"] == "REPORT_RECOMPUTED"
    with pytest.raises(FileExistsError):
        write_report(run, output)
    summary = read_json(output / "report.json")
    summary["models"]["qwen2.5:3b"]["accuracy_full_denominator"] = 1.0
    fake = encoded(summary)
    (output / "report.json").write_bytes(fake)
    manifest = read_json(output / "manifest.json")
    manifest["files"]["report.json"] = hashlib.sha256(fake).hexdigest()
    (output / "manifest.json").write_bytes(encoded(manifest))
    with pytest.raises(ValueError, match="recomputed"):
        verify_report(output, run)


def test_actual_report_cli_runs_and_verifies_without_target_access(tmp_path: Path) -> None:
    run = make_rag_run(tmp_path)
    output = tmp_path / "report"
    base = [sys.executable, "-m", "scripts.report_local_public_benchmarks"]
    reported = subprocess.run(
        base + ["report", "--run-dir", str(run), "--output-dir", str(output)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert reported.returncode == 0, reported.stderr
    verified = subprocess.run(
        base + ["verify", "--run-dir", str(run), "--report-dir", str(output)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert verified.returncode == 0, verified.stderr
    assert json.loads(verified.stdout)["status"] == "REPORT_RECOMPUTED"


def test_absent_and_unknown_attempts_remain_in_report_without_invented_predictions(
    tmp_path: Path,
) -> None:
    run = make_rag_run(tmp_path)
    rows = read_json(run / "plan.json")["requests"][:2]
    for suffix in (".result.json", ".intent.json"):
        (run / "attempts" / (rows[0]["request_id"] + suffix)).unlink()
    (run / "attempts" / (rows[1]["request_id"] + ".result.json")).unlink()
    report = build_report(run)
    model = report["models"]["qwen2.5:3b"]
    assert model["planned"] == 4
    assert model["correct_full_denominator"] == 0
    assert model["statuses"]["NOT_ATTEMPTED"] == 1
    assert model["statuses"]["ATTEMPT_OUTCOME_UNKNOWN"] == 1
    assert model["calibration"]["paired_count"] == 0
    assert report["verification"]["complete"] is False
